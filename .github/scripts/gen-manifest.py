#!/usr/bin/env python3
"""Write the release-artifact manifest consumed by the release workflow.

A pure-Python release is exactly one py3-none-any wheel and one sdist; any
other artifact, or a missing one, stops the release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts",
        required=True,
        type=Path,
        help="directory containing the wheel and the source distribution",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--package",
        required=True,
        help="distribution name as it appears in file names, e.g. browser_download_filename",
    )
    parser.add_argument("--source-commit", required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def only(paths: list[Path], what: str) -> Path:
    if len(paths) != 1:
        names = ", ".join(path.name for path in paths) or "none"
        raise ValueError(f"expected exactly one {what}, found {len(paths)}: {names}")
    return paths[0]


def main() -> int:
    args = parse_args()
    if not args.artifacts.is_dir():
        raise ValueError(f"artifact directory does not exist: {args.artifacts}")
    files = sorted(path for path in args.artifacts.rglob("*") if path.is_file())
    wheels = [path for path in files if path.name.endswith(".whl")]
    sdists = [path for path in files if path.name.endswith(".tar.gz")]
    others = [path for path in files if path not in wheels and path not in sdists]
    if others:
        raise ValueError("unexpected artifacts: " + ", ".join(path.name for path in others))
    wheel = only(wheels, "wheel")
    sdist = only(sdists, "source distribution")

    prefix = f"{args.package}-"
    if not wheel.name.startswith(prefix) or not wheel.name.endswith("-py3-none-any.whl"):
        raise ValueError(f"{wheel.name}: expected {prefix}<version>-py3-none-any.whl")
    if not sdist.name.startswith(prefix):
        raise ValueError(f"{sdist.name}: expected {prefix}<version>.tar.gz")
    wheel_version = wheel.name[len(prefix) : -len("-py3-none-any.whl")]
    sdist_version = sdist.name[len(prefix) : -len(".tar.gz")]
    if not wheel_version or wheel_version != sdist_version:
        raise ValueError(f"artifact versions do not agree: {wheel_version!r}, {sdist_version!r}")

    manifest = {
        "package": args.package,
        "version": wheel_version,
        "source_commit": args.source_commit,
        "artifacts": [
            {"filename": wheel.name, "sha256": sha256(wheel), "kind": "wheel"},
            {"filename": sdist.name, "sha256": sha256(sdist), "kind": "sdist"},
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} for {wheel.name} and {sdist.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"manifest error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
