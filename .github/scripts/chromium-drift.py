#!/usr/bin/env python3
"""Report Chromium source files that changed since the revision ported.

The package mirrors code at CHROMIUM_REVISION (scripts/generate_data.py).
This compares each tracked file there with Chromium's main branch, and the
ICU revision that DEPS pins, and fails if anything moved, so that a
maintainer reads the change and either ports it or bumps the pin.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GITILES = "https://chromium.googlesource.com"
# Gitiles shows history only to signed-in users; the GitHub mirror does not ask.
HISTORY = "https://github.com/chromium/chromium/commits/main"
TRACKED = (
    "net/http/http_content_disposition.cc",
    "net/http/http_util.cc",
    "net/http/http_response_headers.cc",
    "net/http/http_stream_parser.cc",
    "net/base/filename_util.cc",
    "net/base/filename_util_internal.cc",
    "net/base/filename_util_icu.cc",
    "net/base/mime_util.cc",
    "net/base/mime_sniffer.cc",
    "net/base/net_string_util_icu.cc",
    "base/i18n/file_util_icu.cc",
    "base/files/file_path.cc",
    "base/files/file_util.cc",
    "base/strings/escape.cc",
    "base/strings/string_tokenizer.h",
    "url/third_party/mozilla/url_parse.cc",
    "services/network/url_loader.cc",
    "components/download/internal/common/download_utils.cc",
    "content/browser/devtools/protocol/browser_handler.cc",
)


def fetch(path: str) -> bytes:
    request = urllib.request.Request(
        f"{GITILES}/{path}?format=TEXT", headers={"User-Agent": "chromium-drift"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return base64.b64decode(response.read())


def pinned(name: str) -> str:
    source = (ROOT / "scripts/generate_data.py").read_text(encoding="utf-8")
    match = re.search(rf'^{name} = "([0-9a-f]{{40}})"$', source, re.MULTILINE)
    if match is None:
        raise SystemExit(f"cannot find {name} in scripts/generate_data.py")
    return match[1]


def icu_revision(deps: str) -> str:
    match = re.search(r"/chromium/deps/icu\.git' \+ '@' \+ '([0-9a-f]{40})'", deps)
    if match is None:
        raise SystemExit("cannot find the ICU revision in DEPS")
    return match[1]


def write_summary(revision: str, changed: list[tuple[str, str]]) -> None:
    """Add review links to the GitHub Actions job summary, if there is one."""
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    lines = [f"## Chromium changed since `{revision[:12]}`", ""]
    lines += [f"- [`{name}`]({link})" for name, link in changed]
    lines += ["", "See MAINTENANCE.md, 跟進 Chromium.", ""]
    with open(summary, "a", encoding="utf-8") as file:
        file.write("\n".join(lines))


def main() -> int:
    revision = pinned("CHROMIUM_REVISION")
    # (what changed, where to read the change)
    changed: list[tuple[str, str]] = []
    for path in TRACKED:
        old = fetch(f"chromium/src/+/{revision}/{path}")
        new = fetch(f"chromium/src/+/refs/heads/main/{path}")
        if hashlib.sha256(old).digest() != hashlib.sha256(new).digest():
            changed.append((path, f"{HISTORY}/{path}"))
    deps = fetch("chromium/src/+/refs/heads/main/DEPS").decode("utf-8")
    icu = icu_revision(deps)
    if icu != pinned("ICU_REVISION"):
        link = f"{GITILES}/chromium/deps/icu/+log/{pinned('ICU_REVISION')}..{icu}"
        changed.append((f"third_party/icu (now {icu})", link))
    if not changed:
        print(f"no tracked Chromium file changed since {revision}")
        return 0
    write_summary(revision, changed)
    print(f"changed since {revision}:", file=sys.stderr)
    for name, link in changed:
        print(f"  {name}: {link}", file=sys.stderr)
    print(
        "review them (MAINTENANCE.md, 跟進 Chromium) and port them or bump the pins",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
