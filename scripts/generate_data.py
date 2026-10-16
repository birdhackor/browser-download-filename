#!/usr/bin/env python3
"""Regenerate src/browser_download_filename/_data.py from pinned upstream sources.

The tables mirror what Chromium uses at CHROMIUM_REVISION:

* charset aliases and the single-byte mapping tables from the ICU data that
  Chromium ships (chromium/deps/icu at the revision Chromium's DEPS pins);
* the MIME type to file extension tables in net/base/mime_util.cc;
* the Unicode "Other, format" (Cf) code points, taken from this interpreter's
  unicodedata, which must match the Unicode version of that ICU.

Run it with the newest CPython (see UNICODE_VERSION) after bumping the pins:

    uv run --python 3.15 scripts/generate_data.py
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

CHROMIUM_REVISION = "dfd5cca812cefda32e909ae39965ed22041d5e65"
CHROMIUM_COMMIT_POSITION = "refs/heads/main@{#1720588}"
# The chromium/deps/icu revision that DEPS pins at CHROMIUM_REVISION.
ICU_REVISION = "4fe960221710e5b5524ac6e49a454bbb8bfc295d"
# ICU 78 implements Unicode 17.0.
UNICODE_VERSION = "17.0.0"

GITILES = "https://chromium.googlesource.com"
OUTPUT = Path(__file__).resolve().parents[1] / "src/browser_download_filename/_data.py"

# Converters decoded with a Python codec, corrected to ICU where they differ.
STATE_TABLE_CONVERTERS = (
    "big5-html",
    "euc-jp-html",
    "euc-kr-html",
    "gb18030",
    "shift_jis-html",
    "windows-936-2000",
)

# Converters in Chromium's alias table that are not single-byte tables, mapped
# to the closest Python codec. None marks a converter whose data Chromium does
# not ship, so opening it fails there too. A converter missing from both this
# dict and the single-byte tables stops the generator: decide on it by hand.
MULTI_BYTE_CODECS: dict[str, str | None] = {
    "UTF-8": "utf-8",
    "utf-16be": "utf-16-be",
    "utf-16le": "utf-16-le",
    "windows-936-2000": "gbk",
    "gb18030": "gb18030",
    "big5-html": "big5hkscs",
    "euc-jp-html": "euc_jp",
    "ISO_2022,locale=ja,version=0": "iso2022_jp",
    "shift_jis-html": "cp932",
    "euc-kr-html": "cp949",
    "ISO-2022-KR": None,
    "ISO-2022-CN": None,
    "ISO-2022-CN-EXT": None,
    "HZ-GB-2312": None,
}


# A state of an ICU MBCS state table: (first byte, last byte, next state or -1
# for a final entry, action) entries, applied in order so that later entries
# win. Actions: "" (valid), "u" (unassigned), "i" (illegal), "p" (valid,
# possibly a surrogate pair). Bytes no entry covers are illegal.
State = list[tuple[int, int, int, str]]


def parse_states(text: str) -> list[State]:
    states: list[State] = []
    for line in text.splitlines():
        if not line.startswith("<icu:state>"):
            continue
        state: State = []
        for item in line[len("<icu:state>") :].split("#", 1)[0].split(","):
            match = re.fullmatch(
                r"\s*([0-9a-f]{1,2})(?:-([0-9a-f]{1,2}))?(?::([0-9a-f]+))?(?:\.([uips]))?\s*", item
            )
            if match is None:
                raise SystemExit(f"unexpected state entry {item!r}")
            low = int(match[1], 16)
            high = int(match[2], 16) if match[2] else low
            following = int(match[3], 16) if match[3] else -1
            state.append((low, high, following, match[4] or ""))
        states.append(state)
    if not states:
        raise SystemExit("no <icu:state> lines")
    return states


def state_rows(states: list[State]) -> list[list[tuple[int, str]]]:
    rows = []
    for state in states:
        row = [(-1, "i")] * 256
        for low, high, following, action in state:
            for byte in range(low, high + 1):
                row[byte] = (following, action)
        rows.append(row)
    return rows


def state_units(states: list[State], *, max_length: int) -> list[bytes]:
    """Every sequence the state table accepts as one character."""
    rows = state_rows(states)
    units: list[bytes] = []

    def walk(prefix: bytes, state: int) -> None:
        for byte, (following, action) in enumerate(rows[state]):
            sequence = prefix + bytes((byte,))
            if following >= 0:
                if len(sequence) < max_length:
                    walk(sequence, following)
            elif action != "i":
                units.append(sequence)

    walk(b"", 0)
    return units


def parse_multi_byte_ucm(text: str) -> dict[bytes, str]:
    """Byte sequence -> decoded text for every toUnicode mapping."""
    table: dict[bytes, str] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        match = re.fullmatch(
            r"((?:<U[0-9A-F]{4,6}>)+)\s+((?:\\x[0-9A-F]{2})+)(?:\s+\|([0-4]))?", line
        )
        if match is None or (match[3] or "0") not in ("0", "3"):
            continue
        decoded = "".join(chr(int(cp, 16)) for cp in re.findall(r"<U([0-9A-F]+)>", match[1]))
        sequence = bytes(int(byte, 16) for byte in re.findall(r"\\x([0-9A-F]{2})", match[2]))
        if table.setdefault(sequence, decoded) != decoded:
            raise SystemExit(f"{sequence.hex()} has two decodings")
    return table


def python_decode(unit: bytes, codec: str) -> str | None:
    try:
        return unit.decode(codec)
    except UnicodeDecodeError:
        return None


def compress_runs(
    items: list[tuple[bytes, str | None]],
) -> tuple[list[tuple[bytes, int, int]], dict[bytes, str]]:
    """Fold units that differ by one in the last byte into (first, count, cp).

    For rejects (text None) the code point is -1. Mappings to several code
    points cannot be folded and are returned separately.
    """
    runs: list[tuple[bytes, int, int]] = []
    texts: dict[bytes, str] = {}
    for unit, decoded in sorted(items, key=lambda item: (len(item[0]), item[0])):
        if decoded is not None and len(decoded) != 1:
            texts[unit] = decoded
            continue
        code_point = -1 if decoded is None else ord(decoded)
        if runs:
            first, count, first_cp = runs[-1]
            last = first[:-1] + bytes((first[-1] + count - 1,))
            if (
                len(unit) == len(first)
                and unit[:-1] == first[:-1]
                and unit[-1] == last[-1] + 1
                and (code_point == -1) == (first_cp == -1)
                and (code_point == -1 or code_point == first_cp + count)
            ):
                runs[-1] = (first, count + 1, first_cp)
                continue
        runs.append((unit, 1, code_point))
    return runs, texts


def mapping_digest(units: list[bytes], decode: object) -> str:
    """SHA-256 over every unit and what it decodes to ("!" when it does not).

    tests/test_charset.py recomputes this with the package's decoders, so any
    disagreement with ICU, on any Python version, fails the tests.
    """
    import hashlib

    assert callable(decode)
    digest = hashlib.sha256()
    for unit in units:
        decoded = decode(unit)
        digest.update(unit.hex().encode() + b"=")
        digest.update(b"!" if decoded is None else decoded.encode("utf-8", "surrogatepass"))
        digest.update(b";")
    return digest.hexdigest()


def fetch(project: str, revision: str, path: str) -> str:
    url = f"{GITILES}/{project}/+/{revision}/{path}?format=TEXT"
    request = urllib.request.Request(url, headers={"User-Agent": "generate-data"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return base64.b64decode(response.read()).decode("utf-8")


def strip_for_compare(name: str) -> str:
    """ICU's ucnv_io_stripASCIIForCompare, which alias lookups go through."""
    out: list[str] = []
    after_digit = False
    for index, char in enumerate(name):
        if char.isascii() and char.isalpha():
            out.append(char.lower())
            after_digit = False
        elif char == "0":
            following = name[index + 1 : index + 2]
            if not after_digit and following.isascii() and following.isdigit():
                continue
            out.append(char)
        elif char.isascii() and char.isdigit():
            out.append(char)
            after_digit = True
        else:
            after_digit = False
    return "".join(out)


def parse_alias_table(text: str) -> dict[str, list[str]]:
    logical: list[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line[0].isspace() and logical:
            logical[-1] += " " + line.strip()
        else:
            logical.append(line.strip())
    converters: dict[str, list[str]] = {}
    for entry in logical:
        if entry.startswith("{"):
            continue  # the tag affinity list at the top of the file
        words = re.sub(r"\{[^}]*\}", " ", entry).split()
        name, aliases = words[0], words[1:]
        if name in converters:
            raise SystemExit(f"converter listed twice: {name}")
        converters[name] = aliases
    return converters


def parse_single_byte_ucm(text: str) -> str | None:
    """Return the 0x80-0xFF decode table, or None if this is not SBCS."""
    if not re.search(r'<uconv_class>\s+"SBCS"', text):
        return None
    table: dict[int, int] = {}
    in_charmap = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line == "CHARMAP":
            in_charmap = True
            continue
        if line == "END CHARMAP":
            break
        if not in_charmap or not line:
            continue
        match = re.fullmatch(r"<U([0-9A-F]{4,6})>\s+\\x([0-9A-F]{2})(?:\s+\|([0-3]))?", line)
        if match is None:
            raise SystemExit(f"unexpected mapping line: {line!r}")
        code_point, byte, precision = int(match[1], 16), int(match[2], 16), match[3] or "0"
        if precision not in ("0", "3"):
            continue  # |1 and |2 only apply when encoding
        if byte in table and table[byte] != code_point:
            raise SystemExit(f"byte {byte:#04x} has two decodings")
        table[byte] = code_point
    for byte in range(0x80):
        if table.get(byte) != byte:
            raise SystemExit(f"byte {byte:#04x} is not ASCII in a single-byte table")
    return "".join(chr(table.get(byte, 0xFFFE)) for byte in range(0x80, 0x100))


def parse_mime_mappings(source: str, array: str) -> list[tuple[str, tuple[str, ...]]]:
    match = re.search(rf"static const MimeInfo {array}\[\] = \{{(.*?)\n\}};", source, re.DOTALL)
    if match is None:
        raise SystemExit(f"cannot find {array} in mime_util.cc")
    body = re.sub(r"//[^\n]*", "", match[1])
    # Adjacent C++ string literals are concatenated.
    body = re.sub(r'"\s*\n\s*"', "", body)
    entries = re.findall(r'\{\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\}', body)
    return [(mime, tuple(exts.split(","))) for mime, exts in entries]


def format_cf_ranges() -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for code_point in range(0x110000):
        if unicodedata.category(chr(code_point)) != "Cf":
            continue
        if ranges and ranges[-1][1] == code_point - 1:
            ranges[-1] = (ranges[-1][0], code_point)
        else:
            ranges.append((code_point, code_point))
    return ranges


def render(
    aliases: dict[str, str],
    single_byte: dict[str, str],
    multi_byte: dict[str, str | None],
    override_runs: dict[str, list[tuple[bytes, int, int]]],
    override_texts: dict[str, dict[bytes, str]],
    reject_runs: dict[str, list[tuple[bytes, int, int]]],
    digests: dict[str, str],
    states_by_converter: dict[str, list[State]],
    primary: list[tuple[str, tuple[str, ...]]],
    secondary: list[tuple[str, tuple[str, ...]]],
    cf_ranges: list[tuple[int, int]],
) -> str:
    lines = [
        '"""Tables generated by scripts/generate_data.py. Do not edit by hand.',
        "",
        f"Chromium {CHROMIUM_REVISION} ({CHROMIUM_COMMIT_POSITION}),",
        f"chromium/deps/icu {ICU_REVISION}, Unicode {UNICODE_VERSION}.",
        "",
        "The charset tables derive from Chromium's ICU data files (Unicode-3.0;",
        "the single-byte ones are generated from the WHATWG Encoding Standard",
        "indexes) and the MIME tables from Chromium's net/base/mime_util.cc",
        "(BSD-3-Clause); see THIRD-PARTY-LICENSES.",
        '"""',
        "",
        f'CHROMIUM_REVISION = "{CHROMIUM_REVISION}"',
        f'ICU_REVISION = "{ICU_REVISION}"',
        f'UNICODE_VERSION = "{UNICODE_VERSION}"',
        "",
        "# ICU-normalized charset name -> converter name.",
        "CHARSET_ALIASES: dict[str, str] = {",
    ]
    lines += [f"    {alias!r}: {converter!r}," for alias, converter in sorted(aliases.items())]
    lines += [
        "}",
        "",
        "# Converter -> decodings of bytes 0x80-0xFF; U+FFFE marks unmapped bytes.",
        "# Bytes 0x00-0x7F decode to themselves in every one of these tables.",
        "SINGLE_BYTE_TABLES: dict[str, str] = {",
    ]
    for converter, table in sorted(single_byte.items()):
        lines.append(f"    {converter!r}: (")
        for start in range(0, 128, 16):
            chunk = table[start : start + 16].encode("unicode_escape").decode("ascii")
            chunk = chunk.replace('"', '\\"')
            lines.append(f'        "{chunk}"')
        lines.append("    ),")
    lines += [
        "}",
        "",
        "# Converter -> closest Python codec; None where Chromium cannot open it.",
        "MULTI_BYTE_CODECS: dict[str, str | None] = {",
    ]
    lines += [f"    {name!r}: {codec!r}," for name, codec in sorted(multi_byte.items())]
    lines += [
        "}",
        "",
        "# Converter -> ICU MBCS state table: per state, (first byte, last byte,",
        "# next state or -1 if final, action) entries; later entries win and",
        "# uncovered bytes are illegal. Actions: '' or 'p' valid, 'u' unassigned,",
        "# 'i' illegal.",
        "MULTI_BYTE_STATES: dict[str, tuple[tuple[tuple[int, int, int, str], ...], ...]] = {",
    ]
    for name, states in sorted(states_by_converter.items()):
        lines.append(f"    {name!r}: (")
        for state in states:
            entries = ", ".join(
                f"(0x{low:02X}, 0x{high:02X}, {following}, {action!r})"
                for low, high, following, action in state
            )
            lines.append(f"        ({entries},),")
        lines.append("    ),")
    lines += [
        "}",
        "",
        "# Where Chromium's ICU table and the Python codec disagree on a",
        "# well-formed character: runs of (first byte sequence, count, first code",
        "# point), each next character one higher in its last byte and code point.",
        "MULTI_BYTE_OVERRIDE_RUNS: dict[str, tuple[tuple[bytes, int, int], ...]] = {",
    ]
    for name, runs in sorted(override_runs.items()):
        lines.append(f"    {name!r}: (")
        lines += [f"        ({unit!r}, {count}, 0x{cp:04X})," for unit, count, cp in runs]
        lines.append("    ),")
    lines += [
        "}",
        "",
        "# Overrides that decode to more than one code point.",
        "MULTI_BYTE_OVERRIDE_TEXTS: dict[str, dict[bytes, str]] = {",
    ]
    for name, texts in sorted(override_texts.items()):
        lines.append(f"    {name!r}: {{")
        lines += [f"        {unit!r}: {text!r}," for unit, text in sorted(texts.items())]
        lines.append("    },")
    lines += [
        "}",
        "",
        "# Well-formed characters the Python codec decodes but ICU has no mapping",
        "# for: runs of (first byte sequence, count).",
        "MULTI_BYTE_REJECT_RUNS: dict[str, tuple[tuple[bytes, int], ...]] = {",
    ]
    for name, runs in sorted(reject_runs.items()):
        lines.append(f"    {name!r}: (")
        lines += [f"        ({unit!r}, {count})," for unit, count, _ in runs]
        lines.append("    ),")
    lines += [
        "}",
        "",
        "# SHA-256 of ICU's decoding of every character its state table accepts",
        "# (up to three bytes long); see tests/test_charset.py.",
        "MULTI_BYTE_DIGESTS: dict[str, str] = {",
    ]
    lines += [f"    {name!r}: {digest!r}," for name, digest in sorted(digests.items())]
    lines += ["}", "", "MIME_PRIMARY_MAPPINGS: tuple[tuple[str, tuple[str, ...]], ...] = ("]
    lines += [f"    ({mime!r}, {exts!r})," for mime, exts in primary]
    lines += [")", "", "MIME_SECONDARY_MAPPINGS: tuple[tuple[str, tuple[str, ...]], ...] = ("]
    lines += [f"    ({mime!r}, {exts!r})," for mime, exts in secondary]
    lines += [
        ")",
        "",
        "# Inclusive code point ranges of general category Cf.",
        "FORMAT_RANGES: tuple[tuple[int, int], ...] = (",
    ]
    lines += [f"    (0x{start:04X}, 0x{end:04X})," for start, end in cf_ranges]
    lines += [")", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if _data.py is stale")
    args = parser.parse_args()

    if unicodedata.unidata_version != UNICODE_VERSION:
        raise SystemExit(
            f"run this with a Python whose unicodedata is {UNICODE_VERSION}, "
            f"not {unicodedata.unidata_version}"
        )

    converters = parse_alias_table(
        fetch("chromium/deps/icu", ICU_REVISION, "source/data/mappings/convrtrs.txt")
    )
    aliases: dict[str, str] = {}
    single_byte: dict[str, str] = {}
    multi_byte: dict[str, str | None] = {}
    for converter, names in converters.items():
        if converter in MULTI_BYTE_CODECS:
            multi_byte[converter] = MULTI_BYTE_CODECS[converter]
        elif converter.endswith("-html"):
            table = parse_single_byte_ucm(
                fetch("chromium/deps/icu", ICU_REVISION, f"source/data/mappings/{converter}.ucm")
            )
            if table is None:
                raise SystemExit(f"{converter} is not single-byte; add it to MULTI_BYTE_CODECS")
            single_byte[converter] = table
        else:
            raise SystemExit(f"unclassified converter {converter}; add it to MULTI_BYTE_CODECS")
        for name in (converter, *names):
            previous = aliases.setdefault(strip_for_compare(name), converter)
            if previous != converter:
                raise SystemExit(f"alias {name!r} names both {previous} and {converter}")
    unused = set(MULTI_BYTE_CODECS) - set(multi_byte)
    if unused:
        raise SystemExit(f"MULTI_BYTE_CODECS lists converters ICU no longer has: {sorted(unused)}")

    override_runs: dict[str, list[tuple[bytes, int, int]]] = {}
    override_texts: dict[str, dict[bytes, str]] = {}
    reject_runs: dict[str, list[tuple[bytes, int, int]]] = {}
    digests: dict[str, str] = {}
    states_by_converter: dict[str, list[State]] = {}
    for converter in sorted(STATE_TABLE_CONVERTERS):
        codec = MULTI_BYTE_CODECS[converter]
        assert codec is not None
        ucm = fetch("chromium/deps/icu", ICU_REVISION, f"source/data/mappings/{converter}.ucm")
        icu = parse_multi_byte_ucm(ucm)
        states_by_converter[converter] = parse_states(ucm)
        # GB18030's four-byte characters are algorithmic in both ICU and
        # Python; only the ones the .ucm lists explicitly are compared.
        units = state_units(states_by_converter[converter], max_length=3)
        well_formed = set(units)
        stray = [unit for unit in icu if len(unit) < 4 and unit not in well_formed]
        if stray:
            raise SystemExit(f"{converter}: state table misses {stray[0].hex()}")
        overrides: list[tuple[bytes, str | None]] = [
            (unit, text) for unit, text in icu.items() if python_decode(unit, codec) != text
        ]
        rejects: list[tuple[bytes, str | None]] = [
            (unit, None)
            for unit in units
            if unit not in icu and python_decode(unit, codec) is not None
        ]
        override_runs[converter], override_texts[converter] = compress_runs(overrides)
        reject_runs[converter], _ = compress_runs(rejects)
        digests[converter] = mapping_digest(units, icu.get)

    mime_source = fetch("chromium/src", CHROMIUM_REVISION, "net/base/mime_util.cc")
    primary = parse_mime_mappings(mime_source, "kPrimaryMappings")
    secondary = parse_mime_mappings(mime_source, "kSecondaryMappings")

    text = render(
        aliases,
        single_byte,
        multi_byte,
        override_runs,
        override_texts,
        reject_runs,
        digests,
        states_by_converter,
        primary,
        secondary,
        format_cf_ranges(),
    )
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != text:
            print(f"{OUTPUT} is stale; rerun scripts/generate_data.py", file=sys.stderr)
            return 1
        print(f"{OUTPUT} is up to date")
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT}: {len(aliases)} aliases, {len(single_byte)} single-byte tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
