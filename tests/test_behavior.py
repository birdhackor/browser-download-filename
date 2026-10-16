"""Headers seen in practice, and the behaviors the documentation promises."""

from __future__ import annotations

import pytest

from browser_download_filename import (
    ContentDisposition,
    parse_content_disposition,
    suggested_filename,
)

URL = "https://example.com/download/file.bin"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        # filename* wins whichever comes first (Express puts the fallback first).
        (
            b"attachment; filename=\"fallback.zip\"; filename*=UTF-8''%E4%B8%AD%E6%96%87.zip",
            "中文.zip",
        ),
        (
            b"attachment; filename*=UTF-8''%E4%B8%AD%E6%96%87.zip; filename=\"fallback.zip\"",
            "中文.zip",
        ),
        # The language tag is ignored, not rejected.
        (b"attachment; filename*=UTF-8'zh-TW'%E4%B8%AD%E6%96%87.zip", "中文.zip"),
        # Raw UTF-8, quoted or not.
        ('attachment; filename="中文.zip"'.encode(), "中文.zip"),
        ("attachment; filename=中文.zip".encode(), "中文.zip"),
        # Semicolons inside quotes, trailing semicolons.
        (b'attachment; filename="a;b;c.txt"', "a;b;c.txt"),
        (b'attachment; filename="a.txt";', "a.txt"),
        (b'attachment; filename="a.txt"; ', "a.txt"),
        # A broken filename* falls back to filename.
        (b"attachment; filename*=UTF-8''%E4%B8%AD%FF.zip; filename=\"good.zip\"", "good.zip"),
        (b"attachment; filename*=x-unknown''abc.zip; filename=\"good.zip\"", "good.zip"),
        # RFC 2047 encoded-words.
        (b'attachment; filename="=?UTF-8?B?5Lit5paHLnppcA==?="', "中文.zip"),
        (b"attachment; filename==?UTF-8?Q?=E4=B8=AD=E6=96=87.zip?=", "中文.zip"),
        # Percent-encoded UTF-8 in a plain filename.
        (b'attachment; filename="%E4%B8%AD%E6%96%87.zip"', "中文.zip"),
        # Other parameters, valid or broken, do not get in the way.
        (b'attachment; size*=12; filename="ok.txt"', "ok.txt"),
        (b'form-data; name="file"; filename="upload.txt"', "upload.txt"),
        # ISO-8859-1 is windows-1252 to Chromium.
        (b"attachment; filename*=ISO-8859-1''foo-%80.html", "foo-\u20ac.html"),
    ],
)
def test_practical_headers(header: bytes, expected: str) -> None:
    assert parse_content_disposition(header).filename == expected


@pytest.mark.parametrize(
    "header",
    [
        # RFC 2231 continuations are not supported by Chromium.
        b'attachment; filename*0="foo."; filename*1="html"',
        # A parameter without a value stops the parsing.
        b'attachment; foo; filename="after.txt"',
        # Quoted ext-values are invalid.
        b"attachment; filename*=\"UTF-8''x.txt\"",
        # Raw bytes that are not UTF-8, without a fallback charset.
        b'attachment; filename="caf\xe9.txt"',
    ],
)
def test_headers_without_usable_filename(header: bytes) -> None:
    assert parse_content_disposition(header).filename is None


def test_unquoted_comma_ends_the_value() -> None:
    # Chromium refuses such a response outright (the two values differ); the
    # parser, like HttpContentDisposition, reads the first value.
    assert parse_content_disposition(b"attachment; filename=Report, Final.pdf").filename == "Report"
    assert parse_content_disposition(b'attachment; filename="Report, Final.pdf"').filename == (
        "Report, Final.pdf"
    )


def test_disposition_types() -> None:
    assert parse_content_disposition("attachment") == ContentDisposition("attachment", None)
    assert parse_content_disposition("INLINE; filename=a.txt") == ContentDisposition(
        "inline", "a.txt"
    )
    assert parse_content_disposition("form-data").is_attachment
    assert not parse_content_disposition("filename=a.txt").is_attachment
    assert parse_content_disposition("attachment, inline").type == "attachment"


def test_filename_is_not_sanitized() -> None:
    parsed = parse_content_disposition(b'attachment; filename="../etc/passwd"')
    assert parsed.filename == "../etc/passwd"
    assert suggested_filename(URL, b'attachment; filename="../etc/passwd"') == "_etc_passwd"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b'attachment; filename="a<b>c:d|e?f*g.txt"', "a_b_c_d_e_f_g.txt"),
        (b'attachment; filename="C:\\\\Windows\\\\evil.exe"', "C__Windows_evil.exe"),
        ('attachment; filename="invoice\u202egpj.exe"'.encode(), "invoice_gpj.exe"),
        ('attachment; filename="name.txt\u00a0"'.encode(), "name.txt_"),
        # Nothing is left after trimming dots: the default name, not the URL.
        (b'attachment; filename="..."', "download"),
        (b'attachment; filename=".htaccess"', "htaccess"),
        (b'attachment; filename="~tilde~"', "_tilde_"),
        # Whitespace in filename becomes a space.
        (b'attachment; filename="a\tb.txt"', "a b.txt"),
        (b'attachment; filename="' + b"a" * 300 + b'.txt"', "a" * 300 + ".txt"),
    ],
)
def test_sanitization(header: bytes, expected: str) -> None:
    assert suggested_filename(URL, header) == expected


@pytest.mark.parametrize(
    ("name", "posix", "windows"),
    [
        ("CON", "CON", "_CON"),
        ("con.txt", "con.txt", "_con.txt"),
        ("x.lnk", "x.lnk", "x.download"),
        ("x.url", "x.url", "x.download"),
        ("evil.exe.", "evil.exe", "evil.exe_"),
        ("config~1.txt", "config~1.txt", "config_1.txt"),
        ("desktop.ini", "desktop.ini", "_desktop.ini"),
    ],
)
def test_platforms(name: str, posix: str, windows: str) -> None:
    header = f'attachment; filename="{name}"'
    assert suggested_filename(URL, header) == posix
    assert suggested_filename(URL, header, platform="windows") == windows


# Chromium's pattern for the characters that rule out an 8.3 short name looks
# as if it held '[', ']' and '\', but ICU parses it without them (see
# _ILLEGAL_IN_SHORT_NAMES), so on Windows the '~' in these names is replaced.
@pytest.mark.parametrize(
    ("name", "posix", "windows"),
    [
        ("ab~[1].txt", "ab~[1].txt", "ab_[1].txt"),
        ("v~2[a]", "v~2[a]", "v_2[a]"),
    ],
)
def test_brackets_do_not_rule_out_a_short_name(name: str, posix: str, windows: str) -> None:
    header = f'attachment; filename="{name}"'
    assert suggested_filename(URL, header) == posix
    assert suggested_filename(URL, header, platform="windows") == windows


def test_backslash_does_not_rule_out_a_short_name() -> None:
    # Only a default name still holds a '\' when the illegal characters are
    # replaced: SanitizeGeneratedFileName has turned every other one into '_'.
    url = "https://example.com/"
    assert suggested_filename(url, default_name="a\\~1") == "a_~1"
    assert suggested_filename(url, default_name="a\\~1", platform="windows") == "a__1"


def test_precedence() -> None:
    header = b'attachment; filename="cd.txt"'
    assert suggested_filename(URL, header, suggested_name="attr.txt") == "cd.txt"
    assert suggested_filename(URL, b"attachment", suggested_name="attr.txt") == "attr.txt"
    assert suggested_filename(URL, b"attachment") == "file.bin"
    assert suggested_filename("https://example.com/", b"attachment") == "download"
    assert suggested_filename("https://example.com/", default_name="untitled") == "untitled"


def test_mime_type_adds_missing_extension() -> None:
    assert suggested_filename("https://example.com/page", mime_type="text/html") == "page.html"
    assert suggested_filename("https://example.com/", mime_type="text/html; charset=utf-8") == (
        "download.html"
    )
    assert suggested_filename("https://example.com/x", mime_type="application/octet-stream") == "x"
    # Not for names that came from Content-Disposition.
    assert (
        suggested_filename(URL, b'attachment; filename="noext"', mime_type="image/png") == "noext"
    )


def test_fallback_charset_for_raw_bytes() -> None:
    header = b'attachment; filename="caf\xe9.txt"'
    assert suggested_filename(URL, header) == "file.bin"
    assert suggested_filename(URL, header, fallback_charset="windows-1252") == "café.txt"
    big5 = b'attachment; filename="' + "中文.txt".encode("big5") + b'"'
    assert suggested_filename(URL, big5, fallback_charset="big5") == "中文.txt"
