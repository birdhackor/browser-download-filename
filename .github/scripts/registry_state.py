#!/usr/bin/env python3
"""Fail-closed release-registry state checks."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from enum import Enum, auto
from pathlib import Path
from typing import Any

PYPI_BASE_URL = "https://pypi.org/pypi"
USER_AGENT = "browser-download-filename-release-registry-check/1.0"
NOT_FOUND = object()
ERROR = 2
PYPI_SET_MATCH_TIMEOUT_ENV = "PYPI_SET_MATCH_TIMEOUT_SECONDS"
PYPI_SET_MATCH_INTERVAL_ENV = "PYPI_SET_MATCH_INTERVAL_SECONDS"
DEFAULT_PYPI_SET_MATCH_TIMEOUT_SECONDS = 120.0
DEFAULT_PYPI_SET_MATCH_INTERVAL_SECONDS = 10.0

# Tests replace these instead of waiting for the real polling budget.
_sleep = time.sleep
_monotonic = time.monotonic


class RegistryStateError(RuntimeError):
    """Raised when registry state cannot be established safely."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    pypi_has = subparsers.add_parser("pypi-has")
    pypi_has.add_argument("package")
    pypi_has.add_argument("version")

    pypi_matches = subparsers.add_parser(
        "pypi-set-matches",
        description=(
            "Require the exact PyPI manifest set. Retry propagation-only missing "
            "states and query errors for a bounded period. Configure the total "
            f"budget with {PYPI_SET_MATCH_TIMEOUT_ENV} "
            f"(default {DEFAULT_PYPI_SET_MATCH_TIMEOUT_SECONDS:g}) and the polling "
            f"interval with {PYPI_SET_MATCH_INTERVAL_ENV} "
            f"(default {DEFAULT_PYPI_SET_MATCH_INTERVAL_SECONDS:g}). A zero budget "
            "performs one check without retrying."
        ),
    )
    pypi_matches.add_argument("package")
    pypi_matches.add_argument("version")
    pypi_matches.add_argument("manifest", type=Path)
    return parser.parse_args(argv)


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.status
            if status != 200:
                raise RegistryStateError(f"GET {url} returned HTTP {status}")
            try:
                return json.load(response)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RegistryStateError(f"GET {url} returned invalid JSON") from error
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return NOT_FOUND
        raise RegistryStateError(f"GET {url} returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RegistryStateError(f"GET {url} failed: {error}") from error


def pypi_release(package: str, version: str) -> list[Any] | None:
    package_path = urllib.parse.quote(package, safe="")
    data = fetch_json(f"{PYPI_BASE_URL}/{package_path}/json")
    if data is NOT_FOUND:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("releases"), dict):
        raise RegistryStateError("PyPI response does not contain a releases object")
    releases = data["releases"]
    if version not in releases:
        return None
    files = releases[version]
    if not isinstance(files, list):
        raise RegistryStateError(f"PyPI release {version!r} is not a file array")
    return files


def pypi_has(package: str, version: str) -> bool:
    return pypi_release(package, version) is not None


def normalize(name: str) -> str:
    """PEP 503 name normalization: file names use "_", PyPI uses "-"."""
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_sha256(value: Any, context: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise RegistryStateError(f"{context} has an invalid sha256")
    digest = value.lower()
    if any(character not in string.hexdigits for character in digest):
        raise RegistryStateError(f"{context} has an invalid sha256")
    return digest


def manifest_pypi_files(manifest_path: Path, package: str, version: str) -> dict[str, str]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RegistryStateError(f"manifest does not exist: {manifest_path}") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegistryStateError(f"cannot read manifest {manifest_path}: {error}") from error

    if not isinstance(manifest, dict):
        raise RegistryStateError("manifest root must be an object")
    manifest_package = manifest.get("package")
    if not isinstance(manifest_package, str) or normalize(manifest_package) != normalize(package):
        raise RegistryStateError(
            f"manifest package {manifest_package!r} does not match {package!r}"
        )
    if manifest.get("version") != version:
        raise RegistryStateError(
            f"manifest version {manifest.get('version')!r} does not match {version!r}"
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise RegistryStateError("manifest artifacts must be an array")

    expected: dict[str, str] = {}
    for index, record in enumerate(artifacts):
        if not isinstance(record, dict):
            raise RegistryStateError(f"manifest artifact {index} must be an object")
        kind = record.get("kind")
        if kind not in {"wheel", "sdist"}:
            raise RegistryStateError(f"manifest artifact {index} has unsupported kind {kind!r}")
        filename = record.get("filename")
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise RegistryStateError(f"manifest artifact {index} has invalid filename {filename!r}")
        if filename in expected:
            raise RegistryStateError(f"manifest repeats artifact filename {filename}")
        expected[filename] = validate_sha256(record.get("sha256"), f"manifest artifact {filename}")
    if not expected:
        raise RegistryStateError("manifest contains no PyPI artifacts")
    return expected


def remote_pypi_files(files: list[Any], version: str) -> dict[str, str]:
    actual: dict[str, str] = {}
    for index, record in enumerate(files):
        if not isinstance(record, dict):
            raise RegistryStateError(f"PyPI release file {index} must be an object")
        filename = record.get("filename")
        digests = record.get("digests")
        if not isinstance(filename, str) or not filename:
            raise RegistryStateError(f"PyPI release file {index} has no filename")
        if filename in actual:
            raise RegistryStateError(f"PyPI repeats release filename {filename}")
        if not isinstance(digests, dict):
            raise RegistryStateError(f"PyPI release file {filename} has no digests")
        actual[filename] = validate_sha256(digests.get("sha256"), f"PyPI release file {filename}")
    return actual


class PyPISetState(Enum):
    MATCH = auto()
    NOT_YET = auto()
    CONFLICT = auto()
    QUERY_ERROR = auto()


def compare_pypi_file_sets(
    expected: dict[str, str], release: list[Any] | None, version: str
) -> tuple[PyPISetState, list[str]]:
    if release is None:
        return PyPISetState.NOT_YET, ["PyPI release is absent"]
    actual = remote_pypi_files(release, version)

    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    mismatched = sorted(
        filename
        for filename in set(expected) & set(actual)
        if expected[filename] != actual[filename]
    )
    messages = [f"PyPI set mismatch: missing {filename}" for filename in missing]
    messages.extend(f"PyPI set mismatch: unexpected {filename}" for filename in unexpected)
    messages.extend(
        (
            f"PyPI set mismatch: sha256 differs for {filename}: "
            f"manifest={expected[filename]} registry={actual[filename]}"
        )
        for filename in mismatched
    )
    if unexpected or mismatched:
        return PyPISetState.CONFLICT, messages
    if missing:
        return PyPISetState.NOT_YET, messages
    return PyPISetState.MATCH, []


def nonnegative_seconds_from_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        seconds = float(value)
    except ValueError as error:
        raise RegistryStateError(f"{name} must be a non-negative number") from error
    if not math.isfinite(seconds) or seconds < 0:
        raise RegistryStateError(f"{name} must be a non-negative number")
    return seconds


def format_seconds(seconds: float) -> str:
    return f"{seconds:g}"


def pypi_set_matches(
    package: str,
    version: str,
    manifest_path: Path,
    *,
    timeout_seconds: float | None = None,
    interval_seconds: float | None = None,
) -> bool:
    expected = manifest_pypi_files(manifest_path, package, version)
    if timeout_seconds is None:
        timeout_seconds = nonnegative_seconds_from_env(
            PYPI_SET_MATCH_TIMEOUT_ENV, DEFAULT_PYPI_SET_MATCH_TIMEOUT_SECONDS
        )
    if interval_seconds is None:
        interval_seconds = nonnegative_seconds_from_env(
            PYPI_SET_MATCH_INTERVAL_ENV, DEFAULT_PYPI_SET_MATCH_INTERVAL_SECONDS
        )
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise RegistryStateError(f"{PYPI_SET_MATCH_TIMEOUT_ENV} must be a non-negative number")
    if not math.isfinite(interval_seconds) or interval_seconds < 0:
        raise RegistryStateError(f"{PYPI_SET_MATCH_INTERVAL_ENV} must be a non-negative number")
    if timeout_seconds > 0 and interval_seconds <= 0:
        raise RegistryStateError(
            f"{PYPI_SET_MATCH_INTERVAL_ENV} must be greater than zero when "
            f"{PYPI_SET_MATCH_TIMEOUT_ENV} is greater than zero"
        )

    deadline = _monotonic() + timeout_seconds
    while True:
        query_error: RegistryStateError | None = None
        try:
            state, messages = compare_pypi_file_sets(
                expected, pypi_release(package, version), version
            )
        except RegistryStateError as error:
            state = PyPISetState.QUERY_ERROR
            messages = []
            query_error = error

        if state is PyPISetState.MATCH:
            return True
        if state is PyPISetState.CONFLICT:
            for message in messages:
                print(message, file=sys.stderr)
            return False

        remaining = deadline - _monotonic()
        if timeout_seconds == 0 or remaining <= 0:
            if state is PyPISetState.QUERY_ERROR:
                assert query_error is not None
                if timeout_seconds == 0:
                    raise query_error
                raise RegistryStateError(
                    "PyPI query did not recover within "
                    f"{format_seconds(timeout_seconds)}s; last error: {query_error}"
                ) from query_error
            for message in messages:
                print(message, file=sys.stderr)
            print(
                "PyPI did not reach the expected set within "
                f"{format_seconds(timeout_seconds)}s: {package} {version}",
                file=sys.stderr,
            )
            return False

        if state is PyPISetState.QUERY_ERROR:
            assert query_error is not None
            print(f"PyPI query error (will retry): {query_error}", file=sys.stderr)
        else:
            for message in messages:
                print(f"{message} (will retry)", file=sys.stderr)
        _sleep(min(interval_seconds, remaining))


def print_boolean(label: str, value: bool) -> int:
    print(f"{label}: {'true' if value else 'false'}")
    return 0 if value else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "pypi-has":
            return print_boolean(
                f"PyPI has {args.package} {args.version}",
                pypi_has(args.package, args.version),
            )
        return print_boolean(
            f"PyPI set matches {args.package} {args.version}",
            pypi_set_matches(args.package, args.version, args.manifest),
        )
    except RegistryStateError as error:
        print(f"registry state error: {error}", file=sys.stderr)
        return ERROR


if __name__ == "__main__":
    raise SystemExit(main())
