#!/usr/bin/env python3
"""Print the newest beta-or-later CPython that setup-python can install here.

The weekly canary runs the published wheel on this version. Alphas are skipped
on purpose; MAINTENANCE.md ("Weekly canary") records why.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Version strings as actions/python-versions publishes them, e.g. 3.15.0-rc.2.
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?")
# A final release outranks every pre-release of the same version.
STAGE_RANK = {"beta": 0, "rc": 1, None: 2}


class PickError(ValueError):
    """Raised when no CPython version can be picked from the manifest."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="versions-manifest.json from actions/python-versions",
    )
    parser.add_argument("--os-version", required=True, help="runner Ubuntu version, e.g. 24.04")
    parser.add_argument("--arch", required=True, help="setup-python architecture, e.g. x64")
    return parser.parse_args()


def installable(release: dict[str, Any], os_version: str, arch: str) -> bool:
    # As in setup-python's manifest match, an absent platform_version matches any OS.
    return any(
        asset.get("platform") == "linux"
        and asset.get("arch") == arch
        and asset.get("platform_version") in (None, "", os_version)
        for asset in release["files"]
    )


def pick(manifest: list[dict[str, Any]], os_version: str, arch: str) -> str:
    best: tuple[tuple[int, int, int, int, int], str] | None = None
    for release in manifest:
        version = release["version"]
        match = VERSION.fullmatch(version)
        if match is None:
            raise PickError(f"unrecognised version format in manifest: {version!r}")
        major, minor, patch, stage, number = match.groups()
        if stage == "alpha" or not installable(release, os_version, arch):
            continue
        key = (int(major), int(minor), int(patch), STAGE_RANK[stage], int(number or 0))
        if best is None or key > best[0]:
            best = (key, version)
    if best is None:
        raise PickError(f"no beta-or-later CPython for linux {os_version} {arch}")
    return best[1]


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    try:
        version = pick(manifest, args.os_version, args.arch)
    except PickError as error:
        print(f"canary python pick failed: {error}", file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
