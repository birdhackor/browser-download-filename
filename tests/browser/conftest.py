"""Fixtures that ask real browsers what they name a download.

The browser tests run only with --with-browser (chromium, firefox or webkit;
repeatable). A small HTTP server sends each case's header lines, in order,
and its body byte for byte, a Playwright page clicks a same-origin link to
it, and the test compares the download's suggested filename with the name
Chrome is expected to give.
"""

from __future__ import annotations

import json
import socketserver
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from .corpus import BrowserCase

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

INDEX_PAGE = (
    b"<!doctype html><meta charset=utf-8><title>downloads</title><a id=link href=#>link</a>"
)
SETS = ("exact", "limited")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "browser_name" in metafunc.fixturenames:
        metafunc.parametrize(
            "browser_name", metafunc.config.getoption("--with-browser"), scope="session"
        )


class _Handler(socketserver.StreamRequestHandler):
    server: _Server

    def handle(self) -> None:
        request_line = self.rfile.readline(65536)
        while self.rfile.readline(65536) not in (b"", b"\r\n", b"\n"):
            pass
        parts = request_line.split(b" ")
        target = parts[1].decode("latin-1") if len(parts) > 2 else "/"
        segments = target.split("/")
        if len(segments) > 2 and segments[1] == "case" and segments[2].isdigit():
            case = self.server.cases[int(segments[2])]
            head = b"HTTP/1.1 200 OK\r\n"
            for name, value in case.response_headers:
                head += name + b": " + value + b"\r\n"
            body = case.body
        else:
            head = b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
            body = INDEX_PAGE
        head += b"Cache-Control: no-store\r\nConnection: close\r\n"
        head += b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n"
        self.wfile.write(head + body)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    cases: dict[int, BrowserCase]


@pytest.fixture(scope="session")
def server() -> Iterator[_Server]:
    with _Server(("127.0.0.1", 0), _Handler) as httpd:
        httpd.cases = {}
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield httpd
        httpd.shutdown()


@pytest.fixture(scope="session")
def base_url(server: _Server) -> str:
    host, port = server.server_address[:2]
    assert isinstance(host, str)
    return f"http://{host}:{port}"


@dataclass
class BrowserSession:
    name: str
    version: str
    page: Page
    base_url: str
    server: _Server
    timeout_error: type[Exception]
    _next_id: int = 0

    @property
    def major_version(self) -> int:
        return int(self.version.split(".", 1)[0])

    def url_for(self, case: BrowserCase) -> tuple[int, str]:
        self._next_id += 1
        self.server.cases[self._next_id] = case
        return self._next_id, f"{self.base_url}/case/{self._next_id}/{case.path}"

    def download(self, url: str, case: BrowserCase, timeout_ms: float) -> str | None:
        """The suggested filename, or None if the click downloaded nothing."""
        page = self.page
        page.evaluate(
            """([url, name]) => {
                const link = document.getElementById("link");
                link.href = url;
                if (name === null) link.removeAttribute("download");
                else link.setAttribute("download", name);
            }""",
            [url, case.download_attribute],
        )
        try:
            with page.expect_download(timeout=timeout_ms) as info:
                page.click("#link")
        except self.timeout_error:
            page.goto(self.base_url + "/")
            return None
        download = info.value
        name = download.suggested_filename
        download.cancel()
        return name


@pytest.fixture(scope="session")
def browser_session(browser_name: str, base_url: str, server: _Server) -> Iterator[BrowserSession]:
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as playwright:
        browser: Browser = getattr(playwright, browser_name).launch()
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(base_url + "/")
        yield BrowserSession(
            browser_name, browser.version, page, base_url, server, playwright_api.TimeoutError
        )
        context.close()
        browser.close()


@dataclass
class Report:
    rows: list[dict[str, Any]] = field(default_factory=list)


@pytest.fixture(scope="session")
def report(request: pytest.FixtureRequest) -> Iterator[Report]:
    collected = Report()
    yield collected
    path = request.config.getoption("--browser-report")
    if not path:
        return
    target = Path(path)
    target.write_text(json.dumps(collected.rows, ensure_ascii=False, indent=1), encoding="utf-8")
    # "expected" is the name Chrome gives: the package's in the exact set, the
    # one the corpus lists in the limited set.
    differing = [row for row in collected.rows if row["expected"] != row["result"]]
    lines = []
    for engine, version in dict.fromkeys((row["engine"], row["version"]) for row in collected.rows):
        for name in SETS:
            rows = [row for row in collected.rows if row["engine"] == engine and row["set"] == name]
            if rows:
                same = sum(row["expected"] == row["result"] for row in rows)
                lines.append(
                    f"- {engine} {version}, {name} set: {len(rows)} cases, {same} same as Chrome,"
                    f" {len(rows) - same} differ"
                )
    if differing:
        lines += [
            "",
            "| browser | set | case | Chrome | this package | browser |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {row['engine']} | {row['set']} | `{row['case']}` | {_cell(row['expected'])}"
            f" | {_cell(row['ours'])} | {_cell(row['result'])} |"
            for row in differing
        ]
    target.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cell(value: str | None) -> str:
    if value is None:
        return "*(no download)*"
    escaped = value.encode("unicode_escape").decode("ascii").replace("|", "\\|")
    return f"`{escaped}`"
