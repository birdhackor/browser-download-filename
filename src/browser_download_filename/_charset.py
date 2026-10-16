"""Charset names and decoding as Chromium's ICU build resolves them.

Chromium opens converters with ICU's ucnv_open(), which matches names
loosely (case, punctuation and some leading zeros are ignored) against an
alias table that Chromium trims to the WHATWG Encoding Standard labels. So
"ISO-8859-1", "latin1" and "us-ascii" all mean windows-1252, while "UTF-7",
"UTF-32" and "ISO-2022-KR" cannot be opened at all.
"""

from __future__ import annotations

import codecs
import unicodedata
from collections.abc import Callable
from functools import lru_cache

from ._data import (
    CHARSET_ALIASES,
    MULTI_BYTE_CODECS,
    MULTI_BYTE_OVERRIDE_RUNS,
    MULTI_BYTE_OVERRIDE_TEXTS,
    MULTI_BYTE_REJECT_RUNS,
    MULTI_BYTE_STATES,
    SINGLE_BYTE_TABLES,
)

# ICU's UCNV_MAX_CONVERTER_NAME_LENGTH: longer names never open.
_MAX_NAME_LENGTH = 60
_ASCII_HALF = "".join(map(chr, range(0x80)))
_REPLACEMENT_CHARACTER = chr(0xFFFD)

Decoder = Callable[[bytes, str], str]


def strip_for_compare(name: bytes) -> str:
    """ICU's ucnv_io_stripASCIIForCompare.

    Keeps ASCII letters (lowercased) and digits, drops a '0' that starts a
    number and is followed by another digit, and ignores everything else,
    non-ASCII bytes included.
    """
    out: list[str] = []
    after_digit = False
    length = len(name)
    for index, byte in enumerate(name):
        if 0x41 <= byte <= 0x5A or 0x61 <= byte <= 0x7A:
            out.append(chr(byte | 0x20))
            after_digit = False
        elif byte == 0x30:
            following = name[index + 1] if index + 1 < length else 0
            if not after_digit and 0x30 <= following <= 0x39:
                continue
            out.append("0")
        elif 0x31 <= byte <= 0x39:
            out.append(chr(byte))
            after_digit = True
        else:
            after_digit = False
    return "".join(out)


def _single_byte_decoder(table: str) -> Decoder:
    def decode(data: bytes, errors: str) -> str:
        return codecs.charmap_decode(data, errors, table)[0]

    return decode


def _codec_decoder(codec: str) -> Decoder:
    def decode(data: bytes, errors: str) -> str:
        return data.decode(codec, errors)

    return decode


def _state_rows(converter: str) -> list[list[tuple[int, str]]]:
    rows = []
    for state in MULTI_BYTE_STATES[converter]:
        row = [(-1, "i")] * 256
        for low, high, following, action in state:
            for byte in range(low, high + 1):
                row[byte] = (following, action)
        rows.append(row)
    return rows


def _single_or_lead_bytes(rows: list[list[tuple[int, str]]]) -> list[bool]:
    """ICU's isSingleOrLead() for the initial state, for every byte."""
    memo: dict[int, bool] = {}

    def has_valid_trail_bytes(state: int, seen: frozenset[int]) -> bool:
        if state in memo:
            return memo[state]
        row = rows[state]
        result = any(following < 0 and action != "i" for following, action in row) or any(
            following >= 0
            and following not in seen
            and has_valid_trail_bytes(following, seen | {state})
            for following, _action in row
        )
        memo[state] = result
        return result

    return [
        has_valid_trail_bytes(following, frozenset()) if following >= 0 else action != "i"
        for following, action in rows[0]
    ]


def _expand_runs(first: bytes, count: int) -> list[bytes]:
    return [first[:-1] + bytes((first[-1] + offset,)) for offset in range(count)]


def _multi_byte_decoder(converter: str, codec: str) -> Decoder:
    """A Python codec corrected to Chromium's ICU converter.

    The bytes are split into characters by ICU's state table for the
    converter, including how ICU delimits an illegal sequence; each character
    is then decoded by the Python codec unless ICU maps it differently or not
    at all.
    """
    rows = _state_rows(converter)
    single_or_lead = _single_or_lead_bytes(rows)
    overrides = dict(MULTI_BYTE_OVERRIDE_TEXTS[converter])
    for first, count, code_point in MULTI_BYTE_OVERRIDE_RUNS[converter]:
        for offset, character in enumerate(_expand_runs(first, count)):
            overrides[character] = chr(code_point + offset)
    rejects = {
        character
        for first, count in MULTI_BYTE_REJECT_RUNS[converter]
        for character in _expand_runs(first, count)
    }

    def decode(data: bytes, errors: str) -> str:
        pieces: list[str] = []
        start = 0
        length = len(data)
        while start < length:
            state = 0
            end = start
            text: str | None = None
            while end < length:
                following, action = rows[state][data[end]]
                end += 1
                if following >= 0:
                    state = following
                    continue
                if action == "i":
                    # ICU ticket 5691: an illegal sequence stops before its first
                    # non-initial byte that could start a character.
                    end = next(
                        (split for split in range(start + 1, end) if single_or_lead[data[split]]),
                        end,
                    )
                else:
                    character = data[start:end]
                    text = overrides.get(character)
                    if text is None and character not in rejects:
                        try:
                            text = character.decode(codec)
                        except UnicodeDecodeError:
                            text = None
                break
            # Reaching the end mid-character leaves text None: truncated.
            if text is None:
                if errors == "strict":
                    raise UnicodeDecodeError(
                        converter, data, start, end, "not decodable by Chromium's ICU"
                    )
                text = _REPLACEMENT_CHARACTER
            pieces.append(text)
            start = end
        return "".join(pieces)

    return decode


@lru_cache(maxsize=512)
def lookup(name: bytes) -> Decoder | None:
    """The decoder ucnv_open(name) would give Chromium, or None if it fails."""
    # ICU takes a C string, then splits off ",option=value" suffixes.
    name = name.split(b"\0", 1)[0].split(b",", 1)[0]
    if len(name) >= _MAX_NAME_LENGTH:
        return None
    converter = CHARSET_ALIASES.get(strip_for_compare(name))
    if converter is None:
        return None
    table = SINGLE_BYTE_TABLES.get(converter)
    if table is not None:
        return _single_byte_decoder(_ASCII_HALF + table)
    codec = MULTI_BYTE_CODECS[converter]
    if codec is None:
        return None
    if converter in MULTI_BYTE_STATES:
        return _multi_byte_decoder(converter, codec)
    return _codec_decoder(codec)


def decode_strict(data: bytes, charset: bytes) -> str | None:
    """base::CodepageToUTF16 with OnStringConversionError::FAIL."""
    decoder = lookup(charset)
    if decoder is None:
        return None
    try:
        return decoder(data, "strict")
    except UnicodeDecodeError:
        return None


def decode_substituting(data: bytes, charset: bytes) -> str | None:
    """net::ConvertToUtf8: ICU's default callback substitutes U+FFFD."""
    decoder = lookup(charset)
    if decoder is None:
        return None
    return decoder(data, "replace")


def decode_strict_nfc(data: bytes, charset: bytes) -> str | None:
    """base::ConvertToUtf8AndNormalize: strict decoding, then NFC."""
    text = decode_strict(data, charset)
    return None if text is None else unicodedata.normalize("NFC", text)


def require_charset(name: str | None) -> bytes | None:
    """Validate a caller-supplied fallback charset name."""
    if name is None:
        return None
    if not isinstance(name, str):
        raise TypeError(f"fallback_charset must be str or None, not {type(name).__name__}")
    encoded = name.encode("utf-8", "surrogateescape")
    if lookup(encoded) is None:
        raise LookupError(
            f"unknown charset {name!r}: Chromium cannot decode it "
            "(use a WHATWG Encoding Standard label such as 'windows-1252' or 'big5')"
        )
    return encoded
