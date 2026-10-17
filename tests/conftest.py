from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

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
    parser.getgroup("HTTP client tests").addoption(
        "--with-http-clients",
        action="store_true",
        help="run tests/http_clients, which needs the http-clients dependency group",
    )


def http_client_distributions() -> list[str]:
    """The names of the distributions in pyproject.toml's http-clients group."""
    with (Path(__file__).parent.parent / "pyproject.toml").open("rb") as file:
        group = tomllib.load(file)["dependency-groups"]["http-clients"]
    return [Requirement(requirement).name for requirement in group]


def is_installed(distribution: str) -> bool:
    try:
        importlib.metadata.distribution(distribution)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def pytest_configure(config: pytest.Config) -> None:
    """Asking for the HTTP client tests without the libraries is an error."""
    if not config.getoption("--with-http-clients"):
        return
    missing = [name for name in http_client_distributions() if not is_installed(name)]
    if missing:
        raise pytest.UsageError(
            f"--with-http-clients needs {', '.join(missing)}, from the http-clients "
            "dependency group, which `uv sync` installs as part of dev"
        )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Leave the browser and HTTP client tests out unless they were asked for."""
    left_out: list[Path] = []
    if not config.getoption("--with-browser"):
        left_out.append(Path(__file__).parent / "browser")
    if not config.getoption("--with-http-clients"):
        left_out.append(Path(__file__).parent / "http_clients")
    kept = [item for item in items if not any(path in item.path.parents for path in left_out)]
    if len(kept) != len(items):
        config.hook.pytest_deselected(items=[item for item in items if item not in kept])
        items[:] = kept
