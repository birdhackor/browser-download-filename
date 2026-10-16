#!/usr/bin/env python3
"""Verify that release artifacts exactly match a release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


class BatchVerificationError(ValueError):
    """Raised when a manifest and an artifact directory are not one batch."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--artifacts",
        required=True,
        type=Path,
        help="directory containing wheel and source-distribution artifacts",
    )
    parser.add_argument(
        "--expected-version",
        default=None,
        help="optional release version which the manifest must match",
    )
    parser.add_argument(
        "--expected-source-commit",
        default=None,
        help="optional source commit which the manifest must match",
    )
    return parser.parse_args()


def artifact_kind(path: Path) -> str | None:
    if path.name.endswith(".whl"):
        return "wheel"
    if path.name.endswith(".tar.gz"):
        return "sdist"
    return None


def artifact_version(filename: str, package: str, kind: str) -> str:
    prefix = f"{package}-"
    if not filename.startswith(prefix):
        raise BatchVerificationError(f"{filename}: expected package prefix {prefix!r}")

    if kind == "wheel":
        remainder = filename[len(prefix) : -len(".whl")]
        try:
            version, _python_tag, _abi_tag, _platform_tag = remainder.split("-", 3)
        except ValueError as error:
            raise BatchVerificationError(f"{filename}: not a valid wheel filename") from error
    else:
        version = filename[len(prefix) : -len(".tar.gz")]
        if not version:
            raise BatchVerificationError(f"{filename}: source distribution has no version")
    return version


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BatchVerificationError(f"manifest does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise BatchVerificationError(f"manifest is not valid JSON: {error}") from error

    if not isinstance(manifest, dict):
        raise BatchVerificationError("manifest root must be an object")
    required = {"package", "version", "source_commit", "artifacts"}
    missing = required - manifest.keys()
    if missing:
        raise BatchVerificationError(
            f"manifest is missing required key(s): {', '.join(sorted(missing))}"
        )
    if not isinstance(manifest["package"], str) or not manifest["package"]:
        raise BatchVerificationError("manifest package must be a non-empty string")
    if not isinstance(manifest["version"], str) or not manifest["version"]:
        raise BatchVerificationError("manifest version must be a non-empty string")
    if not isinstance(manifest["source_commit"], str) or not manifest["source_commit"]:
        raise BatchVerificationError("manifest source_commit must be a non-empty string")
    if not isinstance(manifest["artifacts"], list) or not manifest["artifacts"]:
        raise BatchVerificationError("manifest artifacts must be a non-empty array")
    return manifest


def collect_manifest_artifacts(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    expected: dict[str, dict[str, str]] = {}
    package = manifest["package"]
    version = manifest["version"]

    for index, record in enumerate(manifest["artifacts"]):
        if not isinstance(record, dict):
            raise BatchVerificationError(f"manifest artifact {index} must be an object")
        if set(record) != {"filename", "sha256", "kind"}:
            raise BatchVerificationError(
                f"manifest artifact {index} must contain only filename, sha256, and kind"
            )
        filename = record["filename"]
        digest = record["sha256"]
        kind = record["kind"]
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise BatchVerificationError(
                f"manifest artifact {index} has an invalid filename: {filename!r}"
            )
        if not isinstance(digest, str) or len(digest) != 64:
            raise BatchVerificationError(f"manifest artifact {filename} has an invalid sha256")
        try:
            int(digest, 16)
        except ValueError as error:
            raise BatchVerificationError(
                f"manifest artifact {filename} has an invalid sha256"
            ) from error
        if kind not in {"wheel", "sdist"}:
            raise BatchVerificationError(f"manifest artifact {filename} has invalid kind {kind!r}")
        expected_kind = artifact_kind(Path(filename))
        if expected_kind != kind:
            raise BatchVerificationError(
                f"manifest artifact {filename} kind is {kind!r}, filename implies {expected_kind!r}"
            )
        filename_version = artifact_version(filename, package, kind)
        if filename_version != version:
            raise BatchVerificationError(
                f"manifest artifact {filename} has version {filename_version!r}, "
                f"expected {version!r}"
            )
        if filename in expected:
            raise BatchVerificationError(f"manifest lists artifact more than once: {filename}")
        expected[filename] = {"sha256": digest.lower(), "kind": kind}
    return expected


def collect_actual_artifacts(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        raise BatchVerificationError(f"artifact directory does not exist: {directory}")

    actual: dict[str, Path] = {}
    for path in directory.rglob("*"):
        if not path.is_file() or artifact_kind(path) is None:
            continue
        if path.name in actual:
            raise BatchVerificationError(
                f"artifact directory has duplicate artifact filename: {path.name}"
            )
        actual[path.name] = path
    return actual


def verify(args: argparse.Namespace) -> tuple[int, str, str]:
    manifest = read_manifest(args.manifest)
    expected = collect_manifest_artifacts(manifest)
    actual = collect_actual_artifacts(args.artifacts)
    errors: list[str] = []

    if args.expected_version is not None:
        if not args.expected_version:
            errors.append("expected version must be a non-empty string when provided")
        elif manifest["version"] != args.expected_version:
            errors.append(
                f"manifest version {manifest['version']!r} does not match "
                f"expected version {args.expected_version!r}"
            )
    if args.expected_source_commit is not None:
        if not args.expected_source_commit:
            errors.append("expected source commit must be a non-empty string when provided")
        elif manifest["source_commit"] != args.expected_source_commit:
            errors.append(
                f"manifest source_commit {manifest['source_commit']!r} does not match "
                f"expected source commit {args.expected_source_commit!r}"
            )

    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    errors.extend(f"missing artifact listed in manifest: {filename}" for filename in missing)
    errors.extend(
        f"unexpected wheel or sdist not listed in manifest: {filename}" for filename in unexpected
    )

    for filename in sorted(set(expected) & set(actual)):
        actual_digest = sha256(actual[filename])
        expected_digest = expected[filename]["sha256"]
        if actual_digest != expected_digest:
            errors.append(
                f"sha256 mismatch for {filename}: expected {expected_digest}, got {actual_digest}"
            )

    if errors:
        return 1, "\n".join(f"batch verification failed: {error}" for error in errors), ""
    return (
        0,
        "",
        f"batch verification passed: {len(expected)} artifact(s), "
        f"version {manifest['version']}, source {manifest['source_commit']}",
    )


def main() -> int:
    args = parse_args()
    try:
        status, error_output, success_output = verify(args)
    except BatchVerificationError as error:
        print(f"batch verification failed: {error}", file=sys.stderr)
        return 1
    if error_output:
        print(error_output, file=sys.stderr)
    if success_output:
        print(success_output)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
