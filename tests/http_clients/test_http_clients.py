"""HTTP libraries, used as the documentation says, give the package what was sent.

These tests run only with --with-http-clients. A local server sends each
case's header lines byte for byte (see server.py). Each library fetches the
case, and the package gets what docs/en/usage.md tells users of that library
to pass: which headers, which URL and which headers_encoding. The result must
be what the package gives for the header lines exactly as they were sent.
Where the usage page says that another way of passing them gives another
name, the tests pin the difference. The other tests check what the
documentation says about the libraries themselves.

The requests here leave out proxies, from the environment or the system, so
that they reach the local server; nothing else differs from the calls in the
documentation.
"""

from __future__ import annotations

import asyncio
import http.client
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
@pytest.mark.parametrize("way", DOCUMENTED.values(), ids=DOCUMENTED.keys())
def test_the_documented_way_gives_the_name_of_the_lines_sent(
    way: Way, case: Case, server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsers = use_aiohttp_parser(monkeypatch, way.aiohttp_parser) if way.aiohttp_parser else []
    start, final = server.add(case.lines, case.name, redirect=case.redirect)
    passed = way.fetch(start)
    assert outcome(passed) == outcome(as_sent(case, final))
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
@pytest.mark.parametrize("way", DECODED.values(), ids=DECODED.keys())
def test_strs_with_the_codec_they_were_decoded_with_give_the_name_of_the_lines_sent(
    way: Way, case: Case, server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert way.aiohttp_parser
    parsers = use_aiohttp_parser(monkeypatch, way.aiohttp_parser)
    start, final = server.add(case.lines, case.name, redirect=case.redirect)
    assert outcome(way.fetch(start)) == outcome(as_sent(case, final))
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
@pytest.mark.parametrize("fetch", JOINED.values(), ids=JOINED.keys())
def test_joined_lines_give_another_name_only_after_an_open_quote(
    fetch: Callable[[str], Passed], case: Case, server: LocalServer
) -> None:
    start, final = server.add(case.lines, case.name, redirect=case.redirect)
    expected = outcome(as_sent(case, final))
    if case.id in JOINED_DIFFERENCES:
        assert JOINED_DIFFERENCES[case.id] != expected
        expected = JOINED_DIFFERENCES[case.id]
    assert outcome(fetch(start)) == expected


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
@pytest.mark.parametrize("fetch", GUESSED.values(), ids=GUESSED.keys())
def test_latin_1_strs_without_headers_encoding_give_another_name_for_legacy_bytes(
    fetch: Callable[[str], Passed], case: Case, server: LocalServer
) -> None:
    start, final = server.add(case.lines, case.name, redirect=case.redirect)
    expected = outcome(as_sent(case, final))
    if case.id in GUESS_DIFFERENCES:
        assert GUESS_DIFFERENCES[case.id] != expected
        expected = GUESS_DIFFERENCES[case.id]
    assert outcome(fetch(start)) == expected


# --- What the documentation says about the libraries ---------------------

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
