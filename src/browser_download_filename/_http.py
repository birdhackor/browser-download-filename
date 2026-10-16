"""Header value splitting as done by Chromium's HttpUtil.

Ported from Chromium's net/http/http_util.cc and base/strings/string_tokenizer.h
(BSD-3-Clause, see THIRD-PARTY-LICENSES).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import NamedTuple

from ._bytes import trim_lws

# A run of bytes up to the next delimiter, where a double-quoted section may
# contain the delimiter. Inside quotes a backslash escapes the next byte, and a
# quote that is never closed runs to the end of the input. This is what
# base::StringTokenizer does with quote_chars set to '"'.
_COMMA_VALUE = re.compile(rb'(?:[^",]|"(?:[^"\\]|\\.)*"?)*', re.DOTALL)
_SEMICOLON_VALUE = re.compile(rb'(?:[^";]|"(?:[^"\\]|\\.)*"?)*', re.DOTALL)


def _split(data: bytes, pattern: re.Pattern[bytes], *, keep_empty: bool) -> Iterator[bytes]:
    """HttpUtil::ValuesIterator: delimiter-separated values, LWS-trimmed."""
    position = 0
    length = len(data)
    while True:
        match = pattern.match(data, position)
        assert match is not None  # the pattern also matches the empty string
        value = trim_lws(match[0])
        if value or keep_empty:
            yield value
        if match.end() >= length:
            return
        position = match.end() + 1


def first_comma_separated_value(data: bytes) -> bytes:
    """The first value of a possibly comma-joined header.

    This is HttpContentDisposition's string constructor, which looks only at
    the first value since Chromium 151, so that "a, b" and two header lines
    "a" and "b" give the same result.
    """
    return next(_split(data, _COMMA_VALUE, keep_empty=True))


def comma_separated_values(data: bytes) -> list[bytes]:
    """All values, as HttpResponseHeaders stores a coalescable header."""
    return list(_split(data, _COMMA_VALUE, keep_empty=True))


class Parameter(NamedTuple):
    name: bytes
    #: The value with surrounding quotes removed and quoted-pairs unescaped.
    value: bytes
    #: The value as written, quotes included (HttpUtil's raw_value()).
    raw_value: bytes


def _unquote(value: bytes) -> bytes:
    """HttpUtil::Unquote for a value already known to be "...".

    Not strict: an unescaped quote inside is kept and a trailing lone
    backslash is dropped.
    """
    out = bytearray()
    escaped = False
    for byte in value[1:-1]:
        if byte == 0x5C and not escaped:
            escaped = True
            continue
        escaped = False
        out.append(byte)
    return bytes(out)


def parameters(data: bytes) -> Iterator[Parameter]:
    """HttpUtil::NameValuePairsIterator(data, ';') with required values.

    Iteration stops at the first item that does not parse, just as Chromium's
    iterator turns invalid and stops there; earlier parameters still count.
    """
    for item in _split(data, _SEMICOLON_VALUE, keep_empty=False):
        equals = item.find(b"=")
        if equals <= 0:
            return  # no name, or no '=' while values are required
        name = trim_lws(item[:equals])
        if b'"' in name:
            return
        value = trim_lws(item[equals + 1 :])
        if not value:
            return
        if value[0] != 0x22:
            yield Parameter(name, value, value)
        elif len(value) == 1 or value[-1] != 0x22:
            # Missing closing quote: Chromium drops the opening one and keeps
            # the rest unescaped, both as the value and as the raw value.
            yield Parameter(name, value[1:], value[1:])
        else:
            yield Parameter(name, _unquote(value), value)
