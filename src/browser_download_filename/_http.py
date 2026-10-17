"""Header lines and values as Chromium's HttpUtil reads them.

Ported from Chromium's net/http/http_util.cc and base/strings/string_tokenizer.h
(BSD-3-Clause, see THIRD-PARTY-LICENSES).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import NamedTuple

from ._bytes import trim_lws

# A line feed, then an optional carriage return and another line feed: the
# blank line that ends the headers.
_END_OF_HEADERS = re.compile(rb"\n\r?\n")
# A run of carriage returns and line feeds, which ends a line; the empty
# lines inside a run are skipped, as base::StringTokenizer skips them.
_LINE_BREAKS = re.compile(rb"[\r\n]+")


def locate_end_of_headers(data: bytes) -> int | None:
    """HttpUtil::LocateEndOfHeaders: the offset just past the blank line.

    None if ``data`` holds no blank line. Only line feeds make the blank
    line: one carriage return between two line feeds, as in "\\n\\r\\n",
    still leaves a blank line, while two, as in "\\n\\r\\r\\n", do not. What
    follows the blank line is the body. The package looks for it in the
    value of each header line, which does not start with a line feed on the
    wire, since the header name and the colon come before it.
    """
    end = _END_OF_HEADERS.search(data)
    return None if end is None else end.end()


def assemble_raw_headers(value: bytes) -> bytes:
    """HttpUtil::AssembleRawHeaders, for the value of one header line.

    ``value`` is the rest of the header line, up to the end of the headers,
    and can hold line breaks: every run of carriage returns and line feeds
    ends a line. The first line belongs to the header, even if it is empty.
    A line that starts with a space or a tab continues the header, and is
    joined to it as one space and the line without its leading spaces and
    tabs; the spaces and tabs at the end of the line before are kept. Any
    other line is another header line, so the value ends before it. Vertical
    tabs and form feeds are neither line breaks nor spaces.
    """
    first, *rest = _LINE_BREAKS.split(value)
    if not rest:
        return first
    joined = [first]
    for line in rest:
        if line[:1] not in (b" ", b"\t"):
            # Another header line, or the end of the value.
            break
        joined.append(line.lstrip(b" \t"))
    return b" ".join(joined)


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


def comma_separated_values(data: bytes, *, ignore_empty: bool = False) -> list[bytes]:
    """All values, as HttpResponseHeaders stores a coalescable header.

    With ``ignore_empty``, values that are empty once trimmed are left out,
    as HttpUtil::ValuesIterator does by default.
    """
    return list(_split(data, _COMMA_VALUE, keep_empty=not ignore_empty))


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
