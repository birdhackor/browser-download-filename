"""Differential tests: this package against real browsers.

In the exact set, whose names the headers and the URL decide, Chromium must
agree with the package on every case, since the package ports its rules. In
the limited set, Chromium sniffs the body for a MIME type: there it must give
the name the corpus lists for the body, while the package gives the name the
corpus lists for the headers and URL. Firefox and WebKit are only compared
with Chrome's names and reported; where they differ, the test is marked as an
expected failure, and the report lists the case.
"""

from __future__ import annotations

import socket

import pytest

from browser_download_filename import parse_content_disposition, suggested_filename

from .conftest import BrowserSession, Report, _Server
from .corpus import BrowserCase, LimitedCase, all_cases

CASES = all_cases()
EXACT = [case for case in CASES if not isinstance(case, LimitedCase)]
LIMITED = [case for case in CASES if isinstance(case, LimitedCase)]


def chromium_expectation(case: BrowserCase, url: str) -> str | None:
    """What Chromium reports, per this package's model of it."""
    headers = case.response_headers
    if parse_content_disposition(headers).blocks_download:
        # The network stack refuses the response, for Content-Disposition
        # values that differ (ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION)
        # or for a NUL in the headers (ERR_INVALID_HTTP_RESPONSE). A plain
        # link downloads nothing; a link with a download attribute starts a
        # download that fails, named as if the response had neither
        # Content-Disposition nor a Content-Type.
        if case.download_attribute is None:
            return None
        return suggested_filename(
            url=url, download_attribute=case.download_attribute, platform="posix"
        )
    return suggested_filename(
        headers,
        url=url,
        download_attribute=case.download_attribute,
        # The package models Chrome on Linux, where CI runs this comparison.
        platform="posix",
    )


def _record(
    report: Report,
    session: BrowserSession,
    case: BrowserCase,
    *,
    set_name: str,
    ours: str | None,
    expected: str | None,
    result: str | None,
) -> None:
    report.rows.append(
        {
            "engine": session.name,
            "version": session.version,
            "set": set_name,
            "case": case.id,
            "headers": [
                [name.decode("latin-1"), value.decode("latin-1")]
                for name, value in case.response_headers
            ],
            "path": case.path,
            "download_attribute": case.download_attribute,
            "ours": ours,
            "expected": expected,
            "result": result,
        }
    )


@pytest.mark.parametrize("case", EXACT, ids=[case.id for case in EXACT])
def test_download_name(case: BrowserCase, browser_session: BrowserSession, report: Report) -> None:
    _, url = browser_session.url_for(case)
    ours = chromium_expectation(case, url)
    timeout_ms = 2_000 if ours is None else 15_000
    result = browser_session.download(url, case, timeout_ms)
    _record(
        report, browser_session, case, set_name="exact", ours=ours, expected=ours, result=result
    )
    if browser_session.name == "chromium":
        assert result == ours
    elif result != ours:
        pytest.xfail(f"{browser_session.name} gives {result!r}, Chromium rules give {ours!r}")


@pytest.mark.parametrize("case", LIMITED, ids=[case.id for case in LIMITED])
def test_sniffed_download_name(
    case: LimitedCase, browser_session: BrowserSession, report: Report
) -> None:
    _, url = browser_session.url_for(case)
    ours = chromium_expectation(case, url)
    result = browser_session.download(url, case, 15_000)
    _record(
        report,
        browser_session,
        case,
        set_name="limited",
        ours=ours,
        expected=case.chromium,
        result=result,
    )
    if browser_session.name == "chromium":
        assert result is not None, "the click started no download"
        assert result == case.chromium
        assert ours == case.fallback
    elif result != case.chromium:
        pytest.xfail(f"{browser_session.name} gives {result!r}, Chromium gives {case.chromium!r}")


def test_the_server_sends_the_header_lines_of_each_case_byte_for_byte(server: _Server) -> None:
    # Line breaks and NULs in a value reach the browser as they are listed, and
    # with them the header lines they make on the wire.
    host, port = server.server_address[:2]
    for index, case in enumerate(CASES):
        # Far above the numbers that the browser sessions give out.
        number = 10**9 + index
        server.cases[number] = case
        received = bytearray()
        with socket.create_connection((str(host), port), timeout=10) as connection:
            connection.sendall(b"GET /case/%d/x HTTP/1.1\r\nHost: localhost\r\n\r\n" % number)
            while chunk := connection.recv(65536):
                received += chunk
        lines = b"".join(name + b": " + value + b"\r\n" for name, value in case.response_headers)
        assert received.startswith(b"HTTP/1.1 200 OK\r\n" + lines), case.id
        assert received.endswith(b"\r\n\r\n" + case.body), case.id
