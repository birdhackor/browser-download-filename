"""Cases for the browser differential tests.

Each case is one HTTP response: its header lines, its body, the URL path it
is served under, and optionally the <a download> attribute of the link that
is clicked. Most cases send a Content-Type, X-Content-Type-Options: nosniff,
zero or more raw Content-Disposition lines and a binary body; the cases about
the MIME type list their header lines and body themselves. Together they
cover every branch of the parser and of the filename generation that a
browser can reach.

The cases come in two sets, and each case says which one it is in. In the
exact set, the headers and the URL decide the name, and Chromium must give
the package's name. The limited set (LimitedCase) holds responses whose body
Chromium sniffs for a MIME type, which the package never sees: each case
lists the name the package gives for its headers and URL, and the name
Chromium gives with its body.
"""

from __future__ import annotations

import random
import urllib.parse
from dataclasses import dataclass

from browser_download_filename._charset import _state_rows, lookup
from browser_download_filename._data import MULTI_BYTE_STATES, SINGLE_BYTE_TABLES

from ..test_chromium_content_disposition import (
    FILENAME_CASES,
    PARSE_RESULT_CASES,
    TC2231_CASES,
)

HeaderLines = tuple[tuple[bytes, bytes], ...]

BINARY_BODY = bytes(range(256)) * 4
HTML_BODY = b"<html><body>hello</body></html>" + b" " * 600
TEXT_BODY = b"hello, world\n" * 20
GIF_BODY = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
    b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)
PNG_BODY = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
_DEFAULT_CONTENT_TYPE = "application/octet-stream"
NOSNIFF = (b"X-Content-Type-Options", b"nosniff")
ATTACHMENT = (b"Content-Disposition", b"attachment")


@dataclass(frozen=True)
class BrowserCase:
    id: str
    #: Raw Content-Disposition values, one per header line.
    content_disposition: tuple[bytes, ...] = ()
    #: The URL path below /case/<n>/, query included.
    path: str = "file.bin"
    content_type: str = _DEFAULT_CONTENT_TYPE
    #: The link's download attribute; None leaves it out.
    download_attribute: str | None = None
    #: Every header line of the response, in order, as raw (name, value)
    #: pairs, in place of the ones built from content_type and
    #: content_disposition (see response_headers).
    header_lines: HeaderLines | None = None
    body: bytes = BINARY_BODY

    def __post_init__(self) -> None:
        if self.header_lines is not None and (
            self.content_disposition or self.content_type != _DEFAULT_CONTENT_TYPE
        ):
            raise ValueError(
                f"{self.id}: give header_lines, or content_type and content_disposition, not both"
            )

    @property
    def response_headers(self) -> HeaderLines:
        """The header lines the server sends, in order.

        Unless the case lists them, they are its Content-Type,
        X-Content-Type-Options: nosniff, and a Content-Disposition line for
        each of its values.
        """
        if self.header_lines is not None:
            return self.header_lines
        return (
            (b"Content-Type", self.content_type.encode("latin-1")),
            NOSNIFF,
            *((b"Content-Disposition", value) for value in self.content_disposition),
        )


@dataclass(frozen=True)
class LimitedCase(BrowserCase):
    """A response whose body Chromium sniffs for the MIME type."""

    #: The name the package gives, for any body with these headers and URL.
    fallback: str = ""
    #: The name Chromium gives with this body.
    chromium: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.fallback or not self.chromium:
            raise ValueError(f"{self.id}: list the package's name and Chromium's")


def _attachment(value: bytes, case_id: str) -> BrowserCase:
    return BrowserCase(case_id, (value,))


def _quote(data: bytes) -> str:
    return urllib.parse.quote_from_bytes(data, safe="")


def _unit_test_header_fits_one_line(header: bytes) -> bool:
    """Whether a header from Chromium's unit tests goes into the corpus.

    They are imported without review, and on the wire a CR, a LF or a NUL in
    one would take the case past what the unit test checks: a line break can
    start another header line, which the package does not read as one, and
    a NUL makes Chromium refuse the response. Cases with them are listed by
    hand instead (RAW_LINE_CASES).
    """
    return not any(byte in header for byte in b"\r\n\0")


def chromium_unit_test_cases() -> list[BrowserCase]:
    """Every header from Chromium's own tests that needs no referrer charset."""
    headers = [header for header, charset, _ in FILENAME_CASES if not charset]
    headers += [header for header, _, _ in TC2231_CASES]
    headers += [header for header, _ in PARSE_RESULT_CASES if header]
    unique = list(dict.fromkeys(filter(_unit_test_header_fits_one_line, headers)))
    return [
        BrowserCase(f"chromium-unittest-{index}", (header,)) for index, header in enumerate(unique)
    ]


PRACTICAL_CASES: list[BrowserCase] = [
    _attachment(
        b"attachment; filename=\"fallback.zip\"; filename*=UTF-8''%E4%B8%AD%E6%96%87.zip",
        "fallback-then-ext",
    ),
    _attachment(
        b"attachment; filename*=UTF-8''%E4%B8%AD%E6%96%87.zip; filename=\"fallback.zip\"",
        "ext-then-fallback",
    ),
    _attachment(b"attachment; filename*=UTF-8'zh-TW'%E4%B8%AD%E6%96%87.zip", "language-tag"),
    _attachment('attachment; filename="中文.zip"'.encode(), "raw-utf8-quoted"),
    _attachment("attachment; filename=中文.zip".encode(), "raw-utf8-token"),
    _attachment(b'attachment; filename="a;b;c.txt"', "quoted-semicolons"),
    _attachment(b'attachment; filename="a.txt";', "trailing-semicolon"),
    _attachment(b'attachment; filename="a.txt"; ', "trailing-semicolon-space"),
    _attachment(b'attachment; filename="a.txt";;', "trailing-semicolons"),
    _attachment(
        b"attachment; filename*=UTF-8''%E4%B8%AD%FF.zip; filename=\"good.zip\"",
        "broken-ext-then-good-filename",
    ),
    _attachment(
        b"attachment; filename*=x-unknown''abc.zip; filename=\"good.zip\"",
        "unknown-charset-then-good-filename",
    ),
    _attachment(b'attachment; filename="=?UTF-8?B?5Lit5paHLnppcA==?="', "rfc2047-b"),
    _attachment(b"attachment; filename==?UTF-8?Q?=E4=B8=AD=E6=96=87.zip?=", "rfc2047-q-token"),
    _attachment(
        b'attachment; filename="=?UTF-8?B?5Lit5paH?= =?UTF-8?B?LnppcA==?="', "rfc2047-two-words"
    ),
    _attachment(b'attachment; filename="=?UTF-8?B?QR==?="', "rfc2047-b-nonzero-pad-bits"),
    _attachment(b'attachment; filename="=?UTF-8?B?QUJD?=.txt"', "rfc2047-glued-suffix"),
    _attachment(b'attachment; filename="a =?"', "rfc2047-dangling"),
    _attachment(b'attachment; filename="=?a?="', "rfc2047-not-a-word"),
    _attachment(b'attachment; filename="="', "rfc2047-lone-equals"),
    _attachment(b'attachment; filename*0="foo."; filename*1="html"', "rfc2231-continuation"),
    _attachment(
        b"attachment; filename*0*=UTF-8''%E4%B8%AD; filename*1*=%E6%96%87.zip",
        "rfc2231-continuation-encoded",
    ),
    _attachment(b'attachment; filename="a<b>c:d|e?f*g.txt"', "windows-illegal-characters"),
    _attachment(b'attachment; filename="quote\\"inside.txt"', "escaped-quote"),
    _attachment(b'attachment; filename="../../etc/passwd"', "path-traversal"),
    _attachment(b'attachment; filename="C:\\\\Windows\\\\evil.exe"', "windows-path"),
    _attachment(b"inline", "inline-without-filename"),
    _attachment(b"\xff\xfe garbage ;;; ===", "garbage"),
    _attachment(b'attachment; size*=12; filename="ok.txt"', "broken-other-ext-param"),
    _attachment(b'attachment; foo; filename="after-valueless.txt"', "valueless-param-first"),
    _attachment(b'attachmentx; filename="x.txt"', "unknown-type"),
    _attachment(b'form-data; name="file"; filename="upload.txt"', "form-data"),
    _attachment(b'attachment; filename="a\tb.txt"', "tab-inside-quotes"),
    _attachment(b"attachment; filename*=ISO-8859-1''foo-%80%81%9F.html", "iso-8859-1-c1-range"),
    _attachment(b"attachment; filename*=iso-8859-1''%E9t%E9.txt", "iso-8859-1-ext"),
    _attachment(b'attachment; filename="100%25 done.txt"', "percent-escape"),
    _attachment(b'attachment; filename="50%.txt"', "stray-percent"),
    _attachment(b'attachment; filename="a+b.txt"', "plus-sign"),
    _attachment(b'attachment; filename=".htaccess"', "leading-dot"),
    _attachment(b'attachment; filename="..."', "only-dots"),
    _attachment(b'attachment; filename="name.txt "', "trailing-space"),
    _attachment('attachment; filename="name.txt\u00a0"'.encode(), "trailing-nbsp"),
    _attachment('attachment; filename="a\u200db.txt"'.encode(), "zero-width-joiner"),
    _attachment('attachment; filename="invoice\u202egpj.exe"'.encode(), "right-to-left-override"),
    _attachment('attachment; filename="🎉.txt"'.encode(), "emoji"),
    _attachment(b"attachment; filename*=UTF-8''a%CC%88.txt", "nfd-in-ext-value"),
    _attachment('attachment; filename="a\u0308.txt"'.encode(), "nfd-raw"),
    _attachment(b"attachment; filename*=UTF-8''%EF%BF%BE.txt", "noncharacter-in-ext-value"),
    _attachment(b'attachment; filename="\xef\xbf\xbe.txt"', "noncharacter-raw"),
    _attachment(b'attachment; filename="%EF%BF%BE.txt"', "noncharacter-percent"),
    _attachment(b'attachment; filename="' + b"a" * 300 + b'.txt"', "long-name"),
    _attachment(b'attachment; filename=""', "empty-quoted-filename"),
    _attachment(b"attachment; filename*=", "empty-ext-value"),
    _attachment(b"attachment; filename*=\"UTF-8''x.txt\"", "quoted-ext-value"),
    _attachment(b"ATTACHMENT; FILENAME*=UTF-8''X.TXT", "uppercase"),
    _attachment(b'attachment; filename = "spaced.txt"', "spaces-around-equals"),
    _attachment(b"attachment; filename='single.txt'", "single-quotes"),
    _attachment(b'attachment; filename="a\\\\b\\"c.txt"', "backslash-escapes"),
    _attachment(b"attachment; filename*=UTF-8''%EF%BB%BFbom.txt", "byte-order-mark"),
    _attachment(b'attachment; filename="caf\xe9.txt"', "raw-latin1"),
    _attachment(b'attachment; filename="caf\xe9 menu.txt"', "raw-latin1-two-words"),
    _attachment(b'attachment; filename="' + "中文.txt".encode("big5") + b'"', "raw-big5"),
    _attachment(
        ("attachment; filename*=Shift_JIS''" + _quote("日本語.txt".encode("cp932"))).encode(),
        "shift-jis-ext-value",
    ),
    _attachment(
        b"attachment; filename*=EUC-KR''" + _quote("한국어.txt".encode("cp949")).encode(),
        "euc-kr-ext-value",
    ),
    _attachment(
        b"attachment; filename*=GB2312''" + _quote("中文.txt".encode("gbk")).encode(),
        "gb2312-ext-value",
    ),
    _attachment(
        b"attachment; filename*=koi8-r''" + _quote("файл.txt".encode("koi8_r")).encode(),
        "koi8-r-ext-value",
    ),
    _attachment(
        b"attachment; filename*=ISO-2022-JP''" + _quote("日本語.txt".encode("iso2022_jp")).encode(),
        "iso-2022-jp-ext-value",
    ),
    _attachment(b"attachment; filename*=UTF''%41.txt", "charset-utf-without-8"),
    _attachment(b"attachment; filename*=utf\xff-8''%41.txt", "charset-with-non-ascii-byte"),
    _attachment(b"attachment; filename*=utf-8" + b"-" * 54 + b"''%41.txt", "charset-name-59-bytes"),
    _attachment(b"attachment; filename*=utf-8" + b"-" * 55 + b"''%41.txt", "charset-name-60-bytes"),
    _attachment(b"attachment; filename*=UTF-16LE''%41%00%2E%00%74%00%78%00%74%00", "utf-16le"),
    _attachment(b"attachment; filename*=UTF-16BE''%00%41%00%2E%00%74%00%78%00%74", "utf-16be"),
    _attachment(b"attachment; filename*=utf-16''%41%00%2E%00%74%00%78%00%74%00", "utf-16-is-le"),
    _attachment(b"attachment; filename*=utf-16le''%41%00%2E", "utf-16le-truncated"),
    _attachment(b'attachment; filename="=?utf-16le?B?QQAuAHQAeAB0AA==?="', "rfc2047-utf-16le"),
    _attachment(b'attachment; filename="=?windows-1253?Q?=AA=E1.txt?="', "rfc2047-unmapped-byte"),
    _attachment(b"attachment; filename*=windows-1253''%AA%E1.txt", "ext-value-unmapped-byte"),
    _attachment(b"attachment; filename=CON", "reserved-device-name"),
    _attachment(b'attachment; filename="x.lnk"', "shell-integrated-extension"),
    _attachment(b'attachment; filename="~tilde~"', "tildes"),
    _attachment(b'attachment; filename="config~1.txt"', "short-name-tilde"),
]

URL_CASES: list[BrowserCase] = [
    BrowserCase("url-plain", path="report.pdf"),
    BrowserCase("url-utf8-escaped", path="%E4%B8%AD%E6%96%87.zip"),
    BrowserCase("url-raw-unicode", path="中文.zip"),
    BrowserCase("url-latin1-escaped", path="caf%E9.txt"),
    BrowserCase("url-semicolon", path="file.txt;jsessionid=ABC"),
    BrowserCase("url-query", path="get.php?id=1"),
    BrowserCase("url-empty-query", path="get.php?"),
    BrowserCase("url-trailing-slash", path="dir/"),
    BrowserCase("url-dot-segments", path="a/b/../c.txt"),
    BrowserCase("url-dot-dot-at-end", path="a/b/.."),
    BrowserCase("url-dot-at-end", path="a/b/."),
    BrowserCase("url-escaped-dots", path="a/%2e%2E/c.txt"),
    BrowserCase("url-backslash", path="a\\b.txt"),
    BrowserCase("url-escaped-slash", path="a%2Fb.txt"),
    BrowserCase("url-escaped-backslash", path="a%5Cb.txt"),
    BrowserCase("url-dotfile", path=".hidden"),
    BrowserCase("url-escaped-control", path="a%01b.txt"),
    BrowserCase("url-escaped-space", path="my%20file.txt"),
    BrowserCase("url-plus", path="a+b.txt"),
    BrowserCase("url-fragment", path="f.txt#fragment"),
    BrowserCase("url-escaped-nul", path="a%00b.txt"),
    BrowserCase("url-long", path="x" * 200 + ".bin"),
    BrowserCase("url-reserved-name", path="CON"),
    BrowserCase("url-tildes", path="~file~"),
    BrowserCase("url-invalid-escape", path="100%zz.txt"),
    BrowserCase("url-query-with-path", path="dl?file=a/b.txt"),
    BrowserCase("url-quote", path='a"b.txt'),
    BrowserCase("url-escaped-noncharacter", path="%EF%BF%BE.txt"),
    BrowserCase("url-inline", (b"inline",), path="inline.pdf"),
]

MIME_CASES: list[BrowserCase] = [
    BrowserCase("mime-html", (b"attachment",), path="page", content_type="text/html"),
    BrowserCase("mime-pdf", (b"attachment",), path="report", content_type="application/pdf"),
    BrowserCase(
        "mime-query-replaces-extension",
        (b"attachment",),
        path="report.php?id=1",
        content_type="application/pdf",
    ),
    BrowserCase(
        "mime-query-JPG", (b"attachment",), path="photo.JPG?x=1", content_type="image/jpeg"
    ),
    BrowserCase(
        "mime-query-jpg", (b"attachment",), path="photo.jpg?x=1", content_type="image/jpeg"
    ),
    BrowserCase(
        "mime-query-double-extension",
        (b"attachment",),
        path="goat.tar.gz?x=1",
        content_type="application/gzip",
    ),
    BrowserCase("mime-default-name", (b"attachment",), path="dir/", content_type="text/html"),
    BrowserCase(
        "mime-not-for-content-disposition",
        (b'attachment; filename="noext"',),
        content_type="image/png",
    ),
    BrowserCase("mime-octet-stream", (b"attachment",), path="noext"),
    BrowserCase(
        "mime-parameters", (b"attachment",), path="notes", content_type="text/plain; charset=utf-8"
    ),
    BrowserCase("mime-uppercase", (b"attachment",), path="notes", content_type="TEXT/PLAIN"),
    BrowserCase("mime-svg-query", (b"attachment",), path="img?x=1", content_type="image/svg+xml"),
    BrowserCase(
        "mime-unknown", (b"attachment",), path="data", content_type="application/x-unknown-thing"
    ),
    BrowserCase(
        "mime-json-known-extension",
        (b"attachment",),
        path="data.json?x=1",
        content_type="application/json",
    ),
    BrowserCase(
        "mime-download-attribute",
        (b"attachment",),
        content_type="text/html",
        download_attribute="saved",
    ),
]


def _probe(case_id: str, *lines: tuple[bytes, bytes]) -> BrowserCase:
    """An attachment at /probe, a name without an extension, with these headers."""
    return BrowserCase(case_id, path="probe", header_lines=(*lines, ATTACHMENT))


# How the network stack reads the Content-Type lines. With nosniff, the MIME
# type is the one they give, or text/plain if they give none.
CONTENT_TYPE_CASES: list[BrowserCase] = [
    _probe(f"content-type-{case_id}", *((b"Content-Type", value) for value in values), NOSNIFF)
    for case_id, values in [
        ("plain", [b"text/html"]),
        ("uppercase", [b"TEXT/HTML"]),
        ("parameters", [b"text/html; charset=utf-8"]),
        ("comment", [b"text/html(comment)"]),
        ("absent", []),
        ("empty", [b""]),
        ("star-star", [b"*/*"]),
        ("star-star-parameter", [b"*/*; charset=utf-8"]),
        ("no-slash", [b"text"]),
        ("slash-at-end", [b"text/"]),
        ("slash-at-start", [b"/plain"]),
        ("space-before-slash", [b"text /html"]),
        ("space-after-slash", [b"text/ html"]),
        ("quoted-type", [b'"text/html"']),
        ("three-parts", [b"text/html/x"]),
        ("non-ascii", [b"t\xc3\xabxt/html"]),
        ("paren-first", [b"(text/html)"]),
        ("semicolon-first", [b";text/html"]),
        ("quoted-comma", [b'text/plain; charset="a,b"']),
        ("unquoted-comma", [b"text/plain; charset=a,b"]),
        ("comma-two", [b"text/plain, text/html"]),
        ("comma-then-invalid", [b"text/html, bogus"]),
        ("comma-then-star-star", [b"text/html, */*"]),
        ("comma-then-star-star-parameter", [b"text/html, */*;q=1"]),
        ("comma-trailing", [b"text/html,"]),
        ("comma-then-slash-at-end", [b"image/png, text/"]),
        ("comma-same-type", [b"text/html, TEXT/HTML"]),
        ("feed-rss", [b"application/rss+xml"]),
        ("feed-atom-parameters", [b"application/atom+xml; charset=utf-8"]),
        ("lines-two", [b"text/plain", b"text/html"]),
        ("lines-then-empty", [b"text/html", b""]),
        ("lines-then-invalid", [b"text/html", b"bogus"]),
        ("lines-then-star-star", [b"text/html", b"*/*"]),
        ("lines-open-quote", [b'text/plain; charset="a', b"text/html"]),
        ("lines-quote-spans", [b'text/plain; charset="a', b'x", text/html']),
        ("lines-open-quote-type", [b'"text/html', b"image/png"]),
        ("lines-comma-then-line", [b"image/png, text/css", b"text/html"]),
    ]
] + [
    _probe(
        "content-type-lines-name-case",
        (b"content-type", b"text/plain"),
        (b"CONTENT-TYPE", b"image/png"),
        NOSNIFF,
    ),
    # Types that Chrome does not sniff, without nosniff.
    _probe("content-type-html-without-nosniff", (b"Content-Type", b"text/html")),
    _probe("content-type-feed-without-nosniff", (b"Content-Type", b"application/rss+xml")),
]

# X-Content-Type-Options that stops the sniffing, so that no Content-Type
# means text/plain.
NOSNIFF_CASES: list[BrowserCase] = [
    _probe(f"nosniff-{case_id}", *((b"X-Content-Type-Options", value) for value in values))
    for case_id, values in [
        ("uppercase", [b"NOSNIFF"]),
        ("mixed-case", [b"NoSniff"]),
        ("spaces-around", [b"\t nosniff \t"]),
        ("first-value", [b"nosniff, bogus"]),
        ("trailing-comma", [b"nosniff,"]),
        ("first-line", [b"nosniff", b"bogus"]),
        ("repeated", [b"nosniff", b"nosniff"]),
    ]
]

DOWNLOAD_ATTRIBUTE_CASES: list[BrowserCase] = [
    BrowserCase("attr-named", download_attribute="named.txt"),
    BrowserCase(
        "attr-loses-to-content-disposition",
        (b'attachment; filename="cd.txt"',),
        download_attribute="attr.txt",
    ),
    BrowserCase("attr-beats-url", (b"attachment",), path="url.txt", download_attribute="attr.txt"),
    BrowserCase("attr-empty", download_attribute=""),
    BrowserCase("attr-path", download_attribute="a/b\\c.txt"),
    BrowserCase("attr-dots", download_attribute=".."),
    BrowserCase("attr-unicode", download_attribute="報告.pdf"),
    BrowserCase("attr-reserved-name", download_attribute="nul.txt"),
]

HEADER_LINE_CASES: list[BrowserCase] = [
    BrowserCase(
        "duplicate-identical", (b'attachment; filename="a.txt"', b'attachment; filename="a.txt"')
    ),
    BrowserCase(
        "duplicate-different", (b'attachment; filename="a.txt"', b'attachment; filename="b.txt"')
    ),
    BrowserCase(
        "duplicate-different-case",
        (b'attachment; filename="a.txt"', b'ATTACHMENT; FILENAME="A.TXT"'),
    ),
    BrowserCase("duplicate-empty-line", (b'attachment; filename="a.txt"', b"")),
    # Chromium refuses these responses, but a link with a download attribute
    # still starts a download. The page and the MIME type tell whether its
    # name used the Content-Type ("page.html") or not ("page").
    BrowserCase(
        "duplicate-different-download-attribute",
        (b'attachment; filename="a.txt"', b'attachment; filename="b.txt"'),
        path="page",
        content_type="text/html",
        download_attribute="saved",
    ),
    BrowserCase(
        "duplicate-different-empty-download-attribute",
        (b'attachment; filename="a.txt"', b'attachment; filename="b.txt"'),
        path="page",
        content_type="text/html",
        download_attribute="",
    ),
    BrowserCase("comma-unquoted", (b"attachment; filename=a,b.txt",)),
    BrowserCase("comma-quoted", (b'attachment; filename="a,b.txt"',)),
    BrowserCase("comma-trailing", (b'attachment; filename="a.txt",',)),
    BrowserCase("comma-after-type", (b"attachment,",)),
    BrowserCase("comma-identical-values", (b"attachment, attachment",)),
    BrowserCase("comma-in-ext-value", (b"attachment; filename*=UTF-8''a%2Cb.txt",)),
    BrowserCase("empty-header", (b"",)),
]

_OCTET_STREAM = (b"Content-Type", b"application/octet-stream")

# Line breaks, blank lines and NUL in the values the server sends. Chromium
# reads the header lines they make on the wire.
RAW_LINE_CASES: list[BrowserCase] = [
    # A line that starts with a space or a tab continues the header: it is
    # joined on with one space.
    _attachment(b"attachment;\r\n filename=wire.pdf", "folded"),
    _attachment(b"attachment;\r\n\t filename=wire.pdf", "folded-with-a-tab"),
    _attachment(b"attachment;\n filename=wire.pdf", "folded-with-lf"),
    _attachment(b"attachment;\r filename=wire.pdf", "folded-with-a-lone-cr"),
    _attachment(b"\r\n attachment; filename=wire.pdf", "folded-onto-an-empty-line"),
    _attachment(b'attachment; filename="wire\r\n\t file.pdf"', "folded-in-quotes"),
    _attachment(b'attachment; filename="wire\r\n   file.pdf"', "folded-in-quotes-after-spaces"),
    # The spaces and tabs before the line break stay.
    _attachment(b'attachment; filename="a \r\n b.pdf"', "folded-after-a-space-in-quotes"),
    _attachment(b'attachment; filename="a\t\r\n\tb.pdf"', "folded-after-a-tab-in-quotes"),
    _attachment(
        b'attachment; filename="a\r\n b \r\n c.pdf"', "folded-twice-after-a-space-in-quotes"
    ),
    # Each line of spaces and tabs adds one space.
    _attachment(b'attachment; filename="a\r\n   \r\n\t\r\n  b.pdf"', "folded-lines-of-spaces"),
    # Two CRs between the line feeds make no blank line.
    _attachment(b"attachment;\n\r\r\n filename=wire.pdf", "folded-across-two-crs"),
    # Any other line after a line break is another header line, which ends
    # the value: here one that Chromium skips, as it has no colon.
    _attachment(b"attachment;\r\nfilename=wire.pdf", "line-break-before-text"),
    _attachment(b"attachment;\r\n\x0bfilename=wire.pdf", "line-break-before-a-vertical-tab"),
    _attachment(b"attachment;\r\n\x0cfilename=wire.pdf", "line-break-before-a-form-feed"),
    _attachment(b"\r\nattachment; filename=wire.pdf", "line-break-at-the-start"),
    _attachment(b"attachment; filename=wire.pdf\rX-Note: 1", "lone-cr-before-another-header"),
    # The package does not read the second Content-Disposition. It is the same
    # as the first, so that it changes nothing for Chromium either: another
    # one would make Chromium refuse the response.
    _attachment(
        b"attachment; filename=a.pdf\rContent-Disposition: attachment; filename=a.pdf",
        "lone-cr-before-the-same-content-disposition",
    ),
    # Neither a vertical tab nor a form feed breaks a line.
    _attachment(b'attachment; filename="a\x0bb\x0cc.txt"', "vertical-tab-and-form-feed"),
    # A blank line ends the headers: the rest of the response is the body.
    _attachment(b"attachment;\r\n\r\n filename=wire.pdf", "blank-line"),
    _attachment(b"attachment;\n\n filename=wire.pdf", "blank-line-of-lfs"),
    _attachment(b"attachment;\n\r\n filename=wire.pdf", "blank-line-of-lf-cr-lf"),
    # With the line break after the value, the LF makes a blank line.
    _attachment(b'attachment; filename="a.txt"\n', "lf-at-the-end"),
    _attachment(b'attachment; filename="a.txt"\r\n\r\n\0', "nul-after-a-blank-line"),
    # A NUL anywhere in the headers makes Chromium refuse the response.
    _attachment(b"attachment; filename=wi\0re.pdf", "nul"),
    _attachment(b"attachment;\r\n\0filename=wire.pdf", "nul-after-a-line-break"),
    BrowserCase(
        "nul-download-attribute",
        (b"attachment; filename=wi\0re.pdf",),
        path="page",
        content_type="text/html",
        download_attribute="saved",
    ),
    BrowserCase(
        "nul-in-another-header",
        header_lines=(_OCTET_STREAM, NOSNIFF, (b"X-Note", b"a\0b"), ATTACHMENT),
    ),
    BrowserCase(
        "nul-in-another-header-download-attribute",
        header_lines=(_OCTET_STREAM, NOSNIFF, (b"X-Note", b"a\0b"), ATTACHMENT),
        download_attribute="saved",
    ),
    BrowserCase(
        "nul-in-a-name", header_lines=(_OCTET_STREAM, NOSNIFF, (b"X-No\0te", b"a"), ATTACHMENT)
    ),
    # Content-Type and X-Content-Type-Options are read the same way.
    _probe("content-type-folded", (b"Content-Type", b"\r\n text/html"), NOSNIFF),
    _probe(
        "content-type-line-break", (b"Content-Type", b"image/png\r\nX-Note: text/html"), NOSNIFF
    ),
    _probe("nosniff-folded", (b"X-Content-Type-Options", b"\r\n nosniff")),
]


def charset_label_cases() -> list[BrowserCase]:
    """filename*=<label>''ABC.txt for labels Chromium accepts or rejects."""
    labels = [
        "utf8", "UTF-8", "U-T-F-8", "utf_8", "UTF8 ", "unicode-1-1-utf-8", "x-user-defined",
        "cp932", "Shift_JIS", "sjis", "ms932", "windows-31j", "EUC-KR", "ks_c_5601-1987",
        "windows-949", "GB2312", "gbk", "x-gbk", "gb18030", "big5", "big5-hkscs", "cn-big5",
        "euc-jp", "iso-2022-jp", "koi8-r", "koi8-u", "windows-1251", "macintosh",
        "x-mac-cyrillic", "iso-8859-15", "iso-8859-8-i", "tis-620", "iso-8859-16", "ibm866",
        "cp866", "csisolatin1", "iso_8859-1:1987", "iso-8859-01", "ISO8859_1", "latin1", "l1",
        "ascii", "us-ascii", "ANSI_X3.4-1968", "iso-8859-11", "iso-8859-9", "latin5",
        "windows-874", "dos-874", "iso-2022-cn", "hz", "csiso2022kr", "replacement",
        "x-mac-roman", "mac", "ISO-8859-1", "iso-ir-100", "cp819", "ibm819", "cp1252", "x-cp1252",
        "windows-1252", "windows-1252-html", "iso88591", "iso8859-1", "ISO_8859-1", "8859-1",
        "88591", "bogus_charset", "ucs-2", "iso-10646-ucs-2", "unicode", "unicodefffe",
        "iso-8859-6-i", "iso-8859-6-e", "csiso88596i", "x-x-big5", "chinese", "iso-ir-58",
        "csgb2312", "gb_2312-80", "korean", "ksc5601", "ksc_5601", "utf-32", "UTF-7", "scsu",
        "bocu-1", "cesu-8", "x-sjis", "shift-jis", "csshiftjis", "euc-jp-html",
        "cseucpkdfmtjapanese", "x-euc-jp", "csiso2022jp", "iso-2022-kr", "iso-2022-cn-ext",
        "hz-gb-2312", "US_ASCII", "iso646-us", "646", "windows-1258", "x-mac-ukrainian",
        "iso-ir-58", "visual", "ISO-8859-8-E", "sun_eu_greek", "koi", "koi8_r", "koi8-ru",
    ]  # fmt: skip
    return [
        BrowserCase(
            f"charset-label-{label}", (f"attachment; filename*={label}''%41%42%43.txt".encode(),)
        )
        for label in dict.fromkeys(labels)
    ]


def single_byte_table_cases() -> list[BrowserCase]:
    """Every byte of every single-byte table, through both decoding paths."""
    cases = []
    for converter, table in sorted(SINGLE_BYTE_TABLES.items()):
        mapped = bytes(0x80 + index for index, char in enumerate(table) if char != "\ufffe")
        cases.append(
            BrowserCase(
                f"table-ext-value-{converter}",
                (f"attachment; filename*={converter}''x{_quote(mapped)}x.bin".encode(),),
            )
        )
        q_encoded = "".join(f"={byte:02X}" for byte in range(0x80, 0x100))
        cases.append(
            BrowserCase(
                f"table-rfc2047-{converter}",
                (f'attachment; filename="=?{converter}?Q?x{q_encoded}x.bin?="'.encode(),),
            )
        )
    return cases


def _well_formed_units(converter: str) -> list[bytes]:
    """Every non-ASCII character of up to three bytes that ICU decodes."""
    decoder = lookup(converter.encode())
    assert decoder is not None
    rows = _state_rows(converter)
    units: list[bytes] = []

    def walk(prefix: bytes, state: int) -> None:
        for byte, (following, action) in enumerate(rows[state]):
            sequence = prefix + bytes((byte,))
            if following >= 0:
                if len(sequence) < 3:
                    walk(sequence, following)
            elif action != "i" and sequence[0] >= 0x80:
                try:
                    decoder(sequence, "strict")
                except UnicodeDecodeError:
                    continue
                units.append(sequence)

    walk(b"", 0)
    return units


def multi_byte_cases(per_case: int = 500) -> list[BrowserCase]:
    """Every non-ASCII character of each legacy multi-byte charset."""
    cases = []
    for converter in sorted(MULTI_BYTE_STATES):
        units = _well_formed_units(converter)
        for index in range(0, len(units), per_case):
            data = b"".join(units[index : index + per_case])
            cases.append(
                BrowserCase(
                    f"multibyte-{converter}-{index // per_case}",
                    (f"attachment; filename*={converter}''x{_quote(data)}x.bin".encode(),),
                )
            )
    generator = random.Random(18030)
    four_byte = b"".join(
        bytes(
            (
                generator.randint(0x81, 0x84),
                generator.randint(0x30, 0x39),
                generator.randint(0x81, 0xFE),
                generator.randint(0x30, 0x39),
            )
        )
        for _ in range(200)
    )
    supplementary = b"".join(
        bytes(
            (
                generator.randint(0x90, 0xE3),
                generator.randint(0x30, 0x39),
                generator.randint(0x81, 0xFE),
                generator.randint(0x30, 0x39),
            )
        )
        for _ in range(200)
    )
    for name, data in (("bmp", four_byte), ("supplementary", supplementary)):
        cases.append(
            BrowserCase(
                f"multibyte-gb18030-four-byte-{name}",
                (f"attachment; filename*=gb18030''x{_quote(data)}x.bin".encode(),),
            )
        )
    kana_and_kanji = "".join(chr(code) for code in range(0x3041, 0x3094)) + "日本語の漢字テスト"
    cases.append(
        BrowserCase(
            "multibyte-iso-2022-jp",
            (
                f"attachment; filename*=iso-2022-jp''x{_quote(kana_and_kanji.encode('iso2022_jp'))}x.bin".encode(),
            ),
        )
    )
    # Characters Python's codecs decode but Chromium's ICU does not, and the
    # other way round.
    for case_id, label, data in (
        ("multibyte-shift_jis-ibm-extension-row", "shift_jis", b"\xf9\x40"),
        ("multibyte-shift_jis-lone-a0", "shift_jis", b"\xa0"),
        ("multibyte-big5-euro", "big5", b"\xa3\xe1"),
        ("multibyte-gbk-euro", "gbk", b"\x80"),
        ("multibyte-euc-jp-nec-row-13", "euc-jp", b"\xad\xe2"),
        ("multibyte-gb18030-a3a0", "gb18030", b"\xa3\xa0"),
        ("multibyte-big5-lead-without-trail", "big5", b"\xa4"),
        ("multibyte-big5-low-lead", "big5", b"\x81\x40"),
    ):
        cases.append(
            BrowserCase(case_id, (f"attachment; filename*={label}''x{_quote(data)}x.bin".encode(),))
        )
        cases.append(
            BrowserCase(
                case_id + "-rfc2047",
                (
                    f'attachment; filename="=?{label}?Q?x{"".join(f"={byte:02X}" for byte in data)}x.bin?="'.encode(),
                ),
            )
        )
    return cases


_FUZZ_PIECES: list[bytes] = [
    b"attachment", b"inline", b"form-data", b"filename", b"filename*", b"FileName", b"name",
    b"=", b"==", b";", b"; ", b" ", b"\t", b'"', b"'", b"''", b"\\", b"%", b"%41", b"%E4%B8%AD",
    b"%ZZ", b"UTF-8", b"utf-8''", b"iso-8859-1''", b"=?", b"?=", b"?Q?", b"?B?", b"=E9", b"_",
    b"a.txt", b"b.pdf", b"\xc3\xa9", b"\xe9", b"\xe4\xb8\xad", b"..", b"/", b"x", b"*", b"~",
    b"=?utf-8?Q?a?=", b"filename=", b"filename*=", b"; filename=", b"; filename*=UTF-8''",
]  # fmt: skip


def fuzz_cases(count: int = 150, seed: int = 20261016) -> list[BrowserCase]:
    """Random headers built from pieces that hit the parser's edge cases."""
    generator = random.Random(seed)
    cases = []
    for index in range(count):
        header = b"".join(generator.choice(_FUZZ_PIECES) for _ in range(generator.randint(1, 12)))
        if b"," not in header:
            cases.append(BrowserCase(f"fuzz-{index}", (header.strip(b" \t"),)))
    return cases


def _sniffed(
    group: str, lines: HeaderLines, fallback: str, chromium: dict[str, str], path: str = "probe"
) -> list[LimitedCase]:
    """One case for each body in ``chromium``, which maps it to Chromium's name.

    The package gives ``fallback`` for all of them: the same headers and URL.
    """
    bodies = {
        "html": HTML_BODY,
        "text": TEXT_BODY,
        "gif": GIF_BODY,
        "png": PNG_BODY,
        "binary": BINARY_BODY,
    }
    return [
        LimitedCase(
            f"sniffed-{group}-{body}",
            path=path,
            header_lines=lines,
            body=bodies[body],
            fallback=fallback,
            chromium=name,
        )
        for body, name in chromium.items()
    ]


def limited_cases() -> list[LimitedCase]:
    """Responses whose body Chromium sniffs for a MIME type, listed by hand."""
    content_type = b"Content-Type"
    options = b"X-Content-Type-Options"
    return [
        # No Content-Type, no X-Content-Type-Options.
        *_sniffed(
            "no-content-type",
            (ATTACHMENT,),
            "probe",
            {"html": "probe.html", "gif": "probe.gif", "binary": "probe"},
        ),
        # text/plain holds unless the body looks binary.
        *_sniffed(
            "text-plain",
            ((content_type, b"text/plain"), ATTACHMENT),
            "probe.txt",
            {"text": "probe.txt", "gif": "probe.gif"},
        ),
        # application/octet-stream is sniffed only for Chrome extensions and
        # Office documents.
        *_sniffed(
            "octet-stream",
            ((content_type, b"application/octet-stream"), ATTACHMENT),
            "probe",
            {"png": "probe"},
        ),
        # The sniffed type replaces the URL's extension only after a query.
        *_sniffed(
            "url-extension", (ATTACHMENT,), "probe.bin", {"gif": "probe.bin"}, path="probe.bin"
        ),
        *_sniffed(
            "url-extension-query",
            (ATTACHMENT,),
            "probe.bin",
            {"gif": "probe.gif"},
            path="probe.bin?x=1",
        ),
        # An empty filename names nothing, so the sniffed type still counts.
        *_sniffed(
            "empty-filename",
            ((b"Content-Disposition", b'attachment; filename=""'),),
            "probe",
            {"html": "probe.html", "gif": "probe.gif"},
        ),
        # X-Content-Type-Options whose first value is not nosniff.
        *_sniffed(
            "options-second-value",
            ((options, b"foo, nosniff"), ATTACHMENT),
            "probe",
            {"html": "probe.html", "binary": "probe"},
        ),
        *_sniffed(
            "options-empty-first-value",
            ((options, b", nosniff"), ATTACHMENT),
            "probe",
            {"html": "probe.html"},
        ),
        *_sniffed(
            "options-empty-first-line",
            ((options, b""), (options, b"nosniff"), ATTACHMENT),
            "probe",
            {"html": "probe.html"},
        ),
        *_sniffed(
            "options-second-line",
            ((options, b"foo"), (options, b"nosniff"), ATTACHMENT),
            "probe",
            {"html": "probe.html"},
        ),
        *_sniffed(
            "options-quoted", ((options, b'"nosniff"'), ATTACHMENT), "probe", {"html": "probe.html"}
        ),
    ]


def exact_cases() -> list[BrowserCase]:
    """Responses whose headers and URL decide the name."""
    return (
        chromium_unit_test_cases()
        + PRACTICAL_CASES
        + URL_CASES
        + MIME_CASES
        + CONTENT_TYPE_CASES
        + NOSNIFF_CASES
        + DOWNLOAD_ATTRIBUTE_CASES
        + HEADER_LINE_CASES
        + RAW_LINE_CASES
        + charset_label_cases()
        + single_byte_table_cases()
        + multi_byte_cases()
        + fuzz_cases()
    )


def all_cases() -> list[BrowserCase]:
    """Both sets, the limited one last."""
    cases: list[BrowserCase] = [*exact_cases(), *limited_cases()]
    ids = [case.id for case in cases]
    duplicates = {case_id for case_id in ids if ids.count(case_id) > 1}
    assert not duplicates, f"duplicate case ids: {sorted(duplicates)}"
    return cases
