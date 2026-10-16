"""Content-Disposition parsing, ported from Chromium's HttpContentDisposition.

Ported from Chromium's net/http/http_content_disposition.cc (BSD-3-Clause,
see THIRD-PARTY-LICENSES). Function names follow the Chromium ones.
"""

from __future__ import annotations

import binascii
import re
from dataclasses import dataclass
from typing import Literal

from ._bytes import (
    header_bytes,
    is_string_utf8,
    is_token,
    native_multibyte_to_text,
    trim_lws,
    unescape_binary_url_component,
)
from ._charset import decode_strict, decode_strict_nfc, decode_substituting, require_charset
from ._http import first_comma_separated_value, parameters

DispositionType = Literal["inline", "attachment"]

_WHITESPACE_SPLIT = re.compile(rb"([ \t\n\r])")
_BASE64 = re.compile(rb"[A-Za-z0-9+/]*={0,2}")


@dataclass(frozen=True, slots=True)
class ContentDisposition:
    """A parsed Content-Disposition header, as Chromium understands it."""

    #: ``"attachment"`` for ``attachment`` and for any other valid
    #: disposition type Chromium does not know; ``"inline"`` for ``inline``, a
    #: missing header, or a header that does not start with a valid type.
    type: DispositionType
    #: The decoded filename, or ``None`` when the header gives none that
    #: Chromium can use. It is not sanitized: it can contain path
    #: separators, control characters and other characters that are unsafe
    #: in a file name.
    filename: str | None

    @property
    def is_attachment(self) -> bool:
        """Whether the type is ``"attachment"``."""
        return self.type == "attachment"


def _decode_q_encoding(data: bytes) -> bytes | None:
    """RFC 2047 "Q" encoding; None if invalid."""
    out = bytearray()
    index = 0
    length = len(data)
    while index < length:
        byte = data[index]
        if byte == 0x5F:  # '_'
            out.append(0x20)
        elif byte == 0x3D:  # '='
            hex_digits = data[index + 1 : index + 3]
            if len(hex_digits) < 2 or not all(
                digit in b"0123456789abcdefABCDEF" for digit in hex_digits
            ):
                return None
            out.append(int(hex_digits, 16))
            index += 2
        elif 0x20 < byte < 0x7F and byte != 0x3F:  # printable, not '?'
            out.append(byte)
        else:
            return None
        index += 1
    return bytes(out)


def _decode_base64_strict(data: bytes) -> bytes | None:
    """base::Base64Decode with the strict policy."""
    if len(data) % 4 or _BASE64.fullmatch(data) is None:
        return None
    try:
        return binascii.a2b_base64(data, strict_mode=True)
    except binascii.Error:
        return None


def _decode_bq_encoding(part: bytes, b_encoding: bool, charset: bytes) -> str | None:
    """DecodeBQEncoding."""
    decoded = _decode_base64_strict(part) if b_encoding else _decode_q_encoding(part)
    if decoded is None:
        return None
    if not decoded:
        return ""
    return decode_substituting(decoded, charset)


def _decode_word(word: bytes, referrer_charset: bytes | None) -> tuple[bool, str, bool]:
    """DecodeWord: (succeeded, text, word was an RFC 2047 encoded-word)."""
    if not word.isascii():
        # Raw 8-bit bytes: UTF-8, else the referrer charset, else the OS
        # multibyte encoding.
        if is_string_utf8(word):
            return True, word.decode("utf-8"), False
        if referrer_charset is not None:
            text = decode_strict(word, referrer_charset)
            if text is not None:
                return True, text, False
        return True, native_multibyte_to_text(word), False

    # RFC 2047: =?charset?<B|Q>?<encoded text>?=, split on '?' with empty
    # pieces skipped the way base::StringTokenizer skips them.
    is_rfc2047 = True
    decoded_word = ""
    charset = b""
    b_encoding = False
    part_index = 0
    for part in word.split(b"?"):
        if not part:
            continue
        if part_index == 0:
            if part != b"=":
                is_rfc2047 = False
                break
        elif part_index == 1:
            charset = part
        elif part_index == 2:
            if part not in (b"b", b"B", b"q", b"Q"):
                is_rfc2047 = False
                break
            b_encoding = part in (b"b", b"B")
        elif part_index == 3:
            text = _decode_bq_encoding(part, b_encoding, charset)
            if text is None:
                return False, "", False
            decoded_word = text
        elif part_index == 4:
            if part != b"=":
                return False, "", False
        else:
            return False, "", False
        part_index += 1

    if is_rfc2047:
        if word.endswith(b"="):
            return True, decoded_word, True
        return False, "", False

    # Not an encoded-word: %-escaped UTF-8, as Internet Explorer 6 and 7 sent.
    unescaped = unescape_binary_url_component(word)
    if is_string_utf8(unescaped):
        return True, unescaped.decode("utf-8"), False
    return False, "", False


def _decode_filename_value(value: bytes, referrer_charset: bytes | None) -> str:
    """DecodeFilenameValue: the filename parameter's value, "" on failure.

    Each whitespace character becomes a space, except right after an RFC 2047
    encoded-word (and before the first word), where it is dropped.
    """
    pieces: list[str] = []
    previous_was_rfc2047 = True
    for index, token in enumerate(_WHITESPACE_SPLIT.split(value)):
        if index % 2:
            if not previous_was_rfc2047:
                pieces.append(" ")
            continue
        if not token:
            continue
        succeeded, text, previous_was_rfc2047 = _decode_word(token, referrer_charset)
        if not succeeded:
            return ""
        pieces.append(text)
    return "".join(pieces)


def _parse_ext_value_components(value: bytes) -> tuple[bytes, bytes] | None:
    """ParseExtValueComponents: charset "'" [ language ] "'" value-chars."""
    pieces = value.split(b"'")
    charset = value_chars = b""
    for delimiters_seen, piece in enumerate(pieces):
        if not piece:
            continue
        if delimiters_seen == 0:
            charset = piece
        elif delimiters_seen == 2:
            value_chars = piece
        elif delimiters_seen > 2:
            return None
    if len(pieces) != 3 or not charset or not value_chars:
        return None
    return charset, value_chars


def _decode_ext_value(raw_value: bytes) -> str:
    """DecodeExtValue: an RFC 8187 ext-value, "" on failure."""
    if b'"' in raw_value:
        return ""
    components = _parse_ext_value_components(raw_value)
    if components is None:
        return ""
    charset, value_chars = components
    if not value_chars.isascii():
        return ""
    text = decode_strict_nfc(unescape_binary_url_component(value_chars), charset)
    return text or ""


def _parse(header: bytes, referrer_charset: bytes | None) -> ContentDisposition:
    """HttpContentDisposition::ConsumeDispositionType followed by Parse."""
    disposition: DispositionType = "inline"
    delimiter = header.find(b";")
    disposition_type = trim_lws(header if delimiter < 0 else header[:delimiter])
    if is_token(disposition_type):
        # "inline" stays inline; "attachment" and unknown types download.
        if disposition_type.lower() != b"inline":
            disposition = "attachment"
        params = b"" if delimiter < 0 else header[delimiter + 1 :]
    else:
        # Not a disposition type: Chromium reads the header as parameters.
        params = header

    filename = ""
    ext_filename = ""
    for name, value, raw_value in parameters(params):
        lowered = name.lower()
        if not filename and lowered == b"filename":
            filename = _decode_filename_value(value, referrer_charset)
        elif not ext_filename and lowered == b"filename*":
            ext_filename = _decode_ext_value(raw_value)
    return ContentDisposition(disposition, ext_filename or filename or None)


def parse_content_disposition(
    value: str | bytes | None,
    *,
    fallback_charset: str | None = None,
) -> ContentDisposition:
    """Parse a Content-Disposition header value exactly as Chromium does.

    ``value`` is the header value as bytes, or as the str an HTTP library
    produced; ``None`` stands for a missing header. Malformed headers never
    raise: Chromium's interpretation of them is returned instead.

    ``fallback_charset`` names the charset tried for raw non-UTF-8 bytes in
    ``filename``, before giving up on them; Chrome passes the browser's
    default text encoding here. It must be a label Chromium knows, such as
    ``"windows-1252"`` or ``"big5"``, otherwise LookupError is raised.
    """
    referrer_charset = require_charset(fallback_charset)
    if value is None:
        return ContentDisposition("inline", None)
    return _parse(first_comma_separated_value(header_bytes(value)), referrer_charset)
