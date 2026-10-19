"""The public surface: names, types, metadata and documentation."""

from __future__ import annotations

import dataclasses
import inspect
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import browser_download_filename
from browser_download_filename import (
    ContentDisposition,
    parse_content_disposition,
    sanitize_filename,
    suggested_filename,
)
from browser_download_filename._data import CHROMIUM_REVISION, ICU_REVISION

ROOT = Path(__file__).resolve().parents[1]


def test_public_names() -> None:
    assert sorted(browser_download_filename.__all__) == [
        "ContentDisposition",
        "HeadersLike",
        "__version__",
        "parse_content_disposition",
        "sanitize_filename",
        "suggested_filename",
    ]


def test_version_matches_project_metadata() -> None:
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip("not running from a source checkout")
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    assert browser_download_filename.__version__ == project["version"]


def test_importlib_metadata_is_loaded_only_when_the_version_is_read() -> None:
    def loads_importlib_metadata(statement: str) -> bool:
        code = f"import sys\n{statement}\nprint('importlib.metadata' in sys.modules)"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip() == "True"

    if loads_importlib_metadata("pass"):
        pytest.skip("this interpreter loads importlib.metadata at startup")
    assert not loads_importlib_metadata("import browser_download_filename")
    assert loads_importlib_metadata("import browser_download_filename as b; b.__version__")


def test_a_misspelled_name_is_reported_at_run_time_and_by_type_checkers() -> None:
    # mypy reports this ignore as unused if it takes the misspelled name for
    # the str that a module __getattr__ returns.
    with pytest.raises(AttributeError, match="sugested_filename"):
        _ = browser_download_filename.sugested_filename  # type: ignore[attr-defined]


def test_content_disposition_is_a_frozen_value() -> None:
    parsed = parse_content_disposition("attachment; filename=a.txt")
    assert dataclasses.is_dataclass(parsed)
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.filename = "b.txt"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.blocks_download = True  # type: ignore[misc]
    assert parsed == ContentDisposition("attachment", "a.txt")
    assert hash(parsed) == hash(ContentDisposition("attachment", "a.txt"))


def test_content_disposition_fields() -> None:
    fields = {field.name: field for field in dataclasses.fields(ContentDisposition)}
    assert list(fields) == ["type", "filename", "blocks_download"]
    assert fields["blocks_download"].default is False
    # Every field takes part in equality, hashing and the repr.
    assert all(field.compare and field.repr and field.hash is None for field in fields.values())
    blocked = ContentDisposition("attachment", "a.txt", True)
    assert blocked.blocks_download is True
    assert blocked != ContentDisposition("attachment", "a.txt")
    assert hash(blocked) == hash(ContentDisposition("attachment", "a.txt", blocks_download=True))
    assert len({blocked, ContentDisposition("attachment", "a.txt")}) == 2
    assert repr(blocked) == (
        "ContentDisposition(type='attachment', filename='a.txt', blocks_download=True)"
    )


def test_signatures() -> None:
    parameters = inspect.signature(parse_content_disposition).parameters
    assert list(parameters) == ["value", "fallback_charset", "headers_encoding"]
    assert parameters["value"].kind is inspect.Parameter.POSITIONAL_ONLY
    assert parameters["value"].default is inspect.Parameter.empty
    assert all(
        parameters[name].kind is inspect.Parameter.KEYWORD_ONLY and parameters[name].default is None
        for name in ("fallback_charset", "headers_encoding")
    )
    parameters = inspect.signature(suggested_filename).parameters
    assert list(parameters) == [
        "headers",
        "url",
        "content_disposition",
        "content_type",
        "download_attribute",
        "default_name",
        "fallback_charset",
        "headers_encoding",
        "platform",
    ]
    assert parameters["headers"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for name, parameter in parameters.items()
        if name != "headers"
    )
    assert {name: parameter.default for name, parameter in parameters.items()} == {
        "headers": None,
        "url": None,
        "content_disposition": None,
        "content_type": None,
        "download_attribute": None,
        "default_name": "download",
        "fallback_charset": None,
        "headers_encoding": None,
        "platform": None,
    }
    parameters = inspect.signature(sanitize_filename).parameters
    assert list(parameters) == ["name", "default_name", "platform"]
    assert parameters["name"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["name"].default is inspect.Parameter.empty
    assert parameters["default_name"].default == "download"
    assert parameters["platform"].default is None
    assert all(
        parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        for name in ("default_name", "platform")
    )


@pytest.mark.parametrize(
    "member",
    [
        browser_download_filename,
        ContentDisposition,
        parse_content_disposition,
        sanitize_filename,
        suggested_filename,
    ],
)
def test_documented(member: object) -> None:
    assert inspect.getdoc(member)


def test_typed_package() -> None:
    package = Path(browser_download_filename.__file__).parent
    assert (package / "py.typed").exists()


def test_pinned_revisions_look_like_commits() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", CHROMIUM_REVISION)
    assert re.fullmatch(r"[0-9a-f]{40}", ICU_REVISION)
