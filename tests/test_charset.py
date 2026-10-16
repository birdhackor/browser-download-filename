"""Charset name resolution and decoding, checked against Chromium's ICU."""

from __future__ import annotations

import codecs
import hashlib

import pytest

from browser_download_filename import parse_content_disposition
from browser_download_filename._charset import _state_rows, lookup, strip_for_compare
from browser_download_filename._data import (
    CHARSET_ALIASES,
    MULTI_BYTE_CODECS,
    MULTI_BYTE_DIGESTS,
    MULTI_BYTE_STATES,
    SINGLE_BYTE_TABLES,
)


@pytest.mark.parametrize(
    ("name", "stripped"),
    [
        (b"UTF-8", "utf8"),
        (b"U-T-F-8", "utf8"),
        (b"ISO_8859-1:1987", "iso885911987"),
        (b"iso-8859-01", "iso88591"),
        (b"windows-0874", "windows874"),
        (b"iso-8859-10", "iso885910"),
        (b"utf\xff-8", "utf8"),
        (b"  latin1 ", "latin1"),
        (b"0", "0"),
        (b"00", "0"),
    ],
)
def test_strip_for_compare_matches_icu(name: bytes, stripped: str) -> None:
    assert strip_for_compare(name) == stripped


@pytest.mark.parametrize(
    "name",
    [
        b"utf8",
        b"U-T-F-8",
        b"UTF8 ",
        b"iso-8859-01",
        b"ISO8859_1",
        b"US_ASCII",
        b"utf\xff-8",
        b"utf-8,locale=ja",
        b"utf-8\0junk",
        b"utf-8" + b"-" * 54,
        b"windows-1252-html",
        b"ms932",
        b"ksc5601",
        b"x-x-big5",
    ],
)
def test_names_chromium_opens(name: bytes) -> None:
    assert lookup(name) is not None


@pytest.mark.parametrize(
    "name",
    [
        b"",
        b"x-user-defined",
        b"cp932",
        b"8859-1",
        b"utf-7",
        b"UTF-32",
        b"scsu",
        b"bocu-1",
        b"cesu-8",
        b"ISO-2022-KR",
        b"iso-2022-cn",
        b"hz-gb-2312",
        b"replacement",
        b"utf-8" + b"-" * 55,
        b"\0utf-8",
    ],
)
def test_names_chromium_cannot_open(name: bytes) -> None:
    assert lookup(name) is None


@pytest.mark.parametrize(
    "label", ["ISO-8859-1", "latin1", "us-ascii", "ascii", "iso_8859-1:1987", "cp819"]
)
def test_latin1_labels_mean_windows_1252(label: str) -> None:
    # Chromium's ICU follows the WHATWG Encoding Standard here.
    header = f"attachment; filename*={label}''%80%81%E9.txt"
    assert parse_content_disposition(header).filename == "€\x81é.txt"


def test_every_alias_resolves() -> None:
    converters = set(SINGLE_BYTE_TABLES) | set(MULTI_BYTE_CODECS)
    assert set(CHARSET_ALIASES.values()) <= converters
    for alias in CHARSET_ALIASES:
        assert strip_for_compare(alias.encode()) == alias


@pytest.mark.parametrize("converter", sorted(SINGLE_BYTE_TABLES))
def test_single_byte_tables(converter: str) -> None:
    table = SINGLE_BYTE_TABLES[converter]
    assert len(table) == 128
    decoder = lookup(converter.encode())
    assert decoder is not None
    assert decoder(bytes(range(0x80)), "strict") == "".join(map(chr, range(0x80)))
    for index, expected in enumerate(table):
        byte = bytes((0x80 + index,))
        if expected == "\ufffe":
            with pytest.raises(UnicodeDecodeError):
                decoder(byte, "strict")
            assert decoder(byte, "replace") == "�"
        else:
            assert decoder(byte, "strict") == expected


@pytest.mark.parametrize("codec", sorted({c for c in MULTI_BYTE_CODECS.values() if c}))
def test_python_has_codec(codec: str) -> None:
    codecs.lookup(codec)


def _state_table_characters(converter: str) -> list[bytes]:
    """What scripts/generate_data.py enumerates for MULTI_BYTE_DIGESTS."""
    rows = _state_rows(converter)
    units: list[bytes] = []

    def walk(prefix: bytes, state: int) -> None:
        for byte, (following, action) in enumerate(rows[state]):
            sequence = prefix + bytes((byte,))
            if following >= 0:
                if len(sequence) < 3:
                    walk(sequence, following)
            elif action != "i":
                units.append(sequence)

    walk(b"", 0)
    return units


@pytest.mark.parametrize("converter", sorted(MULTI_BYTE_STATES))
def test_multi_byte_decoders_match_icu(converter: str) -> None:
    """The Python codec plus overrides decodes exactly what ICU's table does.

    The digest was computed from Chromium's .ucm file by the generator; this
    recomputes it with this interpreter's codecs.
    """
    decoder = lookup(converter.encode())
    assert decoder is not None
    digest = hashlib.sha256()
    for unit in _state_table_characters(converter):
        try:
            decoded: str | None = decoder(unit, "strict")
        except UnicodeDecodeError:
            decoded = None
        digest.update(unit.hex().encode() + b"=")
        digest.update(b"!" if decoded is None else decoded.encode("utf-8", "surrogatepass"))
        digest.update(b";")
    assert digest.hexdigest() == MULTI_BYTE_DIGESTS[converter]


@pytest.mark.parametrize(
    ("label", "data", "expected"),
    [
        # An illegal trail byte that could start a character is not swallowed.
        ("shift_jis", b"x\xf9\x40x", "x�@x"),
        # One that could not is part of the illegal sequence.
        ("shift_jis", b"x\xf9\xfdx", "x�x"),
        # A character cut off by the end of the input.
        ("shift_jis", b"x\x81", "x�"),
        ("big5", b"\xa3\xe1", "€"),
        ("gbk", b"\x80", "€"),
        ("gb18030", b"\xa3\xa0", "\u3000"),
        ("gb18030", b"\x81\x35\xf4\x37", "\ue7c7"),
        ("gb18030", b"\x90\x30\x81\x30", "\U00010000"),
        ("euc-jp", b"\xad\xe2", "№"),
        ("euc-kr", b"\xb0\xa1", "가"),
    ],
)
def test_multi_byte_decoding(label: str, data: bytes, expected: str) -> None:
    decoder = lookup(label.encode())
    assert decoder is not None
    assert decoder(data, "replace") == expected


@pytest.mark.parametrize(
    ("label", "data"),
    [
        ("shift_jis", b"\xf9\x40"),
        ("shift_jis", b"\xf9\x80"),
        ("shift_jis", b"\xa0"),
        ("big5", b"\xa4"),
    ],
)
def test_multi_byte_strict_failures(label: str, data: bytes) -> None:
    decoder = lookup(label.encode())
    assert decoder is not None
    with pytest.raises(UnicodeDecodeError):
        decoder(data, "strict")


def test_rfc2047_substitutes_but_ext_value_fails() -> None:
    # ConvertToUtf8 substitutes; ConvertToUtf8AndNormalize fails.
    assert parse_content_disposition(b'attachment; filename="=?utf-8?Q?=FF.txt?="').filename == (
        "�.txt"
    )
    assert parse_content_disposition(b"attachment; filename*=utf-8''%FF.txt").filename is None


def test_ext_value_is_nfc_normalized_but_filename_is_not() -> None:
    nfd = "a\u0308.txt"
    assert parse_content_disposition(b"attachment; filename*=UTF-8''a%CC%88.txt").filename == (
        "ä.txt"
    )
    assert parse_content_disposition(f'attachment; filename="{nfd}"').filename == nfd
