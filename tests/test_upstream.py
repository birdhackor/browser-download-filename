"""Source outages must not look like a completed drift comparison."""

from __future__ import annotations

import base64
import importlib
import importlib.util
import runpy
import sys
from email.message import Message
from http.client import IncompleteRead
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

ROOT = Path(__file__).resolve().parents[1]
URL = "https://chromium.googlesource.com/chromium/src/+/main/net/base/mime_util.cc?format=TEXT"


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("upstream")


def http_error(status: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(URL, status, "test failure", headers, None)


def response(payload: bytes = b"source") -> MagicMock:
    result = MagicMock()
    result.__enter__.return_value.read.return_value = base64.b64encode(payload)
    return result


def test_fetch_decodes_the_source_and_closes_the_response(upstream: ModuleType) -> None:
    result = response(b"source\x00\xff")
    with patch.object(upstream.urllib.request, "urlopen", return_value=result) as open_url:
        assert upstream.fetch(URL, user_agent="test") == b"source\x00\xff"
    request = open_url.call_args.args[0]
    assert request.full_url == URL
    assert request.get_header("User-agent") == "test"
    assert open_url.call_args.kwargs == {"timeout": 60}
    result.__exit__.assert_called_once()


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_transient_http_errors_retry_then_recover(upstream: ModuleType, status: int) -> None:
    with (
        patch.object(
            upstream.urllib.request, "urlopen", side_effect=[http_error(status), response()]
        ) as open_url,
        patch.object(upstream.time, "sleep") as sleep,
    ):
        assert upstream.fetch(URL, user_agent="test") == b"source"
    assert open_url.call_count == 2
    sleep.assert_called_once_with(1)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 501])
def test_other_http_errors_fail_without_retry(upstream: ModuleType, status: int) -> None:
    with (
        patch.object(
            upstream.urllib.request, "urlopen", side_effect=http_error(status)
        ) as open_url,
        patch.object(upstream.time, "sleep") as sleep,
        pytest.raises(upstream.SourceFetchError) as caught,
    ):
        upstream.fetch(URL, user_agent="test")
    assert open_url.call_count == 1
    sleep.assert_not_called()
    assert caught.value.temporary is False
    assert URL in str(caught.value)


@pytest.mark.parametrize(
    "error", [URLError("connection reset"), TimeoutError(), ConnectionResetError()]
)
def test_transport_errors_retry(upstream: ModuleType, error: Exception) -> None:
    with (
        patch.object(upstream.urllib.request, "urlopen", side_effect=[error, response()]),
        patch.object(upstream.time, "sleep") as sleep,
    ):
        assert upstream.fetch(URL, user_agent="test") == b"source"
    sleep.assert_called_once_with(1)


def test_interrupted_response_is_closed_and_retried(upstream: ModuleType) -> None:
    interrupted = response()
    interrupted.__enter__.return_value.read.side_effect = IncompleteRead(b"partial", 100)
    with (
        patch.object(upstream.urllib.request, "urlopen", side_effect=[interrupted, response()]),
        patch.object(upstream.time, "sleep") as sleep,
    ):
        assert upstream.fetch(URL, user_agent="test") == b"source"
    interrupted.__exit__.assert_called_once()
    sleep.assert_called_once_with(1)


def test_retry_exhaustion_reports_url_and_incomplete_status(
    upstream: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    with (
        patch.object(upstream.urllib.request, "urlopen", side_effect=http_error(503)) as open_url,
        patch.object(upstream.time, "sleep") as sleep,
        pytest.raises(upstream.SourceFetchError) as caught,
    ):
        upstream.fetch(URL, user_agent="test")
    assert open_url.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2, 4]
    assert caught.value.temporary is True
    assert upstream.report_failure(caught.value, check="Chromium source drift check") == 2
    for output in (capsys.readouterr().err, summary.read_text()):
        assert URL in output
        assert "HTTP 503" in output
        assert "source temporarily unavailable" in output
        assert "No drift conclusion can be drawn" in output


@pytest.mark.parametrize(("value", "delay"), [("5", 5), ("999999", 30), ("invalid", 1), ("-1", 1)])
def test_retry_after_is_bounded(upstream: ModuleType, value: str, delay: int) -> None:
    with (
        patch.object(
            upstream.urllib.request, "urlopen", side_effect=[http_error(429, value), response()]
        ),
        patch.object(upstream.time, "sleep") as sleep,
    ):
        assert upstream.fetch(URL, user_agent="test") == b"source"
    sleep.assert_called_once_with(delay)


def test_retry_after_accepts_an_http_date(upstream: ModuleType) -> None:
    with patch.object(upstream, "datetime") as clock:
        clock.now.return_value = upstream.parsedate_to_datetime("Wed, 11 Nov 2026 03:00:00 GMT")
        assert upstream.retry_after_seconds("Wed, 11 Nov 2026 03:00:10 GMT") == 10


def test_invalid_response_is_a_fetch_failure_without_retry(upstream: ModuleType) -> None:
    invalid = response()
    invalid.__enter__.return_value.read.return_value = b"not base64!"
    with (
        patch.object(upstream.urllib.request, "urlopen", return_value=invalid) as open_url,
        patch.object(upstream.time, "sleep") as sleep,
        pytest.raises(upstream.SourceFetchError, match="invalid Gitiles base64") as caught,
    ):
        upstream.fetch(URL, user_agent="test")
    assert caught.value.temporary is False
    assert open_url.call_count == 1
    sleep.assert_not_called()


@pytest.fixture
def drift(upstream: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    path = ROOT / ".github/scripts/chromium-drift.py"
    if not path.is_file():
        pytest.skip("the Actions-only drift script is not shipped in the sdist")
    spec = importlib.util.spec_from_file_location("chromium_drift", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The script adds its sibling scripts directory when run directly.
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "TRACKED", ("one.cc", "two.cc"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    return module


@pytest.mark.parametrize("changed", ["none", "source", "icu"])
def test_completed_drift_check_preserves_real_differences(
    drift: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changed: str
) -> None:
    icu = "0" * 40 if changed == "icu" else drift.pinned("ICU_REVISION")
    deps = f"'/chromium/deps/icu.git' + '@' + '{icu}'".encode()
    new = b"changed" if changed == "source" else b"same"
    monkeypatch.setattr(
        drift, "fetch", MagicMock(side_effect=[b"same", new, b"same", b"same", deps])
    )
    assert drift.main() == (0 if changed == "none" else 1)
    summary = tmp_path / "summary.md"
    if changed == "none":
        assert not summary.exists()
    else:
        text = summary.read_text()
        assert "Chromium changed since" in text
        assert ("one.cc" if changed == "source" else "third_party/icu") in text
        assert "incomplete" not in text


@pytest.mark.parametrize("failure_at", [0, 1, 4], ids=["pinned", "main-after-difference", "deps"])
def test_failed_drift_check_never_claims_a_completed_comparison(
    drift: ModuleType,
    upstream: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_at: int,
) -> None:
    failure = upstream.SourceFetchError(URL, 4, "HTTP 503", temporary=True)
    # Even if an earlier file differed, an outage makes the overall check incomplete.
    results = [*[b"old", b"new", b"same", b"same"][:failure_at], failure]
    monkeypatch.setattr(drift, "fetch", MagicMock(side_effect=results))
    assert drift.main() == 2
    text = (tmp_path / "summary.md").read_text()
    assert "incomplete: source temporarily unavailable" in text
    assert URL in text
    assert "Chromium changed since" not in text


def test_generator_cli_uses_the_same_fetch_failure_status(
    upstream: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["generate_data.py", "--check"])
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr("unicodedata.unidata_version", "17.0.0")
    with (
        patch.object(upstream.urllib.request, "urlopen", side_effect=http_error(503)) as open_url,
        patch.object(upstream.time, "sleep"),
        pytest.raises(SystemExit) as caught,
    ):
        runpy.run_path(str(ROOT / "scripts/generate_data.py"), run_name="__main__")
    assert caught.value.code == 2
    assert open_url.call_count == 4
    error = capsys.readouterr().err
    assert "Generated data check incomplete: source temporarily unavailable" in error
    assert "source/data/mappings/convrtrs.txt?format=TEXT" in error
