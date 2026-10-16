"""The MIME type a download is named with, worked out from the headers."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from browser_download_filename import sanitize_filename, suggested_filename
from browser_download_filename._filename import _get_suggested_filename
from browser_download_filename._mime import (
    download_mime_type,
    get_mime_type,
    should_sniff_mime_type,
)
from browser_download_filename._url import parse_url

HTTPS = parse_url("https://example.com/probe")
PAGE = "https://example.com/page"
NOSNIFF = ("X-Content-Type-Options", "nosniff")


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        ([b"text/html"], b"text/html"),
        # ASCII-lowercased, and only the type counts.
        ([b"TEXT/HTML; charset=UTF-8"], b"text/html"),
        ([b" \ttext/html \t"], b"text/html"),
        # The type ends at a space, a tab, ';' or '(', which starts a comment.
        ([b"text/html(comment)"], b"text/html"),
        ([b"text/ html"], b"text/"),
        # The type must hold the first '/' of the value; nothing else is checked.
        ([b"text/"], b"text/"),
        ([b"/plain"], b"/plain"),
        ([b'"text/html"'], b'"text/html"'),
        ([b"text/html/x"], b"text/html/x"),
        ([b"text"], b""),
        ([b"text /html"], b""),
        ([b"(text/html)"], b""),
        ([b";text/html"], b""),
        # Bytes outside ASCII are kept; only ASCII letters are lowercased.
        ([b"T\xc3\x89XT/HTML"], b"t\xc3\x89xt/html"),
        # No line, or no value in the lines.
        ([], b""),
        ([b""], b""),
        ([b" , ,"], b""),
        # "*/*" itself is skipped; with parameters it is a type.
        ([b"*/*"], b""),
        ([b"*/*; charset=utf-8"], b"*/*"),
        # The last value with a type wins, ...
        ([b"text/plain, text/html"], b"text/html"),
        ([b"image/png, text/"], b"text/"),
        ([b"text/html, */*;q=1"], b"*/*"),
        ([b"text/html, TEXT/HTML"], b"text/html"),
        # ... and a value without one changes nothing.
        ([b"text/html, bogus"], b"text/html"),
        ([b"text/html, */*"], b"text/html"),
        ([b"text/html,"], b"text/html"),
        # Lines count as their values joined with ", ".
        ([b"text/plain", b"text/html"], b"text/html"),
        ([b"image/png, text/css", b"text/html"], b"text/html"),
        ([b"text/html", b""], b"text/html"),
        ([b"text/html", b"bogus"], b"text/html"),
        ([b"text/html", b"*/*"], b"text/html"),
        # A comma inside quotes does not split a value, ...
        ([b'text/plain; charset="a,b"'], b"text/plain"),
        ([b"text/plain; charset=a,b"], b"text/plain"),
        # ... and a quote left open on one line goes on into the next.
        ([b'text/plain; note="', b"text/html"], b"text/plain"),
        ([b'text/plain; charset="a', b'x", text/html'], b"text/html"),
        ([b'"text/html', b"image/png"], b'"text/html,'),
        # Each line is trimmed before the lines are joined.
        ([b'"text/html ', b"x"], b'"text/html,'),
    ],
)
def test_get_mime_type(lines: list[bytes], expected: bytes) -> None:
    assert get_mime_type(lines) == expected


@pytest.mark.parametrize(
    ("lines", "sniffs"),
    [
        ([], True),
        ([b"nosniff"], False),
        # In any ASCII case, with spaces and tabs around it.
        ([b"NOSNIFF"], False),
        ([b"NoSniff"], False),
        ([b" \tnosniff\t "], False),
        # Only the first value of the first line counts.
        ([b"nosniff, bogus"], False),
        ([b"nosniff,"], False),
        ([b"bogus, nosniff"], True),
        ([b", nosniff"], True),
        ([b"nosniff", b"bogus"], False),
        ([b"bogus", b"nosniff"], True),
        ([b"", b"nosniff"], True),
        ([b"nosniff", b"nosniff"], False),
        # Quotes are part of the value.
        ([b'"nosniff"'], True),
        ([b"nosniffs"], True),
        ([b"no-sniff"], True),
    ],
)
def test_x_content_type_options(lines: list[bytes], sniffs: bool) -> None:
    assert should_sniff_mime_type(HTTPS, lines, b"") is sniffs


# kSniffableTypes and kUnknownMimeTypes in Chromium's net/base/mime_sniffer.cc.
SNIFFED_TYPES = [
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
    b"",
    b"unknown/unknown",
    b"application/unknown",
    b"*/*",
    # A type without '/' is unknown too, though the network stack gives none.
    b"text",
]


@pytest.mark.parametrize("mime_type", SNIFFED_TYPES)
def test_sniffed_types(mime_type: bytes) -> None:
    assert should_sniff_mime_type(HTTPS, [], mime_type)
    assert should_sniff_mime_type(None, [], mime_type)
    assert not should_sniff_mime_type(HTTPS, [b"nosniff"], mime_type)


@pytest.mark.parametrize(
    "mime_type",
    [
        b"text/html",
        b"image/gif",
        b"application/pdf",
        b"application/json",
        b"application/rss+xml",
        b"application/x-unknown",
        b"text/",
        b"/plain",
        b'"text/plain"',
    ],
)
def test_other_types_are_not_sniffed(mime_type: bytes) -> None:
    assert not should_sniff_mime_type(HTTPS, [], mime_type)


@pytest.mark.parametrize(
    ("url", "sniffs"),
    [
        (None, True),
        ("http://example.com/a", True),
        ("HTTPS://example.com/a", True),
        ("file:///tmp/a", True),
        ("filesystem:https://example.com/temporary/a", True),
        # A URL that is not valid counts as none.
        ("https://exa mple.com/a", True),
        ("ftp://example.com/a", False),
        ("ws://example.com/a", False),
        ("data:text/plain,a", False),
        ("blob:https://example.com/0", False),
        ("about:blank", False),
    ],
)
def test_sniffing_schemes(url: str | None, sniffs: bool) -> None:
    assert should_sniff_mime_type(parse_url(url), [], b"") is sniffs


@pytest.mark.parametrize(
    ("content_type", "options", "expected"),
    [
        # Not sniffed: no type and the feed types become text/plain.
        ([], [b"nosniff"], "text/plain"),
        ([b""], [b"nosniff"], "text/plain"),
        ([b"*/*"], [b"nosniff"], "text/plain"),
        ([b"bogus"], [b"nosniff"], "text/plain"),
        ([b"application/rss+xml"], [], "text/plain"),
        ([b"Application/Atom+XML; charset=utf-8"], [], "text/plain"),
        ([b"application/rss+xml"], [b"nosniff"], "text/plain"),
        ([b"text/html"], [], "text/html"),
        ([b"*/*; q=1"], [b"nosniff"], "*/*"),
        # Sniffed: the declared type, even an empty one.
        ([], [], ""),
        ([b""], [], ""),
        ([b"text/plain"], [], "text/plain"),
        ([b"application/octet-stream"], [], "application/octet-stream"),
        ([b"*/*; q=1"], [], "*/*"),
        # Each byte becomes the character with its value.
        ([b"t\xc3\xabxt/html"], [], "tÃ«xt/html"),
    ],
)
def test_download_mime_type(content_type: list[bytes], options: list[bytes], expected: str) -> None:
    assert download_mime_type(content_type, options, HTTPS) == expected


@pytest.mark.parametrize(
    ("mime_type", "expected"),
    [
        ("text/html", "page.html"),
        # net::GetSuggestedFilename looks the type up exactly; the network
        # stack is what lowercases it and drops the parameters.
        ("TEXT/HTML", "page"),
        ("text/html; charset=utf-8", "page"),
        (" text/html", "page"),
    ],
)
def test_get_suggested_filename_takes_the_type_as_it_is(mime_type: str, expected: str) -> None:
    name = _get_suggested_filename(parse_url(PAGE), b"", None, "", mime_type, "", windows=False)
    assert name == expected


def test_other_schemes_are_never_sniffed() -> None:
    assert download_mime_type([], [], parse_url("ftp://example.com/a")) == "text/plain"
    assert download_mime_type([b"text/plain"], [], parse_url("data:,a")) == "text/plain"


def test_content_type_alone() -> None:
    assert suggested_filename(url=PAGE, content_type="text/html") == "page.html"
    assert suggested_filename(url=PAGE, content_type=b"TEXT/HTML; charset=utf-8") == "page.html"
    assert suggested_filename(url=PAGE, content_type="text/html(comment)") == "page.html"
    # A feed type, which Chrome does not sniff, is saved as text.
    assert suggested_filename(url=PAGE, content_type="application/rss+xml") == "page.txt"
    # An empty Content-Type: without nosniff Chrome sniffs, so no type is known.
    assert suggested_filename(url=PAGE, content_type="") == "page"


def test_headers_give_the_mime_type() -> None:
    headers = [("Content-Type", "text/plain"), ("Content-Type", "text/html")]
    assert suggested_filename(headers, url=PAGE) == "page.html"
    assert suggested_filename({"Content-Type": "text/html, bogus"}, url=PAGE) == "page.html"
    assert suggested_filename([(b"content-type", b"IMAGE/PNG")], url=PAGE) == "page.png"
    # No Content-Type, which nosniff turns into text/plain.
    assert suggested_filename([NOSNIFF], url=PAGE) == "page.txt"
    assert suggested_filename([], url=PAGE) == "page"


def test_content_type_replaces_every_content_type_line() -> None:
    headers = [("Content-Type", "image/png"), ("Content-Type", "text/html"), NOSNIFF]
    assert suggested_filename(headers, url=PAGE) == "page.html"
    assert suggested_filename(headers, url=PAGE, content_type=None) == "page.html"
    assert suggested_filename(headers, url=PAGE, content_type="application/pdf") == "page.pdf"
    # "bogus" has no type: next to either line it would leave a type there.
    assert suggested_filename(headers, url=PAGE, content_type="bogus") == "page.txt"


def test_empty_content_type_is_not_a_missing_one() -> None:
    headers = [("Content-Type", "application/pdf"), NOSNIFF]
    assert suggested_filename(headers, url=PAGE, content_type=None) == "page.pdf"
    # An empty Content-Type, which nosniff turns into text/plain.
    assert suggested_filename(headers, url=PAGE, content_type="") == "page.txt"
    assert suggested_filename(headers, url=PAGE, content_type=b"") == "page.txt"


def test_x_content_type_options_comes_only_from_the_headers() -> None:
    assert suggested_filename([NOSNIFF], url=PAGE, content_type="") == "page.txt"
    assert suggested_filename(url=PAGE, content_type="") == "page"


def test_types_are_not_checked_for_tokens() -> None:
    headers = [("Content-Type", "text/"), NOSNIFF, ("Content-Disposition", "attachment")]
    # "text/" is a type with no extension. Taken as no type, it would have
    # become text/plain.
    assert suggested_filename(headers, url="https://example.com/probe") == "probe"


def test_no_mime_type_without_headers_or_content_type() -> None:
    # A URL whose scheme Chrome never sniffs: an empty type there would be
    # text/plain, and the query would let it replace the extension.
    assert suggested_filename(url="ftp://example.com/get.php?id=1") == "get.php"
    assert suggested_filename([], url="ftp://example.com/get.php?id=1") == "get.txt"
    assert suggested_filename(url="https://example.com/report") == "report"
    assert sanitize_filename("report") == "report"


def test_headers_are_read_once() -> None:
    # The name depends on both lines: an empty Content-Type is text/plain
    # only with nosniff.
    def pairs() -> Iterator[tuple[str, str]]:
        yield ("Content-Type", "")
        yield NOSNIFF

    assert suggested_filename(pairs(), url=PAGE) == "page.txt"

    class OneShotItems:
        """items() hands out the same generator every time."""

        def __init__(self) -> None:
            self._pairs = pairs()

        def items(self) -> Iterator[tuple[str, str]]:
            return self._pairs

    assert suggested_filename(OneShotItems(), url=PAGE) == "page.txt"
