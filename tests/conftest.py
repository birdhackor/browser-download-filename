from __future__ import annotations

from pathlib import Path

import pytest

BROWSERS = ("chromium", "firefox", "webkit")


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("browser differential tests")
    group.addoption(
        "--with-browser",
        action="append",
        choices=BROWSERS,
        default=[],
        help="run tests/browser against this Playwright browser (repeatable)",
    )
    group.addoption(
        "--browser-report",
        metavar="PATH",
        help="write the browser results to PATH (JSON) and to PATH with .md (a table)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Leave the browser tests out unless a browser was asked for."""
    if config.getoption("--with-browser"):
        return
    browser_dir = Path(__file__).parent / "browser"
    kept = [item for item in items if browser_dir not in item.path.parents]
    if len(kept) != len(items):
        config.hook.pytest_deselected(items=[item for item in items if item not in kept])
        items[:] = kept
