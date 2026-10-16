"""Differential tests: this package against real browsers.

Chromium must agree exactly, since the package ports its rules. Firefox and
WebKit are only compared and reported; where they differ from Chromium the
test is marked as an expected failure, and the report lists the case.
"""

from __future__ import annotations

import pytest

from browser_download_filename import parse_content_disposition, suggested_filename

from .conftest import BrowserSession, Report
from .corpus import BrowserCase, all_cases

CASES = all_cases()


def chromium_expectation(case: BrowserCase, url: str) -> str | None:
    """What Chromium reports, per this package's model of it."""
    headers = [(b"Content-Disposition", value) for value in case.headers]
    if parse_content_disposition(headers).blocks_download:
        # net::ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION: the network
        # stack refuses the response. A plain link downloads nothing; a link
        # with a download attribute starts a download that fails, named as if
        # the response had neither Content-Disposition nor a Content-Type.
        if case.download_attribute is None:
            return None
        return suggested_filename(
            url=url, download_attribute=case.download_attribute, platform="posix"
        )
    return suggested_filename(
        headers,
        url=url,
        content_type=case.content_type,
        download_attribute=case.download_attribute,
        # The package models Chrome on Linux, where CI runs this comparison.
        platform="posix",
    )


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_download_name(case: BrowserCase, browser_session: BrowserSession, report: Report) -> None:
    is_chromium = browser_session.name == "chromium"
    _, url = browser_session.url_for(case)
    ours = chromium_expectation(case, url)
    timeout_ms = 2_000 if ours is None else 15_000
    result = browser_session.download(url, case, timeout_ms)
    report.rows.append(
        {
            "engine": browser_session.name,
            "version": browser_session.version,
            "case": case.id,
            "headers": [header.decode("latin-1") for header in case.headers],
            "path": case.path,
            "content_type": case.content_type,
            "download_attribute": case.download_attribute,
            "ours": ours,
            "result": result,
        }
    )
    if is_chromium:
        assert result == ours
    elif result != ours:
        pytest.xfail(f"{browser_session.name} gives {result!r}, Chromium rules give {ours!r}")
