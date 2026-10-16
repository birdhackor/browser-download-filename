"""A response's headers, given as a whole.

Chromium's HttpResponseHeaders keeps every header line of a response in
order, and a header is looked up by name among them. The package does the
same with the headers it is given: whatever shape they come in, they are read
once into an ordered list of lines, and every lookup reads that list. A dict
would lose repeated lines and their order.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeAlias, cast

from ._bytes import header_bytes

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

#: Header names as the lines store them, ASCII-lowercased.
CONTENT_DISPOSITION = b"content-disposition"

HEADERS_SHAPE = "a mapping or an iterable of (name, value) pairs"


def _name_key(name: object) -> bytes:
    """The name a line is looked up by: the header name, ASCII-lowercased."""
    if isinstance(name, str):
        # A non-ASCII character keeps bytes of its own, so such a name
        # matches none of the ASCII names that are looked up.
        return name.encode("utf-8", "surrogatepass").lower()
    if isinstance(name, bytes):
        return name.lower()
    raise TypeError(f"a header name must be str or bytes, not {type(name).__name__}")


def _value_bytes(value: object, encoding: str | None) -> bytes:
    if isinstance(value, (str, bytes, bytearray, memoryview)):
        return header_bytes(value, encoding)
    raise TypeError(
        "a header value must be str or bytes, or a list or tuple of them, "
        f"not {type(value).__name__}"
    )


def _describe(item: object) -> str:
    if isinstance(item, (tuple, list)):
        return f"a {type(item).__name__} of length {len(item)}"
    return type(item).__name__


def header_lines(
    headers: object, encoding: str | None, *, argument: str, accepted: str
) -> list[tuple[bytes, bytes]]:
    """Every header line, in order, as (ASCII-lowercased name, value bytes).

    ``headers`` is walked once, so a generator works. Every str value is
    turned into bytes with ``encoding`` (see header_bytes), so both a shape
    that is wrong and a value that does not encode raise here, before any
    header is parsed. ``argument`` and ``accepted`` name the argument and what
    it takes in the TypeError messages.
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
    for pair in iterator:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise TypeError(
                f"each header in {argument} must be a (name, value) pair, not {_describe(pair)}"
            )
        name, value = pair
        key = _name_key(name)
        if isinstance(value, (list, tuple)):
            lines.extend((key, _value_bytes(item, encoding)) for item in value)
        else:
            lines.append((key, _value_bytes(value, encoding)))
    return lines


def header_values(lines: list[tuple[bytes, bytes]], name: bytes) -> list[bytes]:
    """The value of every line with this ASCII-lowercased name, in order."""
    return [value for key, value in lines if key == name]
