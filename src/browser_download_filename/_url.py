"""The parts of a URL that Chromium's filename generation reads.

GURL canonicalizes the URL first. Only the pieces that can change the
filename are reproduced here: validity, scheme, host, the last path segment
(after backslashes become slashes and dot segments are resolved in special
URLs), and whether a query is present. Percent-encoding differences do not
matter, since the file name is unescaped afterwards anyway.

The path-segment logic is ported from Chromium's url/third_party/mozilla/
url_parse.cc (see THIRD-PARTY-LICENSES).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ._bytes import unescape_binary_url_component

_SPECIAL_SCHEMES = frozenset({"http", "https", "ws", "wss", "ftp", "file"})
_SCHEME = re.compile(r"([A-Za-z][A-Za-z0-9+\-.]*):")
_C0_OR_SPACE = "".join(map(chr, range(0x21)))
_TAB_OR_NEWLINE = re.compile(r"[\t\n\r]")
_FORBIDDEN_HOST = re.compile(r"[\x00-\x20#%/:<>?@\[\\\]^|\x7f]")
_IPV6 = re.compile(r"\[[0-9A-Fa-f:.]+\]")
_SINGLE_DOT = frozenset({".", "%2e"})
_DOUBLE_DOT = frozenset({"..", ".%2e", "%2e.", "%2e%2e"})


@dataclass(frozen=True, slots=True)
class ParsedURL:
    scheme: str
    host: str
    path: str
    has_query: bool

    def extract_file_name(self) -> str:
        """url::ExtractFileName: after the last slash, up to the first ';'."""
        path = self.path
        end = len(path)
        for index in range(len(path) - 1, -1, -1):
            char = path[index]
            if char == ";":
                end = index
            elif char in "/\\":
                return path[index + 1 : end]
        return path[:end]


def _canonical_host(host: str) -> str | None:
    if _IPV6.fullmatch(host):
        return host.lower()
    try:
        host = unescape_binary_url_component(host.encode("utf-8")).decode("utf-8")
    except UnicodeError:
        return None
    if _FORBIDDEN_HOST.search(host):
        return None
    host = host.lower() if host.isascii() else host
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return None
    return host


def _remove_dot_segments(path: str) -> str:
    segments = path.split("/")[1:]
    out: list[str] = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        lowered = segment.lower()
        if lowered in _DOUBLE_DOT:
            if out:
                out.pop()
            if last:
                out.append("")
        elif lowered in _SINGLE_DOT:
            if last:
                out.append("")
        else:
            out.append(segment)
    return "/" + "/".join(out)


def parse_url(url: str | None) -> ParsedURL | None:
    """Parse an absolute URL; None when GURL would consider it invalid."""
    if not url:
        return None
    url = _TAB_OR_NEWLINE.sub("", url.strip(_C0_OR_SPACE))
    match = _SCHEME.match(url)
    if match is None:
        return None
    scheme = match[1].lower()
    rest = url[match.end() :].split("#", 1)[0]
    rest, question, _query = rest.partition("?")
    has_query = bool(question)

    if scheme not in _SPECIAL_SCHEMES:
        if rest.startswith("//"):
            authority, slash, path = rest[2:].partition("/")
            host = authority.rpartition("@")[2]
            return ParsedURL(scheme, host, slash + path, has_query)
        return ParsedURL(scheme, "", rest, has_query)

    rest = rest.replace("\\", "/")
    if scheme == "file":
        if rest.startswith("//"):
            authority, slash, path = rest[2:].partition("/")
            path = slash + path
        else:
            authority, path = "", rest
        file_host = _canonical_host(authority) if authority else ""
        if file_host is None:
            return None
        if file_host == "localhost":
            file_host = ""
        if not path.startswith("/"):
            path = "/" + path
        return ParsedURL(scheme, file_host, _remove_dot_segments(path), has_query)

    authority, slash, path = rest.lstrip("/").partition("/")
    authority = authority.rpartition("@")[2]
    if authority.startswith("["):
        host, _bracket, port = authority.partition("]")
        host += "]"
        port = port[1:] if port.startswith(":") else port
    else:
        host, _colon, port = authority.partition(":")
    if port and (not port.isascii() or not port.isdigit() or int(port) > 65535):
        return None
    canonical = _canonical_host(host) if host else None
    if not canonical:
        return None
    return ParsedURL(scheme, canonical, _remove_dot_segments(slash + path or "/"), has_query)
