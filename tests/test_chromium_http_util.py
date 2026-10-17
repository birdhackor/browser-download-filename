"""Chromium's HttpUtil unit tests for header lines, ported.

Source: net/http/http_util_unittest.cc at the Chromium revision in
browser_download_filename._data (BSD-3-Clause, see THIRD-PARTY-LICENSES).
Cases and comments are kept in Chromium's order.

Chromium's AssembleRawHeaders test takes a whole response head. The package
reads one header value at a time, so each case is written here as the value
of one header line, with everything that follows it on the wire up to the end
of the headers, and the value Chromium assembles for that line. Cases about
the status line, which the package never sees, and about header names that
run over two lines, which the package reads as one name (see "Limits of the
port" in docs/en/behavior.md), are left out.
"""

from __future__ import annotations

import pytest

from browser_download_filename._headers import line_value
from browser_download_filename._http import assemble_raw_headers, locate_end_of_headers

# (input, expected offset); None stands for Chromium's std::string::npos.
LOCATE_END_OF_HEADERS_CASES: list[tuple[bytes, int | None]] = [
    (b"\r\n", None),
    (b"\n", None),
    (b"\r", None),
    (b"foo", None),
    (b"\r\n\r\n", 4),
    (b"foo\r\nbar\r\n\r\n", 12),
    (b"foo\nbar\n\n", 9),
    (b"foo\r\nbar\r\n\r\njunk", 12),
    (b"foo\nbar\n\njunk", 9),
    (b"foo\nbar\n\r\njunk", 10),
    (b"foo\nbar\r\n\njunk", 10),
]


@pytest.mark.parametrize(("data", "expected"), LOCATE_END_OF_HEADERS_CASES)
def test_locate_end_of_headers(data: bytes, expected: int | None) -> None:
    assert locate_end_of_headers(data) == expected


# (the value of the first header line and what follows it, the value
# Chromium assembles for that line)
ASSEMBLE_RAW_HEADERS_CASES: list[tuple[bytes, bytes]] = [
    # "Foo: 1\r\nBar: 2\r\n\r\n": the next line is another header.
    (b"1\r\nBar: 2", b"1"),
    (b"1\nBar: 2", b"1"),
    # Valid line continuation (single SP).
    (b"1\n continuation\nBar: 2", b"1 continuation"),
    # Valid line continuation (single HT).
    (b"1\n\tcontinuation\nBar: 2", b"1 continuation"),
    # Valid line continuation (multiple SP).
    (b"1\n   continuation\nBar: 2", b"1 continuation"),
    # Valid line continuation (multiple HT).
    (b"1\n\t\t\tcontinuation\nBar: 2", b"1 continuation"),
    # Valid line continuation (mixed HT, SP).
    (b"1\n \t \t continuation\nBar: 2", b"1 continuation"),
    # Valid multi-line continuation
    (
        b"1\n continuation1\n\tcontinuation2\n  continuation3\nBar: 2",
        b"1 continuation1 continuation2 continuation3",
    ),
    # Continuation of quoted value.
    # This is different from what Firefox does, since it
    # will preserve the LWS.
    (b'"34534-d3\n    134q"\nBar: 2', b'"34534-d3 134q"'),
    # Valid multi-line continuation, full LWS lines
    # One SP per continued line = 3.
    (b"1\n         \n\t\t\t\t\n\t  continuation\nBar: 2", b"1   continuation"),
    # Valid multi-line continuation, all LWS
    # One SP per continued line = 3.
    (b"1\n         \n\t\t\t\t\n\t  \nBar: 2", b"1   "),
    # Valid line continuation (No value bytes in first line).
    # "Foo:\n value" becomes "Foo: value": the space is the one joining the
    # lines, and HttpResponseHeaders trims it off the value.
    (b"\n value\nBar: 2", b" value"),
    # Single terminated, with headers
    (b"2\n", b"2"),
    # Not terminated, with headers
    (b"2", b"2"),
    # Not a line continuation (VT)
    (b"1\n\x0bInvalidContinuation\nBar: 2", b"1"),
    # Not a line continuation (formfeed)
    (b"1\n\x0cInvalidContinuation\nBar: 2", b"1"),
    # Not a line continuation -- no value to continue.
    (b"1\ngarbage\n  not-a-continuation\nBar: 2", b"1"),
]


@pytest.mark.parametrize(("value", "expected"), ASSEMBLE_RAW_HEADERS_CASES)
def test_assemble_raw_headers(value: bytes, expected: bytes) -> None:
    assert assemble_raw_headers(value) == expected


# Chromium expects AssembleRawHeaders to drop these NULs once it has split the
# lines. On the network it never sees one: HttpResponseHeaders::TryToCreate
# refuses a response whose headers hold a NUL before they are assembled. So
# the package keeps the NUL and reports the refusal.
NUL_CASES: list[tuple[bytes, bytes]] = [
    # Embed NULLs in a header line. They should not be understood as
    # line separators.
    (b"1\x00Foo2: 3\nBar: 2", b"1\x00Foo2: 3"),
    # The embedded NUL at the start of the line (before "Blah:") should not be
    # interpreted as LWS (as that would mistake it for a header line
    # continuation).
    (b"1\n\x00Blah: 3\nBar: 2", b"1"),
]


@pytest.mark.parametrize(("value", "expected"), NUL_CASES)
def test_assemble_raw_headers_with_embedded_nulls(value: bytes, expected: bytes) -> None:
    assert line_value(value, None) == (expected, True)
