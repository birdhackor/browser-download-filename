"""The public surface: names, types, metadata and documentation."""

from __future__ import annotations

import dataclasses
import inspect
import re
import tomllib
from pathlib import Path

import pytest

import browser_download_filename
from browser_download_filename import (
    ContentDisposition,
    parse_content_disposition,
    suggested_filename,
)
from browser_download_filename._data import CHROMIUM_REVISION, ICU_REVISION

ROOT = Path(__file__).resolve().parents[1]


def test_public_names() -> None:
    assert sorted(browser_download_filename.__all__) == [
        "ContentDisposition",
        "__version__",
        "parse_content_disposition",
        "suggested_filename",
    ]


def test_version_matches_project_metadata() -> None:
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip("not running from a source checkout")
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    assert browser_download_filename.__version__ == project["version"]


def test_content_disposition_is_a_frozen_value() -> None:
    parsed = parse_content_disposition("attachment; filename=a.txt")
    assert dataclasses.is_dataclass(parsed)
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.filename = "b.txt"  # type: ignore[misc]
    assert parsed == ContentDisposition("attachment", "a.txt")
    assert hash(parsed) == hash(ContentDisposition("attachment", "a.txt"))


def test_signatures() -> None:
    parameters = inspect.signature(parse_content_disposition).parameters
    assert list(parameters) == ["value", "fallback_charset"]
    assert parameters["fallback_charset"].kind is inspect.Parameter.KEYWORD_ONLY
    parameters = inspect.signature(suggested_filename).parameters
    assert list(parameters) == [
        "url",
        "content_disposition",
        "suggested_name",
        "mime_type",
        "default_name",
        "fallback_charset",
        "platform",
    ]
    assert all(
        parameters[name].kind is inspect.Parameter.KEYWORD_ONLY for name in list(parameters)[2:]
    )


@pytest.mark.parametrize(
    "member",
    [browser_download_filename, ContentDisposition, parse_content_disposition, suggested_filename],
)
def test_documented(member: object) -> None:
    assert inspect.getdoc(member)


def test_typed_package() -> None:
    package = Path(browser_download_filename.__file__).parent
    assert (package / "py.typed").exists()


def test_pinned_revisions_look_like_commits() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", CHROMIUM_REVISION)
    assert re.fullmatch(r"[0-9a-f]{40}", ICU_REVISION)
