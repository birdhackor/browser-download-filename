"""The MIME type a download is named with, worked out as Chromium does.

When Chrome downloads a response over the network, net::GetSuggestedFilename
gets the MIME type that Chromium's network service leaves in the response
head. The network stack reads it from the Content-Type lines; the URL loader
then either sniffs the body for another type, when ShouldSniffMimeType says
so, or turns a missing type and the feed types into text/plain. The package
has no body: where Chrome would sniff it, the declared type is kept.

Ported from Chromium's net/http/http_response_headers.cc,
net/http/http_util.cc, net/base/mime_util.cc, net/base/mime_sniffer.cc and
services/network/url_loader.cc (BSD-3-Clause, see THIRD-PARTY-LICENSES).
Function names follow the Chromium ones.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ._bytes import trim_lws
from ._http import comma_separated_values, first_comma_separated_value
from ._url import ParsedURL

# net::ParseMimeType ends the type at the first LWS, ';' or '(', which starts
# a comment as in "text/html(comment)".
_TYPE_END = re.compile(rb"[ \t;(]")

# kSniffableTypes in ShouldSniffMimeType (net/base/mime_sniffer.cc).
_SNIFFABLE_TYPES = frozenset(
    {
        b"text/plain",
        b"application/octet-stream",
        b"text/xml",
        b"application/xml",
        b"application/msword",
        b"application/vnd.ms-excel",
        b"application/vnd.ms-powerpoint",
        b"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        b"application/vnd.openxmlformats-officedocument.presentationml.presentation",
        b"application/vnd.ms-excel.sheet.macroenabled.12",
        b"application/vnd.ms-word.document.macroenabled.12",
        b"application/vnd.ms-powerpoint.presentation.macroenabled.12",
        b"application/mspowerpoint",
        b"application/msexcel",
        b"application/vnd.ms-word",
        b"application/vnd.ms-word.document.12",
        b"application/vnd.msword",
    }
)
# kUnknownMimeTypes in IsUnknownMimeType (net/base/mime_sniffer.cc).
_UNKNOWN_MIME_TYPES = frozenset({b"", b"unknown/unknown", b"application/unknown", b"*/*"})
# The schemes ShouldSniffMimeType sniffs, leaving out Android's content:.
_SNIFFABLE_SCHEMES = frozenset({"http", "https", "file", "filesystem"})
# The feed types that URLLoader::StartReading (services/network/url_loader.cc)
# treats as text/plain.
_FEED_TYPES = frozenset({b"application/rss+xml", b"application/atom+xml"})


def parse_mime_type(value: bytes) -> bytes | None:
    """net::ParseMimeType, for the type only; None if there is none.

    The type runs from the first byte that is not LWS to the first LWS, ';'
    or '(' after it, and the first '/' of the value must be inside it. It is
    not checked for token characters: "text/", "/plain" and '"text/html"'
    are types.
    """
    start = len(value) - len(value.lstrip(b" \t"))
    match = _TYPE_END.search(value, start)
    end = len(value) if match is None else match.start()
    slash = value.find(b"/")
    if slash < 0 or slash > end:
        return None
    return value[start:end]


def parse_content_type(value: bytes, mime_type: bytes) -> bytes:
    """HttpUtil::ParseContentType, for the MIME type: the type after ``value``.

    A value with no type, or that is exactly "*/*", leaves ``mime_type`` as
    it is; any other value replaces it with its own type, ASCII-lowercased.
    """
    parsed = parse_mime_type(value)
    if parsed is None or value == b"*/*":
        return mime_type
    return parsed.lower()


def get_mime_type(lines: Sequence[bytes]) -> bytes:
    """HttpResponseHeaders::GetMimeTypeAndCharset, for the MIME type.

    ``lines`` are the values of the Content-Type lines, in order.
    GetNormalizedHeader trims each one and joins them with ", ", so a quote
    left open on one line goes on into the next. The non-empty values of the
    result, split on commas outside quotes, go through ParseContentType in
    order, so the last one with a type wins. Empty when there is no line, or
    no value with a type.
    """
    joined = b", ".join(trim_lws(line) for line in lines)
    mime_type = b""
    for value in comma_separated_values(joined, ignore_empty=True):
        mime_type = parse_content_type(value, mime_type)
    return mime_type


def is_unknown_mime_type(mime_type: bytes) -> bool:
    """IsUnknownMimeType in net/base/mime_sniffer.cc."""
    return mime_type in _UNKNOWN_MIME_TYPES or b"/" not in mime_type


def should_sniff_mime_type(
    url: ParsedURL | None, options_lines: Sequence[bytes], mime_type: bytes
) -> bool:
    """net::ShouldSniffMimeType: whether Chrome sniffs the body for a type.

    ``url`` is None when there is no URL; a URL that is not valid counts as
    none, since Chrome downloads nothing from one. ``options_lines`` are the
    values of the X-Content-Type-Options lines. Only the first value of the
    first line counts (HttpResponseHeaders::EnumerateHeader), and it stops
    the sniffing if it is "nosniff" in any ASCII case.
    """
    if url is not None and url.scheme not in _SNIFFABLE_SCHEMES:
        return False
    if options_lines and first_comma_separated_value(options_lines[0]).lower() == b"nosniff":
        return False
    return mime_type in _SNIFFABLE_TYPES or is_unknown_mime_type(mime_type)


def download_mime_type(
    content_type_lines: Sequence[bytes], options_lines: Sequence[bytes], url: ParsedURL | None
) -> str:
    """The MIME type net::GetSuggestedFilename gets for a download.

    That is the type services/network's URLLoader leaves in the response
    head: the one the Content-Type lines declare (get_mime_type), or, when
    the body is not sniffed, text/plain in place of an empty type
    (URLLoader::OnResponseStarted) and of a feed type
    (URLLoader::StartReading). Where Chrome sniffs the body, which the
    package does not have, the declared type is returned as it is, even if
    it is empty. Each byte becomes one character (Latin-1), so a byte
    outside ASCII matches no MIME type that has an extension.
    """
    mime_type = get_mime_type(content_type_lines)
    if not should_sniff_mime_type(url, options_lines, mime_type) and (
        not mime_type or mime_type in _FEED_TYPES
    ):
        mime_type = b"text/plain"
    return mime_type.decode("latin-1")
