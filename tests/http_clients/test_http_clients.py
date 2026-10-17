"""HTTP libraries, used as the documentation says, give the package what was sent.

These tests run only with --with-http-clients. A local server sends each
case's header lines byte for byte (see server.py). Each library fetches the
case, and the package gets what docs/en/usage.md tells users of that library
to pass: which headers, which URL and which headers_encoding. The result must
be what the package gives for the header lines exactly as they were sent.
Where the usage page says that a library reads some header lines otherwise
than Chromium, or refuses the response, and where it says that another way of
passing them gives another name, the tests pin the difference. The other
tests check what the documentation says about the libraries themselves.

The requests here leave out proxies, from the environment or the system, so
that they reach the local server; nothing else differs from the calls in the
documentation.
"""

from __future__ import annotations

import asyncio
import http.client
import importlib
import socket
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from browser_download_filename import (
    ContentDisposition,
    HeadersLike,
    parse_content_disposition,
    suggested_filename,
)

from .server import Lines, LocalServer, sent_lines

if TYPE_CHECKING:
    import aiohttp
    import requests

CD = b"Content-Disposition"
CT = b"Content-Type"
XCTO = b"X-Content-Type-Options"
A = b'attachment; filename="a.txt"'
B = b'attachment; filename="b.txt"'


@dataclass(frozen=True)
class Case:
    id: str
    lines: Lines
    #: The last segment of the URL's path.
    name: str = "report"
    #: Whether the URL redirects to the response.
    redirect: bool = False


CASES = (
    Case("repeated-content-disposition", ((CD, A), (CD, B))),
    Case("commas-in-one-line", ((CD, b"attachment; filename=a,b.txt"),)),
    # A quote left open runs to the end of its line.
    Case("open-quote", ((CD, b'attachment; filename="a'), (CD, b"attachment; filename=b"))),
    Case("open-quote-on-a-later-line", ((CD, A), (CD, b'attachment; filename="b'), (CD, A))),
    # Three values that differ, which the quote left open on the second line
    # joins into two that are the same.
    Case(
        "open-quote-joins-later-lines",
        ((CD, b'attachment; filename="a, b"'), (CD, b'attachment; filename="a'), (CD, b'b"')),
    ),
    Case("empty-first-line", ((CD, b""), (CD, A))),
    # windows-1252: 0xE9 is é and 0x85 is an ellipsis. As Latin-1, 0x85 is
    # U+0085, which str.splitlines takes for a line break.
    Case("windows-1252", ((CD, b'attachment; filename="caf\xe9.txt"'),)),
    Case("windows-1252-0x85", ((CD, b'attachment; filename="caf\xe9\x85.txt"'),)),
    Case("utf-8", ((CD, b'attachment; filename="caf\xc3\xa9.txt"'),)),
    # UTF-8 for a text whose characters all have Latin-1 bytes, which are
    # valid UTF-8 themselves.
    Case("utf-8-of-mojibake", ((CD, b'attachment; filename="caf\xc3\x83\xc2\xa9.txt"'),)),
    # A byte that is not UTF-8 in another header makes httpx decode every
    # header as Latin-1.
    Case(
        "legacy-byte-elsewhere",
        ((b"X-Note", b"caf\xe9"), (CD, b'attachment; filename="caf\xc3\xa9.txt"')),
    ),
    Case("content-type-lines", ((CT, b"text/plain"), (CT, b"application/pdf"))),
    Case("content-type-open-quote", ((CT, b'text/plain; charset="a'), (CT, b"application/pdf"))),
    Case("nosniff", ((XCTO, b"nosniff"),)),
    Case("nosniff-on-the-second-line", ((XCTO, b"bogus"), (XCTO, b"nosniff"))),
    Case("nosniff-after-an-open-quote", ((XCTO, b'"nosniff'), (XCTO, b"nosniff"))),
    Case(
        "names-in-other-cases",
        ((b"content-disposition", b"attachment"), (b"CONTENT-TYPE", b"application/pdf")),
    ),
    Case("url-escapes", (), name="r%C3%A9sum%C3%A9.pdf"),
    Case("url-legacy-escape", (), name="caf%E9.txt"),
    Case("redirect", ((CD, A),), redirect=True),
    # Without Content-Disposition, only the final URL gives the name.
    Case("redirect-without-content-disposition", (), name="report.pdf", redirect=True),
    # Line breaks in a value. A line that starts with a space or a tab
    # continues the header: Chromium joins it on with one space.
    Case("folded", ((CD, b"attachment;\r\n filename=wire.pdf"),)),
    Case("folded-with-lf", ((CD, b"attachment;\n filename=wire.pdf"),)),
    Case("folded-with-a-lone-cr", ((CD, b"attachment;\r filename=wire.pdf"),)),
    Case("folded-onto-an-empty-line", ((CD, b"\r\n attachment; filename=wire.pdf"),)),
    Case("folded-with-a-tab-in-quotes", ((CD, b'attachment; filename="wire\r\n\t file.pdf"'),)),
    Case("folded-after-a-space-in-quotes", ((CD, b'attachment; filename="a \r\n b.pdf"'),)),
    Case("folded-after-a-tab-in-quotes", ((CD, b'attachment; filename="a\t\r\n\tb.pdf"'),)),
    Case("folded-with-lf-after-a-space", ((CD, b'attachment; filename="a \n b.pdf"'),)),
    # Two CRs between the line feeds make no blank line, so the line folds.
    Case("folded-across-two-crs", ((CD, b"attachment;\n\r\r\n filename=wire.pdf"),)),
    # A blank line ends the headers.
    Case("blank-line", ((CD, b"attachment;\r\n\r\n filename=wire.pdf"),)),
    # A line that is no header line and does not continue one, which
    # Chromium skips, and a CR that ends a value before the line break.
    Case("text-after-a-line-break", ((b"X-Note", b"a\r\nnot a header"), (CD, A))),
    Case("lone-cr-at-the-end", ((CD, b"attachment\r"), (CT, b"application/pdf"))),
    # Control characters that HTTP does not allow, which Chromium reads.
    Case("vertical-tab", ((CD, b"attachment; filename=a\x0bb.txt"),)),
    Case("form-feed", ((CD, b"attachment; filename=a\x0cb.txt"),)),
    # A NUL anywhere in the headers makes Chromium refuse the response.
    Case("nul", ((CD, b"attachment; filename=wi\x00re.pdf"),)),
    Case("nul-in-another-header", ((b"X-Note", b"a\x00b"), (CD, A))),
    Case("nul-in-a-name", ((b"X-No\x00te", b"a"), (CD, A))),
    Case("nul-after-a-line-break", ((CD, b"attachment;\r\n\x00filename=wire.pdf"),)),
    # Header lines longer, or more of them, than some libraries take.
    Case("line-of-10000-bytes", ((CD, b'attachment; filename="' + b"a" * 10_000 + b'.txt"'),)),
    Case("line-of-70000-bytes", ((CD, b'attachment; filename="' + b"a" * 70_000 + b'.txt"'),)),
    # h11 refuses more than 100 KiB of headers only if they have not ended by
    # then, and httpx2 and httpx read up to 64 KiB at a time: these do not end
    # before 164 KiB.
    Case("lines-of-200000-bytes", (*((b"X-Note", b"a" * 40_000),) * 5, (CD, A))),
    Case("150-lines", (*((b"X-Note", b"a"),) * 149, (CD, A))),
)


class Passed(NamedTuple):
    """What a library's user passes the package for a response."""

    headers: HeadersLike
    url: str
    headers_encoding: str | None = None


def outcome(passed: Passed) -> tuple[ContentDisposition, str, str]:
    """What the package makes of a response.

    That is the parsed Content-Disposition, and the name without and with a
    fallback charset, which turns bytes in a legacy charset into a name.
    """
    headers, url, encoding = passed
    return (
        parse_content_disposition(headers, headers_encoding=encoding),
        suggested_filename(headers, url=url, headers_encoding=encoding, platform="posix"),
        suggested_filename(
            headers,
            url=url,
            headers_encoding=encoding,
            fallback_charset="windows-1252",
            platform="posix",
        ),
    )


def as_sent(case: Case, final_url: str) -> Passed:
    """The header lines exactly as the server sent them, as bytes."""
    return Passed(sent_lines(case.lines), final_url)


Outcome = tuple[ContentDisposition, str, str]


class HandedOver(NamedTuple):
    """The header lines a library gives in place of the ones sent."""

    lines: Lines


class Refused(NamedTuple):
    """The exception a library raises instead of giving the response."""

    module: str
    name: str

    def exception(self) -> type[BaseException]:
        exception = getattr(importlib.import_module(self.module), self.name)
        assert isinstance(exception, type)
        assert issubclass(exception, BaseException)
        return exception


AIOHTTP = ("aiohttp-c-parser", "aiohttp-python-parser")
HTTP_CLIENT = ("urllib.request", "requests")
# httpx2 and httpx read HTTP/1.1 with h11, and refuse what h11 cannot read.
H11_REFUSES = {
    "httpx2": Refused("httpx2", "RemoteProtocolError"),
    "httpx": Refused("httpx", "RemoteProtocolError"),
}
AIOHTTP_REFUSES = dict.fromkeys(AIOHTTP, Refused("aiohttp", "ClientResponseError"))
# urllib.request and requests read the headers with http.client.
HTTP_CLIENT_REFUSES_A_LONG_LINE = {
    "urllib.request": Refused("http.client", "LineTooLong"),
    "requests": Refused("requests", "ConnectionError"),
}
HTTP_CLIENT_REFUSES_MANY_LINES = {
    "urllib.request": Refused("http.client", "HTTPException"),
    "requests": Refused("requests", "ConnectionError"),
}

# Where a library reads the header lines otherwise than Chromium, or refuses
# the response: by case, what each library gives instead.
LIBRARY_DIFFERENCES: dict[str, dict[str, HandedOver | Refused]] = {
    "folded-with-a-lone-cr": {**H11_REFUSES, **AIOHTTP_REFUSES},
    # aiohttp keeps the spaces and tabs at the start of the next line.
    "folded-with-a-tab-in-quotes": dict.fromkeys(
        AIOHTTP, HandedOver(((CD, b'attachment; filename="wire\t file.pdf"'),))
    ),
    # urllib3, under requests, turns a fold after CR LF into one space,
    # together with the spaces and tabs before the line break.
    "folded-after-a-space-in-quotes": {
        "requests": HandedOver(((CD, b'attachment; filename="a b.pdf"'),))
    },
    "folded-after-a-tab-in-quotes": {
        "requests": HandedOver(((CD, b'attachment; filename="a b.pdf"'),))
    },
    # http.client's email parser and aiohttp's Python parser take a line of
    # CRs for a blank line, which ends the headers.
    "folded-across-two-crs": {
        **dict.fromkeys(
            (*HTTP_CLIENT, "aiohttp-python-parser"), HandedOver(((CD, b"attachment;"),))
        ),
        **H11_REFUSES,
        "aiohttp-c-parser": AIOHTTP_REFUSES["aiohttp-c-parser"],
    },
    # http.client's email parser ends the headers at a line that is no
    # header line, and at a line of a lone CR, which the CR at the end of a
    # value makes; the header lines after it are lost.
    "text-after-a-line-break": {
        **dict.fromkeys(HTTP_CLIENT, HandedOver(((b"X-Note", b"a"),))),
        **H11_REFUSES,
        **AIOHTTP_REFUSES,
    },
    "lone-cr-at-the-end": {
        **dict.fromkeys(HTTP_CLIENT, HandedOver(((CD, b"attachment"),))),
        **H11_REFUSES,
        "aiohttp-c-parser": AIOHTTP_REFUSES["aiohttp-c-parser"],
    },
    "vertical-tab": {**H11_REFUSES},
    "form-feed": {**H11_REFUSES},
    "nul": {**H11_REFUSES, **AIOHTTP_REFUSES},
    "nul-in-another-header": {**H11_REFUSES, **AIOHTTP_REFUSES},
    # A name with a NUL is no header line to the email parser either, and
    # neither is a line that starts with a NUL.
    "nul-in-a-name": {
        **dict.fromkeys(HTTP_CLIENT, HandedOver(())),
        **H11_REFUSES,
        **AIOHTTP_REFUSES,
    },
    "nul-after-a-line-break": {
        **dict.fromkeys(HTTP_CLIENT, HandedOver(((CD, b"attachment;"),))),
        **H11_REFUSES,
        **AIOHTTP_REFUSES,
    },
    "line-of-10000-bytes": {**AIOHTTP_REFUSES},
    "line-of-70000-bytes": {**HTTP_CLIENT_REFUSES_A_LONG_LINE, **AIOHTTP_REFUSES},
    "lines-of-200000-bytes": {**H11_REFUSES, **AIOHTTP_REFUSES},
    "150-lines": {**HTTP_CLIENT_REFUSES_MANY_LINES, **AIOHTTP_REFUSES},
}


def expected_outcome(library: str, case: Case, final_url: str) -> Outcome | Refused:
    """What the package makes of the response a library fetched for the case.

    That is what it makes of the lines sent, unless LIBRARY_DIFFERENCES says
    otherwise for the library, which must then change the result.
    """
    sent = outcome(as_sent(case, final_url))
    difference = LIBRARY_DIFFERENCES.get(case.id, {}).get(library)
    if difference is None:
        return sent
    if isinstance(difference, Refused):
        return difference
    handed_over = outcome(Passed(list(difference.lines), final_url))
    assert handed_over != sent, f"{library} gives the name of the lines sent"
    return handed_over


def check(fetch: Callable[[str], Passed], url: str, expected: Outcome | Refused) -> None:
    if isinstance(expected, Refused):
        with pytest.raises(expected.exception()):
            fetch(url)
    else:
        assert outcome(fetch(url)) == expected


def use_aiohttp_parser(monkeypatch: pytest.MonkeyPatch, kind: str) -> list[str]:
    """Make aiohttp read responses with its C parser or its Python parser.

    aiohttp uses the C parser where it can, and the Python one on PyPy or
    with AIOHTTP_NO_EXTENSIONS set. Its client makes a parser for each
    response by the name aiohttp.client_proto imported; the list returned
    records each parser made this way, so that a test can tell that the one
    asked for read the response.
    """
    import aiohttp.client_proto
    import aiohttp.http_parser

    if kind == "c":
        parser = getattr(aiohttp.http_parser, "HttpResponseParserC", None)
        if parser is None:
            pytest.fail(
                "aiohttp's C parser is not available: run on CPython with aiohttp's wheel, "
                "without AIOHTTP_NO_EXTENSIONS"
            )
    else:
        parser = aiohttp.http_parser.HttpResponseParserPy
    made: list[str] = []

    def make(*args: Any, **kwargs: Any) -> Any:
        made.append(kind)
        return parser(*args, **kwargs)

    monkeypatch.setattr(aiohttp.client_proto, "HttpResponseParser", make)
    return made


@contextmanager
def requests_get(url: str) -> Iterator[requests.Response]:
    import requests

    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, stream=True) as response:
            yield response


def urlopen(url: str) -> Any:
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url)


def aiohttp_get(url: str) -> aiohttp.ClientResponse:
    """The response, whose headers and URL stay readable once it is closed."""
    import aiohttp

    async def fetch() -> aiohttp.ClientResponse:
        async with aiohttp.ClientSession() as session, session.get(url) as response:
            return response

    return asyncio.run(fetch())


# --- The ways docs/en/usage.md shows -------------------------------------


def httpx2_raw(url: str) -> Passed:
    import httpx2

    with httpx2.stream("GET", url, follow_redirects=True, trust_env=False) as response:
        return Passed(response.headers.raw, str(response.url))


def httpx_raw(url: str) -> Passed:
    import httpx

    with httpx.stream("GET", url, follow_redirects=True, trust_env=False) as response:
        return Passed(response.headers.raw, str(response.url))


def requests_raw_headers(url: str) -> Passed:
    with requests_get(url) as response:
        return Passed(response.raw.headers, response.url, "latin-1")


def urllib_headers(url: str) -> Passed:
    with urlopen(url) as response:
        return Passed(response.headers, response.url, "latin-1")


def aiohttp_raw_headers(url: str) -> Passed:
    response = aiohttp_get(url)
    return Passed(response.raw_headers, str(response.url))


@dataclass(frozen=True)
class Way:
    fetch: Callable[[str], Passed]
    #: The aiohttp parser to read the response with: "c" or "python".
    aiohttp_parser: str | None = None


DOCUMENTED = {
    "httpx2": Way(httpx2_raw),
    "httpx": Way(httpx_raw),
    "requests": Way(requests_raw_headers),
    "urllib.request": Way(urllib_headers),
    "aiohttp-c-parser": Way(aiohttp_raw_headers, "c"),
    "aiohttp-python-parser": Way(aiohttp_raw_headers, "python"),
}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
@pytest.mark.parametrize("library", DOCUMENTED)
def test_the_documented_way_gives_the_name_of_the_lines_sent_unless_the_library_reads_them_otherwise(
    library: str, case: Case, server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    way = DOCUMENTED[library]
    parsers = use_aiohttp_parser(monkeypatch, way.aiohttp_parser) if way.aiohttp_parser else []
    start, final = server.add(case.lines, case.name, redirect=case.redirect)
    check(way.fetch, start, expected_outcome(library, case, final))
    if way.aiohttp_parser:
        assert parsers
        assert set(parsers) == {way.aiohttp_parser}


def aiohttp_headers(url: str) -> Passed:
    response = aiohttp_get(url)
    return Passed(response.headers, str(response.url), "utf-8")


# aiohttp's decoded headers, with the codec it decoded them with.
DECODED = {
    "aiohttp-c-parser": Way(aiohttp_headers, "c"),
    "aiohttp-python-parser": Way(aiohttp_headers, "python"),
}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
@pytest.mark.parametrize("library", DECODED)
def test_strs_with_the_codec_they_were_decoded_with_give_what_the_lines_give(
    library: str, case: Case, server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    way = DECODED[library]
    assert way.aiohttp_parser
    parsers = use_aiohttp_parser(monkeypatch, way.aiohttp_parser)
    start, final = server.add(case.lines, case.name, redirect=case.redirect)
    check(way.fetch, start, expected_outcome(library, case, final))
    assert parsers
    assert set(parsers) == {way.aiohttp_parser}


# --- Ways the usage page says can give another name ----------------------


def requests_headers(url: str) -> Passed:
    with requests_get(url) as response:
        return Passed(response.headers, response.url, "latin-1")


def httpx2_headers(url: str) -> Passed:
    import httpx2

    with httpx2.stream("GET", url, follow_redirects=True, trust_env=False) as response:
        return Passed(response.headers, str(response.url), response.headers.encoding)


def httpx_headers(url: str) -> Passed:
    import httpx

    with httpx.stream("GET", url, follow_redirects=True, trust_env=False) as response:
        return Passed(response.headers, str(response.url), response.headers.encoding)


# response.headers joins the lines of a header into one, with ", ".
JOINED = {"requests": requests_headers, "httpx2": httpx2_headers, "httpx": httpx_headers}
# Where that gives another result: a quote left open on a line takes in the
# next one. On the first line, that changes the name; on any line, it changes
# the values, and so blocks_download.
JOINED_DIFFERENCES = {
    "open-quote": (
        ContentDisposition("attachment", "a, attachment; filename=b"),
        "a, attachment; filename=b",
        "a, attachment; filename=b",
    ),
    "open-quote-joins-later-lines": (ContentDisposition("attachment", "a, b"), "a, b", "a, b"),
}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
@pytest.mark.parametrize("library", JOINED)
def test_joined_lines_give_what_the_documented_way_gives_except_after_an_open_quote(
    library: str, case: Case, server: LocalServer
) -> None:
    start, final = server.add(case.lines, case.name, redirect=case.redirect)
    expected = expected_outcome(library, case, final)
    if case.id in JOINED_DIFFERENCES:
        assert JOINED_DIFFERENCES[case.id] != expected
        expected = JOINED_DIFFERENCES[case.id]
    check(JOINED[library], start, expected)


# Strs that a library decoded as Latin-1, passed without headers_encoding.
GUESSED = {
    "requests": lambda url: requests_raw_headers(url)._replace(headers_encoding=None),
    "urllib.request": lambda url: urllib_headers(url)._replace(headers_encoding=None),
}
# Where the guess gives another name: bytes that are not UTF-8 are taken for
# text and encoded as UTF-8.
GUESS_DIFFERENCES = {
    "windows-1252": (ContentDisposition("attachment", "café.txt"), "café.txt", "café.txt"),
    "windows-1252-0x85": (
        ContentDisposition("attachment", "café\x85.txt"),
        "café_.txt",
        "café_.txt",
    ),
}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
@pytest.mark.parametrize("library", GUESSED)
def test_latin_1_strs_without_headers_encoding_give_what_the_documented_way_gives_but_for_legacy_bytes(
    library: str, case: Case, server: LocalServer
) -> None:
    start, final = server.add(case.lines, case.name, redirect=case.redirect)
    expected = expected_outcome(library, case, final)
    if case.id in GUESS_DIFFERENCES:
        assert GUESS_DIFFERENCES[case.id] != expected
        expected = GUESS_DIFFERENCES[case.id]
    check(GUESSED[library], start, expected)


# --- What the documentation says about the libraries ---------------------

# Values that hold another header line after a line break, or a blank line,
# which the package reads otherwise than Chromium: it does not read another
# header line out of a value, and it goes on to the next lines after a blank
# line. The libraries read such lines as Chromium does, or refuse them.
LINES_IN_A_VALUE = (
    Case(
        "another-header-after-lf",
        ((CD, b"attachment; filename=a.pdf\nContent-Disposition: attachment; filename=b.pdf"),),
    ),
    Case(
        "another-header-after-a-lone-cr",
        ((CD, b"attachment; filename=a.pdf\rContent-Disposition: attachment; filename=b.pdf"),),
    ),
    Case(
        "blank-line-before-another-header",
        ((CD, b"attachment\r\n\r\nfilename=a.pdf"), (CT, b"application/pdf")),
    ),
    # The line feed at the end and the line break after it make a blank line.
    Case("blank-line-at-the-end", ((CD, b"attachment\n"), (CT, b"application/pdf"))),
)
# The header lines Chromium reads in each.
AS_CHROMIUM_READS: dict[str, Lines] = {
    "another-header-after-lf": (
        (CD, b"attachment; filename=a.pdf"),
        (CD, b"attachment; filename=b.pdf"),
    ),
    "another-header-after-a-lone-cr": (
        (CD, b"attachment; filename=a.pdf"),
        (CD, b"attachment; filename=b.pdf"),
    ),
    "blank-line-before-another-header": ((CD, b"attachment"),),
    "blank-line-at-the-end": ((CD, b"attachment"),),
}
LINES_IN_A_VALUE_REFUSED = {"another-header-after-a-lone-cr": {**H11_REFUSES, **AIOHTTP_REFUSES}}


@pytest.mark.parametrize("case", LINES_IN_A_VALUE, ids=lambda case: case.id)
@pytest.mark.parametrize("library", DOCUMENTED)
def test_libraries_read_header_lines_in_a_value_as_chromium_does_or_refuse_them(
    library: str, case: Case, server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    way = DOCUMENTED[library]
    parsers = use_aiohttp_parser(monkeypatch, way.aiohttp_parser) if way.aiohttp_parser else []
    start, final = server.add(case.lines, case.name)
    chromium = outcome(Passed(list(AS_CHROMIUM_READS[case.id]), final))
    # Given the value as it was sent, the package reads it otherwise.
    assert chromium != outcome(as_sent(case, final))
    check(way.fetch, start, LINES_IN_A_VALUE_REFUSED.get(case.id, {}).get(library, chromium))
    if way.aiohttp_parser:
        assert set(parsers) == {way.aiohttp_parser}


CODEC_LINES: Lines = ((b"X-Utf-8", b"caf\xc3\xa9"), (b"X-Legacy", b"caf\xe9"))


def test_requests_urllib3_and_http_client_decode_headers_as_latin_1(server: LocalServer) -> None:
    import urllib3

    start, _ = server.add(CODEC_LINES, "x")
    with requests_get(start) as response:
        # requests' response.raw is the urllib3 response.
        assert isinstance(response.raw, urllib3.HTTPResponse)
        assert isinstance(response.raw.headers, urllib3.HTTPHeaderDict)
        for name, value in CODEC_LINES:
            assert response.headers[name.decode()] == value.decode("latin-1")
            assert response.raw.headers[name.decode()] == value.decode("latin-1")
    with urlopen(start) as response:
        # urllib.request's response.headers is http.client's.
        assert isinstance(response.headers, http.client.HTTPMessage)
        for name, value in CODEC_LINES:
            assert response.headers[name.decode()] == value.decode("latin-1")


@pytest.mark.parametrize("parser", ["c", "python"])
def test_aiohttp_decodes_headers_as_utf_8_with_surrogate_escapes(
    parser: str, server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsers = use_aiohttp_parser(monkeypatch, parser)
    start, _ = server.add(CODEC_LINES, "x")
    response = aiohttp_get(start)
    assert parsers == [parser]
    for name, value in CODEC_LINES:
        assert response.headers[name.decode()] == value.decode("utf-8", "surrogateescape")


@pytest.mark.parametrize("parser", ["c", "python"])
def test_httpx2_httpx_and_aiohttp_keep_each_header_line_in_bytes(
    parser: str, server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx
    import httpx2

    lines = ((CD, A), (CD, B))
    start, _ = server.add(lines, "x")
    with httpx2.stream("GET", start, trust_env=False) as response_2:
        assert response_2.headers.raw == sent_lines(lines)
    with httpx.stream("GET", start, trust_env=False) as response_x:
        assert response_x.headers.raw == sent_lines(lines)
    parsers = use_aiohttp_parser(monkeypatch, parser)
    response_a = aiohttp_get(start)
    assert parsers == [parser]
    assert list(response_a.raw_headers) == sent_lines(lines)


def test_requests_httpx2_and_httpx_join_the_lines_of_a_header_looked_up_by_name(
    server: LocalServer,
) -> None:
    import httpx
    import httpx2

    joined = (A + b", " + B).decode()
    start, _ = server.add(((CD, A), (CD, B)), "x")
    with requests_get(start) as response:
        assert response.headers["Content-Disposition"] == joined
        # The urllib3 response under it keeps both lines.
        assert response.raw.headers.getlist("Content-Disposition") == [A.decode(), B.decode()]
    with httpx2.stream("GET", start, trust_env=False) as response_2:
        assert response_2.headers["Content-Disposition"] == joined
    with httpx.stream("GET", start, trust_env=False) as response_x:
        assert response_x.headers["Content-Disposition"] == joined


def test_urllib_request_gives_the_first_line_of_a_header_looked_up_by_name(
    server: LocalServer,
) -> None:
    start, _ = server.add(((CD, A), (CD, B)), "x")
    with urlopen(start) as response:
        assert response.headers["Content-Disposition"] == A.decode()
        # response.headers keeps both lines.
        assert response.headers.get_all("Content-Disposition") == [A.decode(), B.decode()]


@pytest.mark.parametrize("parser", ["c", "python"])
def test_aiohttp_gives_the_first_line_of_a_header_looked_up_by_name(
    parser: str, server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsers = use_aiohttp_parser(monkeypatch, parser)
    start, _ = server.add(((CD, A), (CD, B)), "x")
    response = aiohttp_get(start)
    assert parsers == [parser]
    assert response.headers["Content-Disposition"] == A.decode()


# Folded lines: a space before the line break, a tab and a space after one,
# and a fold after a lone LF. Chromium joins them as "a  b", "wire file" and
# "c  d".
FOLDS: Lines = (
    (b"X-Space", b"a \r\n b"),
    (b"X-Tab", b"wire\r\n\t file"),
    (b"X-Lf", b"c \n d"),
)


def test_httpx2_and_httpx_join_a_folded_line_with_one_space_as_chromium_does(
    server: LocalServer,
) -> None:
    import httpx
    import httpx2

    joined = {b"X-Space": b"a  b", b"X-Tab": b"wire file", b"X-Lf": b"c  d"}
    start, _ = server.add(FOLDS, "x")
    with httpx2.stream("GET", start, trust_env=False) as response_2:
        assert {name: dict(response_2.headers.raw)[name] for name in joined} == joined
    with httpx.stream("GET", start, trust_env=False) as response_x:
        assert {name: dict(response_x.headers.raw)[name] for name in joined} == joined


def test_urllib3_under_requests_joins_a_cr_lf_fold_into_one_space_with_the_spaces_before_it(
    server: LocalServer,
) -> None:
    start, _ = server.add(FOLDS, "x")
    with requests_get(start) as response:
        headers = response.raw.headers
        # A fold after a lone LF comes as it was sent.
        assert [headers["X-Space"], headers["X-Tab"], headers["X-Lf"]] == [
            "a b",
            "wire file",
            "c \n d",
        ]


def test_http_client_under_urllib_request_gives_a_folded_line_as_it_was_sent(
    server: LocalServer,
) -> None:
    start, _ = server.add(FOLDS, "x")
    with urlopen(start) as response:
        assert [response.headers[name.decode()] for name, _ in FOLDS] == [
            value.decode() for _, value in FOLDS
        ]


@pytest.mark.parametrize("parser", ["c", "python"])
def test_aiohttp_joins_a_folded_line_keeping_the_spaces_and_tabs_that_start_it(
    parser: str, server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsers = use_aiohttp_parser(monkeypatch, parser)
    start, _ = server.add(FOLDS, "x")
    response = aiohttp_get(start)
    assert parsers == [parser]
    joined = {b"X-Space": b"a  b", b"X-Tab": b"wire\t file", b"X-Lf": b"c  d"}
    assert {name: dict(response.raw_headers)[name] for name in joined} == joined


def test_httpx2_and_httpx_follow_redirects_only_when_asked(server: LocalServer) -> None:
    import httpx
    import httpx2

    start, final = server.add((), "x", redirect=True)
    with httpx2.stream("GET", start, trust_env=False) as response_2:
        assert (response_2.status_code, str(response_2.url)) == (302, start)
    with httpx2.stream("GET", start, follow_redirects=True, trust_env=False) as response_2:
        assert (response_2.status_code, str(response_2.url)) == (200, final)
        assert isinstance(response_2.url, httpx2.URL)
    with httpx.stream("GET", start, trust_env=False) as response_x:
        assert (response_x.status_code, str(response_x.url)) == (302, start)
    with httpx.stream("GET", start, follow_redirects=True, trust_env=False) as response_x:
        assert (response_x.status_code, str(response_x.url)) == (200, final)
        assert isinstance(response_x.url, httpx.URL)


def test_aiohttp_gives_a_url_object(server: LocalServer) -> None:
    import yarl

    start, final = server.add((), "x", redirect=True)
    response = aiohttp_get(start)
    assert isinstance(response.url, yarl.URL)
    assert str(response.url) == final


NON_ASCII_HOST = "bücher.test"
ASCII_HOST = "xn--bcher-kva.test"


def test_response_url_has_the_host_in_ascii_except_in_urllib_request(
    server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx
    import httpx2

    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        """Find the test hosts at the local server."""
        if host in (NON_ASCII_HOST, ASCII_HOST, ASCII_HOST.encode()):
            host = "127.0.0.1"
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    local, _ = server.add((), "x")
    url = local.replace("127.0.0.1", NON_ASCII_HOST)
    in_ascii = local.replace("127.0.0.1", ASCII_HOST)
    with requests_get(url) as response:
        assert response.url == in_ascii
    with httpx2.stream("GET", url, trust_env=False) as response_2:
        assert str(response_2.url) == in_ascii
    with httpx.stream("GET", url, trust_env=False) as response_x:
        assert str(response_x.url) == in_ascii
    assert str(aiohttp_get(url).url) == in_ascii
    with urlopen(url) as response_u:
        assert response_u.url == url
