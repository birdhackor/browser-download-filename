#!/usr/bin/env python3
"""Check that the wheel and the sdist ship what they must, and nothing else.

The wheel holds the package, its type marker and the license files; the
sdist also carries the tests and the data generator so that it can be
rebuilt and tested on its own.
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path

PACKAGE = "browser_download_filename"
MODULES = {
    "__init__.py",
    "_bytes.py",
    "_charset.py",
    "_content_disposition.py",
    "_data.py",
    "_filename.py",
    "_http.py",
    "_url.py",
    "py.typed",
}
LICENSES = {"LICENSE-APACHE", "LICENSE-MIT", "THIRD-PARTY-LICENSES"}
LICENSE_EXPRESSION = "(MIT OR Apache-2.0) AND BSD-3-Clause AND Unicode-3.0"


def check_wheel(path: Path) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(path) as wheel:
        names = {name for name in wheel.namelist() if not name.endswith("/")}
        dist_info = {name.split("/", 1)[0] for name in names if ".dist-info/" in name}
        if len(dist_info) != 1:
            return [f"{path.name}: expected one .dist-info directory, found {sorted(dist_info)}"]
        (info,) = dist_info
        metadata = Parser().parsestr(wheel.read(f"{info}/METADATA").decode("utf-8"))
    package = {name.split("/", 1)[1] for name in names if name.startswith(f"{PACKAGE}/")}
    if package != MODULES:
        errors.append(f"{path.name}: package files {sorted(package)} differ from {sorted(MODULES)}")
    licenses = {name.rsplit("/", 1)[1] for name in names if name.startswith(f"{info}/licenses/")}
    if licenses != LICENSES:
        errors.append(
            f"{path.name}: license files {sorted(licenses)} differ from {sorted(LICENSES)}"
        )
    stray = sorted(name for name in names if not name.startswith((f"{PACKAGE}/", f"{info}/")))
    if stray:
        errors.append(f"{path.name}: unexpected files {stray}")
    if metadata.get("License-Expression") != LICENSE_EXPRESSION:
        errors.append(f"{path.name}: License-Expression is {metadata.get('License-Expression')!r}")
    if metadata.get("Requires-Python") != ">=3.11":
        errors.append(f"{path.name}: Requires-Python is {metadata.get('Requires-Python')!r}")
    if metadata.get_all("Requires-Dist"):
        errors.append(f"{path.name}: has runtime dependencies {metadata.get_all('Requires-Dist')}")
    if metadata.get("Description-Content-Type") != "text/markdown":
        errors.append(f"{path.name}: README is not rendered as Markdown")
    return errors


def check_sdist(path: Path) -> list[str]:
    with tarfile.open(path) as sdist:
        names = {
            member.name.split("/", 1)[1] for member in sdist.getmembers() if "/" in member.name
        }
    required = {
        "pyproject.toml",
        "README.md",
        "PKG-INFO",
        *LICENSES,
        *(f"src/{PACKAGE}/{module}" for module in MODULES),
        "tests/test_chromium_content_disposition.py",
        "tests/browser/corpus.py",
        "scripts/generate_data.py",
    }
    missing = sorted(required - names)
    errors = [f"{path.name}: missing {missing}"] if missing else []
    cached = sorted(name for name in names if "__pycache__" in name or name.endswith(".pyc"))
    if cached:
        errors.append(f"{path.name}: contains bytecode {cached}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path, help="directory with the built wheel and sdist")
    args = parser.parse_args()
    wheels = sorted(args.dist.glob("*.whl"))
    sdists = sorted(args.dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print(f"expected one wheel and one sdist in {args.dist}", file=sys.stderr)
        return 1
    errors = check_wheel(wheels[0]) + check_sdist(sdists[0])
    for error in errors:
        print(f"dist check failed: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"dist check passed: {wheels[0].name}, {sdists[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
