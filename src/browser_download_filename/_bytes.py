"""Byte-string helpers with Chromium's semantics.

Ported from Chromium's base/strings and net/http/http_util.cc (BSD-3-Clause,
see THIRD-PARTY-LICENSES).
"""

from __future__ import annotations

import re

# Unicode noncharacters: U+FDD0..U+FDEF and the last two code points of every
# plane. base::IsStringUTF8 rejects them.
_NONCHARACTER = re.compile(
    "[\ufdd0-\ufdef"
    + "".join(
        f"{chr(plane + 0xFFFE)}{chr(plane + 0xFFFF)}" for plane in range(0, 0x110000, 0x10000)
    )
    + "]"
)
_PERCENT_ESCAPE = re.compile(rb"%([0-9A-Fa-f]{2})")
_TOKEN = re.compile(rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")


def is_string_utf8(data: bytes) -> bool:
    """base::IsStringUTF8: well-formed UTF-8 that contains no noncharacter."""
    if data.isascii():
        return True
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return _NONCHARACTER.search(text) is None


def native_multibyte_to_text(data: bytes) -> str:
    """base::SysNativeMBToWide on Linux with a UTF-8 locale.

    Chromium falls back to the operating system's multibyte encoding for bytes
    that are neither UTF-8 nor in the referrer charset. On Linux that is UTF-8,
    and anything that does not decode yields an empty string.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def unescape_binary_url_component(data: bytes) -> bytes:
    """base::UnescapeBinaryURLComponent with UnescapeRule::NORMAL.

    Every well-formed %XX escape becomes the byte it names; anything else,
    including a stray '%', is kept as is.
    """
    if b"%" not in data:
        return data
    return _PERCENT_ESCAPE.sub(lambda match: bytes((int(match[1], 16),)), data)


def trim_lws(data: bytes) -> bytes:
    """HttpUtil::TrimLWS: strip spaces and horizontal tabs from both ends."""
    return data.strip(b" \t")


def is_token(data: bytes) -> bool:
    """HttpUtil::IsToken (RFC 7230 token)."""
    return _TOKEN.fullmatch(data) is not None


def header_bytes(value: str | bytes) -> bytes:
    """The bytes a header value had on the wire.

    Chromium parses raw header bytes. A str is mapped back to bytes like this:
    if every character is in U+0000-U+00FF and the Latin-1 encoding is valid
    UTF-8, those Latin-1 bytes are used; that is how http.client, urllib3,
    requests and WSGI hand over a header that carried UTF-8. Any other str is
    treated as text and encoded as UTF-8, with surrogate escapes (aiohttp)
    turned back into the bytes they stand for.
    """
    if not isinstance(value, str):
        # bytes() would also take an int and make that many NUL bytes.
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError(
                f"a header value must be str, bytes or None, not {type(value).__name__}"
            )
        return bytes(value)
    try:
        latin1 = value.encode("latin-1")
    except UnicodeEncodeError:
        pass
    else:
        if latin1.isascii():
            return latin1
        try:
            latin1.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return latin1
    try:
        return value.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        # A lone surrogate outside U+DC80-U+DCFF stands for no byte; keep it
        # as an ill-formed sequence so that the UTF-8 checks reject it.
        return value.encode("utf-8", "surrogatepass")
