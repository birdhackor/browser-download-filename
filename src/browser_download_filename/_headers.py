"""A response's headers, given as a whole.

Chromium's HttpResponseHeaders keeps the lines of an HTTP/1 response that
HttpUtil::HeadersIterator reads as headers, in order, each under the name it
reads from the line, and a header is looked up by that name in any ASCII
case. The package does the same with the headers it is given: whatever shape
they come in, they are read once into an ordered list of lines, and every
lookup reads that list. A dict would lose repeated lines and their order.

Each (name, value) pair stands for one header line, the name before its colon
and the value after it. HeadersIterator skips a line whose name is empty,
starts with a space or a tab, or is not a token once the spaces and tabs at
its end are trimmed, and so does the package; the NUL check reads every name
as it was given, since Chromium looks for a NUL before it reads any line.

Ported in part from Chromium's net/http/http_response_headers.cc and
net/http/http_util.cc (BSD-3-Clause, see THIRD-PARTY-LICENSES).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple, Protocol, TypeAlias, cast

from ._bytes import header_bytes, is_token, trim_lws
from ._http import assemble_raw_headers, locate_end_of_headers

# The value of one header name: one line, or one line per item, as Scrapy
# gives them. The list types are spelled out because list is invariant.
HeaderValue: TypeAlias = (
    str | bytes | list[str] | list[bytes] | list[str | bytes] | tuple[str | bytes, ...]
)


class SupportsHeaderItems(Protocol):
    """Headers with an items() method, such as a dict or http.client.HTTPMessage."""

    def items(self) -> Iterable[tuple[str | bytes, HeaderValue]]: ...


#: A response's headers: an object with an items() method, which is used, or
#: an iterable of (name, value) pairs.
HeadersLike: TypeAlias = SupportsHeaderItems | Iterable[tuple[str | bytes, HeaderValue]]

#: Header names as the lines store them (see _lookup_name).
CONTENT_DISPOSITION = b"content-disposition"
CONTENT_TYPE = b"content-type"
X_CONTENT_TYPE_OPTIONS = b"x-content-type-options"

HEADERS_SHAPE = "a mapping or an iterable of (name, value) pairs"


def _name_bytes(name: object) -> bytes:
    """A header name as bytes, as it was given."""
    if isinstance(name, str):
        # A non-ASCII character keeps bytes of its own, none of them a token
        # byte, so such a name matches none of the names that are looked up.
        return name.encode("utf-8", "surrogatepass")
    if isinstance(name, bytes):
        return name
    raise TypeError(f"a header name must be str or bytes, not {type(name).__name__}")


def _lookup_name(name: bytes) -> bytes | None:
    """The name a header line is looked up by; None if HeadersIterator skips it.

    HttpUtil::HeadersIterator::GetNext skips a line whose name, the part
    before its colon, is empty or starts with a space or a tab. Otherwise it
    trims the name (TrimLWS, which removes only spaces and tabs, so here only
    those at the end) and skips the line if what is left is not a token.
    HttpResponseHeaders::FindHeader then compares names in any ASCII case.
    """
    if not name or name[0] in b" \t":
        return None
    trimmed = trim_lws(name)
    return trimmed.lower() if is_token(trimmed) else None


class LineValue(NamedTuple):
    """The value of a header line, as Chromium reads it."""

    #: The value: its first line, joined with the lines that continue it.
    value: bytes
    #: Whether the value holds a NUL before the end of the headers.
    has_nul: bool


def line_value(value: str | bytes | bytearray | memoryview, encoding: str | None) -> LineValue:
    """A header value, given as it was sent, read the way Chromium reads it.

    The value is turned into its bytes (header_bytes), cut where a blank line
    ends the headers (locate_end_of_headers), and its lines are joined as
    the network stack joins them (assemble_raw_headers). A NUL anywhere
    before the blank line makes HttpResponseHeaders::TryToCreate refuse the
    whole response (HasEmbeddedNulls), even in a line that is not part of
    the value, so has_nul looks at all of it.
    """
    data = header_bytes(value, encoding)
    end = locate_end_of_headers(data)
    if end is not None:
        data = data[:end]
    return LineValue(assemble_raw_headers(data), b"\0" in data)


def _line_value(value: object, encoding: str | None) -> LineValue:
    if isinstance(value, (str, bytes, bytearray, memoryview)):
        return line_value(value, encoding)
    raise TypeError(
        "a header value must be str or bytes, or a list or tuple of them, "
        f"not {type(value).__name__}"
    )


def _describe(item: object) -> str:
    if isinstance(item, (tuple, list)):
        return f"a {type(item).__name__} of length {len(item)}"
    return type(item).__name__


class HeaderLines(NamedTuple):
    """A response's header lines, as Chromium reads them."""

    #: Every line, in order, as (name, value), each name as it is looked up
    #: (see _lookup_name); a line whose name HeadersIterator skips is left out.
    lines: list[tuple[bytes, bytes]]
    #: Whether a name, as it was given, or a value holds a NUL, for which
    #: Chromium refuses the response (see line_value).
    has_nul: bool


def header_lines(
    headers: object, encoding: str | None, *, argument: str, accepted: str
) -> HeaderLines:
    """The header lines, in order, with each value read as in line_value.

    ``headers`` is walked once, so a generator works. Every str value is
    turned into bytes with ``encoding`` (see header_bytes), so both a shape
    that is wrong and a value that does not encode raise here, before any
    header is parsed. A line whose name HeadersIterator skips (see
    _lookup_name) is left out of the lines, but its value is read all the
    same, and a NUL in the value or in the name still counts. ``argument``
    and ``accepted`` name the argument and what it takes in the TypeError
    messages.
    """
    if isinstance(headers, (str, bytes, bytearray, memoryview)):
        raise TypeError(
            f"{argument} must be {accepted}, not {type(headers).__name__}; pass a "
            "Content-Disposition value as content_disposition=, or a URL as url="
        )
    items = getattr(headers, "items", None)
    pairs = items() if callable(items) else headers
    try:
        iterator = iter(cast("Iterable[object]", pairs))
    except TypeError:
        raise TypeError(f"{argument} must be {accepted}, not {type(headers).__name__}") from None
    lines: list[tuple[bytes, bytes]] = []
    has_nul = False
    for pair in iterator:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise TypeError(
                f"each header in {argument} must be a (name, value) pair, not {_describe(pair)}"
            )
        name, value = pair
        raw_name = _name_bytes(name)
        key = _lookup_name(raw_name)
        # A list or tuple holds one value for each line with this name.
        for item in value if isinstance(value, (list, tuple)) else (value,):
            read = _line_value(item, encoding)
            if key is not None:
                lines.append((key, read.value))
            has_nul = has_nul or read.has_nul or b"\0" in raw_name
    return HeaderLines(lines, has_nul)


def header_values(lines: list[tuple[bytes, bytes]], name: bytes) -> list[bytes]:
    """The value of every line looked up by this name (see _lookup_name), in order."""
    return [value for key, value in lines if key == name]
