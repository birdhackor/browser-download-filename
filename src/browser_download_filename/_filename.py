"""Filename generation, ported from Chromium's net::GetSuggestedFilename.

Ported from Chromium's net/base/filename_util*.cc, base/i18n/file_util_icu.cc,
base/files/file_path.cc, base/files/file_util.cc and net/base/mime_util.cc
(BSD-3-Clause, see THIRD-PARTY-LICENSES). Function names follow the Chromium
ones.
"""

from __future__ import annotations

import re
import sys
from typing import Literal

from ._bytes import (
    is_string_utf8,
    native_multibyte_to_text,
    require_headers_encoding,
    unescape_binary_url_component,
)
from ._charset import decode_strict, require_charset
from ._content_disposition import _parse
from ._data import FORMAT_RANGES, MIME_PRIMARY_MAPPINGS, MIME_SECONDARY_MAPPINGS
from ._headers import (
    CONTENT_DISPOSITION,
    CONTENT_TYPE,
    HEADERS_SHAPE,
    X_CONTENT_TYPE_OPTIONS,
    HeadersLike,
    header_lines,
    header_values,
    line_value,
)
from ._http import first_comma_separated_value
from ._mime import download_mime_type
from ._url import ParsedURL, parse_url

Platform = Literal["posix", "windows"]

_FINAL_FALLBACK_NAME = "download"

# Unicode White_Space, which ICU's [:WSpace:] matches.
_WHITE_SPACE = "\t\n\x0b\x0c\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
# base::TrimWhitespace's set on Windows (kWhitespaceWide) is the same list.
_WINDOWS_TRIM_WHITESPACE = _WHITE_SPACE


def _char_class(ranges: list[tuple[int, int]]) -> str:
    return "".join(f"\\U{start:08X}-\\U{end:08X}" for start, end in ranges)


# IllegalCharacters in file_util_icu.cc: [["*/:<>?\\|][:Cc:][:Cf:]] plus the
# noncharacters.
_ILLEGAL_ANYWHERE = re.compile(
    "["
    + re.escape('"*/:<>?\\|')
    + _char_class(
        [
            (0x00, 0x1F),
            (0x7F, 0x9F),
            *FORMAT_RANGES,
            (0xFDD0, 0xFDEF),
            *((plane + 0xFFFE, plane + 0xFFFF) for plane in range(0, 0x110000, 0x10000)),
        ]
    )
    + "]"
)
# [[:WSpace:][.~]]: not allowed as the first or last character.
_ILLEGAL_AT_ENDS = frozenset(_WHITE_SPACE + ".~")
# Windows 8.3 short names: these characters rule a short name out. Chromium
# writes the set as [[:WSpace:]["\/[]:+|<>=;?,*]], which looks as if it held
# '\', '[' and ']', but ICU does not parse it that way: "\/" is an escaped '/',
# and an unescaped '[' inside a set starts a nested set, which the ']' right
# after it closes, so "[]" adds nothing.
_ILLEGAL_IN_SHORT_NAMES = frozenset(_WHITE_SPACE + '"/:+|<>=;?,*')

_LONE_SURROGATE = re.compile("[\ud800-\udfff]")

_DOUBLE_EXTENSION_SUFFIXES = frozenset({"bz", "bz2", "gz", "lz", "lzma", "lzo", "xz", "z", "zst"})
_DOUBLE_EXTENSIONS = frozenset({"user.js"})
_SHELL_INTEGRATED_EXTENSIONS = frozenset({"local", "lnk", "scf", "url"})
_WINDOWS_DEVICES = (
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
    "clock$",
)  # fmt: skip
_WINDOWS_MAGIC_NAMES = frozenset({"desktop.ini", "thumbs.db", "conin$", "conout$"})
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _ascii_lower(text: str) -> str:
    return text.translate(_ASCII_LOWER)


def _scalar_values(text: str) -> str:
    """Replace lone surrogates, which a byte string could not hold."""
    return _LONE_SURROGATE.sub("�", text)


def _utf16_length(text: str) -> int:
    return len(text) + sum(1 for char in text if ord(char) > 0xFFFF)


# --- base::FilePath on a base name ------------------------------------------


def _final_extension_separator(name: str) -> int:
    if name in (".", ".."):
        return -1
    return name.rfind(".")


def _extension_separator(name: str) -> int:
    last_dot = _final_extension_separator(name)
    if last_dot <= 0:
        return last_dot
    penultimate_dot = name.rfind(".", 0, last_dot)
    if penultimate_dot == -1:
        return last_dot
    if _ascii_lower(name[penultimate_dot + 1 :]) in _DOUBLE_EXTENSIONS:
        return penultimate_dot
    if (
        _ascii_lower(name[last_dot + 1 :]) in _DOUBLE_EXTENSION_SUFFIXES
        and 1 < last_dot - penultimate_dot <= 5
    ):
        return penultimate_dot
    return last_dot


def _extension(name: str) -> str:
    """FilePath::Extension, without the leading dot."""
    dot = _extension_separator(name)
    return "" if dot < 0 else name[dot + 1 :]


def _final_extension(name: str) -> str:
    """FilePath::FinalExtension, without the leading dot."""
    dot = _final_extension_separator(name)
    return "" if dot < 0 else name[dot + 1 :]


def _replace_extension(name: str, extension: str) -> str:
    """FilePath::ReplaceExtension."""
    if name in ("", ".", ".."):
        return ""
    dot = _extension_separator(name)
    no_extension = name if dot < 0 else name[:dot]
    if extension in ("", "."):
        return no_extension
    return no_extension + ("" if extension.startswith(".") else ".") + extension


# --- net/base/mime_util.cc ---------------------------------------------------


def _preferred_extension_for_mime_type(mime_type: str) -> str | None:
    """GetPreferredExtensionForMimeType, without the platform MIME database."""
    if mime_type == "application/octet-stream":
        return None
    for mappings in (MIME_PRIMARY_MAPPINGS, MIME_SECONDARY_MAPPINGS):
        for candidate, extensions in mappings:
            if candidate == mime_type:
                return extensions[0]
    return None


def _extensions_for_mime_type(mime_type: str) -> set[str]:
    """GetExtensionsForMimeType, without the platform MIME database."""
    return {
        extension
        for mappings in (MIME_PRIMARY_MAPPINGS, MIME_SECONDARY_MAPPINGS)
        for candidate, extensions in mappings
        if candidate == mime_type
        for extension in extensions
    }


# --- net/base/filename_util_internal.cc ---------------------------------------


def _corrected_extension(mime_type: str, ignore_extension: bool, name: str) -> str:
    """GetCorrectedExtensionUnsafe."""
    extension = _extension(name)
    if not mime_type:
        return extension
    if extension and not ignore_extension:
        return extension
    preferred = _preferred_extension_for_mime_type(mime_type)
    if preferred is None:
        return extension
    all_extensions = _extensions_for_mime_type(mime_type)
    if extension in all_extensions:
        return extension
    # Keep "foo.tar.gz" rather than renaming it to "foo.gz".
    if _final_extension(name) in all_extensions:
        return extension
    return preferred


def _is_shell_integrated_extension(extension: str) -> bool:
    lowered = _ascii_lower(extension)
    return lowered in _SHELL_INTEGRATED_EXTENSIONS or (
        lowered.startswith("{") and lowered.endswith("}")
    )


def _is_reserved_name_on_windows(name: str) -> bool:
    """base::IsReservedNameOnWindows."""
    trimmed = _ascii_lower(name).rstrip(" .")
    prefix = trimmed.split(".", 1)[0]
    return (
        any(trimmed == device or prefix == device for device in _WINDOWS_DEVICES)
        or trimmed in _WINDOWS_MAGIC_NAMES
    )


def _generate_safe_file_name(
    mime_type: str, ignore_extension: bool, name: str, windows: bool
) -> str:
    """GenerateSafeFileName, with EnsureSafeExtension inlined."""
    extension = _corrected_extension(mime_type, ignore_extension, name)
    if windows and _is_shell_integrated_extension(extension):
        extension = "download"
    name = _replace_extension(name, extension)
    if windows and _is_reserved_name_on_windows(name):
        name = "_" + name
    return name


def _sanitize_generated_file_name(name: str, replace_trailing: bool) -> str:
    """SanitizeGeneratedFileName."""
    if not name:
        return name
    if replace_trailing:
        # CreateFile() strips trailing dots and spaces, so Windows turns them
        # into underscores instead.
        length = len(name)
        name = name.rstrip(" .").rstrip(_WINDOWS_TRIM_WHITESPACE)
        if not name:
            return name
        name += "_" * (length - len(name))
    name = name.strip(".")
    if not name:
        return name
    return name.replace("/", "_").replace("\\", "_")


def _has_valid_dot_position_for_short_name(name: str) -> bool:
    first_dot = name.find(".")
    if first_dot == -1:
        return _utf16_length(name) <= 8
    if first_dot != name.rfind("."):
        return False
    first_dot = _utf16_length(name[:first_dot])
    return 0 < first_dot <= 8 and first_dot + 4 >= _utf16_length(name)


def _replace_illegal_characters(name: str, windows: bool, replace_char: str = "_") -> str:
    """base::i18n::ReplaceIllegalCharactersInPath.

    Chromium's filename generation always replaces with '_'; other
    replacement characters are only exercised by the ported unit tests.
    """
    replace_char_illegal_at_ends = replace_char in _ILLEGAL_AT_ENDS
    # On Windows, '~' is also replaced if the name could be an 8.3 short name.
    could_be_short_name = (
        windows
        and _utf16_length(name) <= 12
        and _has_valid_dot_position_for_short_name(name)
        and not any(char in _ILLEGAL_IN_SHORT_NAMES for char in name)
    )
    last = len(name) - 1
    chars = list(name)
    # The first and last characters that are kept and allowed at the ends,
    # and the last '.', as code point indexes; -1 if none.
    legal_begin = legal_end = last_dot = -1
    for index, char in enumerate(chars):
        illegal_at_ends = char in _ILLEGAL_AT_ENDS
        if (
            _ILLEGAL_ANYWHERE.match(char)
            or (could_be_short_name and char == "~")
            or (
                (index == 0 or index == last)
                and illegal_at_ends
                and not replace_char_illegal_at_ends
            )
        ):
            chars[index] = replace_char
        elif not illegal_at_ends:
            if legal_begin == -1:
                legal_begin = index
            legal_end = index + 1
        if char == ".":
            last_dot = index
    result = "".join(chars)
    if not replace_char_illegal_at_ends:
        return result
    # The replacement may not start or end the name either: trim what is
    # illegal at the ends, keeping a leading extension separator as "_.ext".
    if legal_begin == -1:
        return "_" + result + "_"
    result = result[:legal_end]
    if last_dot != -1 and last_dot == legal_begin - 1:
        return "_" + result[last_dot:]
    return result[legal_begin:]


def _file_name_from_url(url: ParsedURL | None, referrer_charset: bytes | None) -> tuple[str, bool]:
    """GetFileNameFromURL: (name, whether its extension may be replaced)."""
    if url is None or url.scheme in ("about", "data"):
        return "", False
    unescaped = unescape_binary_url_component(url.extract_file_name().encode("utf-8"))
    decoded: str | None = None
    if is_string_utf8(unescaped):
        decoded = unescaped.decode("utf-8")
    else:
        if referrer_charset is not None:
            decoded = decode_strict(unescaped, referrer_charset)
        if decoded is None:
            decoded = native_multibyte_to_text(unescaped)
    # A URL with a query is assumed to be a generator, so the extension the
    # path suggests is not trusted.
    return decoded, bool(decoded) and url.has_query


def _uses_windows_rules(platform: Platform | None) -> bool:
    """Whether Chromium's Windows rules apply; None follows the running system."""
    if platform is None:
        return sys.platform == "win32"
    if platform not in ("posix", "windows"):
        raise ValueError(f"platform must be 'posix', 'windows' or None, not {platform!r}")
    return platform == "windows"


def _content_type_line(content_type: object, encoding: str | None) -> bytes | None:
    """The ``content_type`` argument as the value of a Content-Type line."""
    if content_type is None:
        return None
    if not isinstance(content_type, (str, bytes, bytearray, memoryview)):
        raise TypeError(
            f"content_type must be str, bytes or None, not {type(content_type).__name__}"
        )
    return line_value(content_type, encoding).value


def suggested_filename(
    headers: HeadersLike | None = None,
    *,
    url: str | None = None,
    content_disposition: str | bytes | None = None,
    content_type: str | bytes | None = None,
    download_attribute: str | None = None,
    default_name: str | None = "download",
    fallback_charset: str | None = None,
    headers_encoding: str | None = None,
    platform: Platform | None = None,
) -> str:
    """The filename Chromium suggests for a download. Never empty.

    This is net::GetSuggestedFilename, the name Chrome reports to DevTools
    (and Playwright) when a download starts, except in the cases that the
    documentation lists under "Limits of the port". It is the
    Content-Disposition filename, else ``download_attribute`` (an
    ``<a download>`` value), else the last segment of the URL path, else
    ``default_name`` (or, if that is None, the URL's host and then
    ``"download"``), then sanitized for use as a file name. A name that did
    not come from Content-Disposition can also get its extension from the
    response's MIME type.

    ``headers`` are the response's headers, as a mapping or an iterable of
    (name, value) pairs, each value read as Chromium reads the rest of its
    header line, line breaks included (see :func:`parse_content_disposition`).
    Content-Disposition is read from them as the first comma-separated value
    of its first line. The MIME type comes from their
    Content-Type lines, read the way Chromium's network stack reads them,
    and from X-Content-Type-Options, which tells with the type whether Chrome
    sniffs the body for another one; the package has no body, so where
    Chrome sniffs it keeps the declared type. ``content_disposition`` and
    ``content_type``, if they are not None, take the place of every
    Content-Disposition or Content-Type line in ``headers``, even if they
    are empty: an empty ``content_type`` is an empty Content-Type. With
    neither ``headers`` nor ``content_type``, no MIME type is used. ``url``
    is the final URL of the response, after redirects. ``fallback_charset``
    and ``headers_encoding`` are as in :func:`parse_content_disposition`;
    ``fallback_charset`` also applies to %-escaped non-UTF-8 bytes in the
    URL. ``platform`` chooses Chromium's rules for Linux, macOS and other
    POSIX systems (``"posix"``) or for Windows (``"windows"``), which also
    handles reserved device names, trailing dots and spaces, and
    shell-integrated extensions; None picks the rules of the system the call
    runs on.
    """
    referrer_charset = require_charset(fallback_charset)
    encoding = require_headers_encoding(headers_encoding)
    windows = _uses_windows_rules(platform)
    for name, value in (("url", url), ("download_attribute", download_attribute)):
        if value is not None and not isinstance(value, str):
            raise TypeError(f"{name} must be str or None, not {type(value).__name__}")
    content_type_line = _content_type_line(content_type, encoding)
    if default_name is None:
        # Chromium's empty default name: the URL's host, then "download".
        default_name = ""
    elif not isinstance(default_name, str):
        raise TypeError(f"default_name must be str or None, not {type(default_name).__name__}")
    elif not default_name:
        raise ValueError("default_name is empty; pass default_name=None to use the URL's host")
    lines: list[tuple[bytes, bytes]] = []
    if headers is not None:
        accepted = HEADERS_SHAPE + " or None"
        lines = header_lines(headers, encoding, argument="headers", accepted=accepted).lines
    if content_disposition is not None:
        disposition_lines = [line_value(content_disposition, encoding).value]
    else:
        disposition_lines = header_values(lines, CONTENT_DISPOSITION)
    parsed_url = parse_url(_scalar_values(url) if url else None)
    mime_type = ""
    if headers is not None or content_type_line is not None:
        if content_type_line is not None:
            content_type_lines = [content_type_line]
        else:
            content_type_lines = header_values(lines, CONTENT_TYPE)
        options_lines = header_values(lines, X_CONTENT_TYPE_OPTIONS)
        mime_type = download_mime_type(content_type_lines, options_lines, parsed_url)
    return _get_suggested_filename(
        parsed_url,
        # The download code reads the first line.
        disposition_lines[0] if disposition_lines else b"",
        referrer_charset,
        download_attribute or "",
        mime_type,
        default_name,
        windows=windows,
    )


def sanitize_filename(
    name: str,
    *,
    default_name: str = "download",
    platform: Platform | None = None,
) -> str:
    """Clean any name, such as a page title, into a file name as Chrome does.

    ``name`` is cleaned as Chrome cleans an ``<a download>`` value: the result
    is what :func:`suggested_filename` returns for ``download_attribute=name``.
    It is never empty: ``default_name``, which cannot be empty, is used where
    :func:`suggested_filename` would use its default name. ``platform`` is as
    in :func:`suggested_filename`.
    """
    if not isinstance(name, str):
        raise TypeError(f"name must be str, not {type(name).__name__}")
    if not isinstance(default_name, str):
        raise TypeError(f"default_name must be str, not {type(default_name).__name__}")
    if not default_name:
        raise ValueError("default_name cannot be empty")
    return suggested_filename(download_attribute=name, default_name=default_name, platform=platform)


def _get_suggested_filename(
    url: ParsedURL | None,
    content_disposition: bytes,
    referrer_charset: bytes | None,
    suggested_name: str,
    mime_type: str,
    default_name: str,
    *,
    windows: bool,
) -> str:
    """net::GetSuggestedFilename, with the arguments Chromium passes it.

    As in Chromium, an empty argument stands for none; ``url`` is the parsed
    URL, None for none. ``mime_type`` is used as it is:
    GetPreferredExtensionForMimeType looks it up exactly, so a type in
    capitals or with parameters gets no extension. suggested_filename works
    it out from the response's headers first (see _mime).
    """
    content_disposition_filename = None
    if content_disposition:
        # HttpContentDisposition reads the first comma-separated value.
        header = first_comma_separated_value(content_disposition)
        content_disposition_filename = _parse(header, referrer_charset).filename
    return _generate(
        url,
        content_disposition_filename,
        suggested_name=suggested_name,
        mime_type=mime_type,
        default_name=default_name,
        referrer_charset=referrer_charset,
        windows=windows,
    )


def _generate(
    parsed_url: ParsedURL | None,
    content_disposition_filename: str | None,
    *,
    suggested_name: str,
    mime_type: str,
    default_name: str,
    referrer_charset: bytes | None,
    windows: bool,
) -> str:
    """GetSuggestedFilenameImpl, given the Content-Disposition filename."""
    default_name = _scalar_values(default_name)
    filename = content_disposition_filename or ""
    from_content_disposition = bool(filename)
    overwrite_extension = False
    if not filename and suggested_name:
        filename = _scalar_values(suggested_name)
    if not filename:
        filename, overwrite_extension = _file_name_from_url(parsed_url, referrer_charset)
    if not filename and not default_name and parsed_url is not None and parsed_url.host:
        filename = parsed_url.host

    result = _sanitize_generated_file_name(filename, replace_trailing=windows)
    if not result.strip("-_"):
        result = default_name or _FINAL_FALLBACK_NAME
        overwrite_extension = False
    result = _replace_illegal_characters(result, windows)
    if from_content_disposition:
        # A Content-Disposition name gets no extension it did not ask for.
        result = _generate_safe_file_name("", False, result, windows)
    else:
        result = _generate_safe_file_name(mime_type, overwrite_extension, result, windows)
    return result or default_name or _FINAL_FALLBACK_NAME
