"""Content-Disposition parsing, ported from Chromium's HttpContentDisposition.

Ported from Chromium's net/http/http_content_disposition.cc, and for repeated
headers net/http/http_util.cc (BSD-3-Clause, see THIRD-PARTY-LICENSES).
Function names follow the Chromium ones.
"""

from __future__ import annotations

import binascii
import re
from dataclasses import dataclass
from typing import Literal

from ._bytes import (
    is_string_utf8,
    is_token,
    native_multibyte_to_text,
    require_headers_encoding,
    trim_lws,
    unescape_binary_url_component,
)
from ._charset import decode_strict, decode_strict_nfc, decode_substituting, require_charset
from ._headers import (
    CONTENT_DISPOSITION,
    HEADERS_SHAPE,
    HeadersLike,
    header_lines,
    header_values,
    line_value,
)
from ._http import comma_separated_values, parameters

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
    #: Whether Chromium refuses the whole response for one of two reasons:
    #: some value of the Content-Disposition lines, split on commas outside
    #: quotes, differs from the first one
    #: (ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION), or a header line
    #: holds a NUL (ERR_INVALID_HTTP_RESPONSE). Chromium refuses responses for
    #: other reasons too, which this does not tell. ``type`` and ``filename``
    #: still come from the first value.
    blocks_download: bool = False

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


def _from_lines(
    lines: list[bytes], referrer_charset: bytes | None, *, has_nul: bool
) -> ContentDisposition:
    """The Content-Disposition of a response with these header lines.

    HttpResponseHeaders splits each line into its comma-separated values,
    empty ones included, and the download code parses the first value
    (EnumerateHeader). The network stack refuses the response when
    HttpUtil::HeadersContainMultipleCopiesOfField finds another value that
    differs from that one, and also, before it reads any header, when a
    header line holds a NUL, which ``has_nul`` tells.
    """
    values = [value for line in lines for value in comma_separated_values(line)]
    if not values:
        return ContentDisposition("inline", None, has_nul)
    first = values[0]
    parsed = _parse(first, referrer_charset)
    return ContentDisposition(
        parsed.type, parsed.filename, has_nul or any(value != first for value in values)
    )


def parse_content_disposition(
    value: str | bytes | HeadersLike | None,
    /,
    *,
    fallback_charset: str | None = None,
    headers_encoding: str | None = None,
) -> ContentDisposition:
    """Parse Content-Disposition exactly as Chromium does.

    ``value`` is one header value, as bytes or as the str an HTTP library
    produced, or a response's headers, as a mapping or an iterable of
    (name, value) pairs, of which every Content-Disposition line is read;
    ``None`` stands for a missing header. Each value is read as the rest of
    its header line was sent, the way Chromium reads it: a blank line ends
    it, and at a line break, a next line that starts with a space or a tab
    is folded into it, and any other ends it. The type and the filename come
    from the first comma-separated value, which is the one Chrome's download
    code reads, and ``blocks_download`` tells whether Chrome refuses the
    response for one of two reasons: another value differs from it, or a
    header holds a NUL. Malformed headers never raise: Chromium's
    interpretation of them is returned instead.

    ``fallback_charset`` names the charset tried for raw non-UTF-8 bytes in
    ``filename``, before giving up on them; Chrome passes the browser's
    default text encoding here. It must be a label Chromium knows, such as
    ``"windows-1252"`` or ``"big5"``, otherwise LookupError is raised.

    ``headers_encoding`` is the Python codec the HTTP library decoded the
    headers with, such as ``"latin-1"``; every str header value is encoded
    back with it, and ValueError is raised if one does not encode. Without
    it, a str whose characters are all Latin-1 and whose Latin-1 bytes are
    valid UTF-8 is read as those bytes, and any other str as UTF-8 text.
    """
    referrer_charset = require_charset(fallback_charset)
    encoding = require_headers_encoding(headers_encoding)
    if value is None:
        return _from_lines([], referrer_charset, has_nul=False)
    if isinstance(value, (str, bytes, bytearray, memoryview)):
        line = line_value(value, encoding)
        return _from_lines([line.value], referrer_charset, has_nul=line.has_nul)
    headers = header_lines(
        value, encoding, argument="value", accepted="str, bytes, None, " + HEADERS_SHAPE
    )
    lines = header_values(headers.lines, CONTENT_DISPOSITION)
    return _from_lines(lines, referrer_charset, has_nul=headers.has_nul)
