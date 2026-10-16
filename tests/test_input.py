"""How header values reach the parser, and argument validation."""

from __future__ import annotations

from typing import NoReturn

import pytest

from browser_download_filename import (
    _filename,
    parse_content_disposition,
    sanitize_filename,
    suggested_filename,
)
from browser_download_filename._bytes import header_bytes

RAW_UTF8 = 'attachment; filename="中文.zip"'.encode()
RAW_UTF8_LATIN_RANGE = 'attachment; filename="café.txt"'.encode()


def test_bytes_are_used_as_is() -> None:
    assert header_bytes(RAW_UTF8) == RAW_UTF8


def test_latin1_decoded_str_from_requests() -> None:
    # http.client, urllib3, requests and WSGI decode header bytes as Latin-1.
    as_requests_gives_it = RAW_UTF8.decode("latin-1")
    assert header_bytes(as_requests_gives_it) == RAW_UTF8
    assert parse_content_disposition(as_requests_gives_it).filename == "中文.zip"
    assert parse_content_disposition(RAW_UTF8_LATIN_RANGE.decode("latin-1")).filename == "café.txt"


def test_utf8_decoded_str_from_httpx() -> None:
    assert parse_content_disposition(RAW_UTF8.decode("utf-8")).filename == "中文.zip"
    # All characters fit Latin-1, but those Latin-1 bytes are not UTF-8, so
    # the str is taken as text.
    assert parse_content_disposition(RAW_UTF8_LATIN_RANGE.decode("utf-8")).filename == "café.txt"


def test_surrogateescape_str_from_aiohttp() -> None:
    raw_latin1 = b'attachment; filename="caf\xe9.txt"'
    as_aiohttp_gives_it = raw_latin1.decode("utf-8", "surrogateescape")
    assert header_bytes(as_aiohttp_gives_it) == raw_latin1
    # Not UTF-8, and no fallback charset: Chromium on Linux drops the name.
    assert parse_content_disposition(as_aiohttp_gives_it).filename is None
    parsed = parse_content_disposition(as_aiohttp_gives_it, fallback_charset="windows-1252")
    assert parsed.filename == "café.txt"


def test_lone_surrogate_does_not_raise() -> None:
    assert parse_content_disposition('attachment; filename="\ud800.txt"').filename is None
    assert suggested_filename(url="https://example.com/\ud800.txt") == "\ufffd.txt"


def test_ascii_str_is_unchanged() -> None:
    assert header_bytes("attachment") == b"attachment"


def test_none_is_a_missing_header() -> None:
    parsed = parse_content_disposition(None)
    assert parsed.type == "inline"
    assert parsed.filename is None
    assert (
        suggested_filename(url="https://example.com/report.pdf", content_disposition=None)
        == "report.pdf"
    )


def test_unknown_fallback_charset_raises() -> None:
    with pytest.raises(LookupError, match="utf-7"):
        parse_content_disposition("attachment", fallback_charset="utf-7")
    with pytest.raises(LookupError):
        suggested_filename(url="https://example.com/", fallback_charset="cp932")
    with pytest.raises(LookupError):
        parse_content_disposition("attachment", fallback_charset="iso-2022-kr")


def test_fallback_charset_must_be_str() -> None:
    with pytest.raises(TypeError):
        parse_content_disposition("attachment", fallback_charset=b"utf-8")  # type: ignore[arg-type]


def test_bytes_like_headers_are_accepted() -> None:
    header = b"attachment; filename=a.txt"
    assert parse_content_disposition(bytearray(header)).filename == "a.txt"  # type: ignore[arg-type]
    assert parse_content_disposition(memoryview(header)).filename == "a.txt"  # type: ignore[arg-type]
    assert suggested_filename(content_disposition=bytearray(header)) == "a.txt"  # type: ignore[arg-type]
    page = "https://example.com/page"
    assert suggested_filename(url=page, content_type=bytearray(b"text/html")) == "page.html"  # type: ignore[arg-type]
    assert suggested_filename(url=page, content_type=memoryview(b"text/html")) == "page.html"  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [5, 0, ["attachment"]])
def test_other_header_types_raise(value: object) -> None:
    # bytes(5) would be five NUL bytes, which would silently parse as no header.
    with pytest.raises(TypeError, match="header value"):
        parse_content_disposition(value)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="header value"):
        suggested_filename(content_disposition=value)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="content_type"):
        suggested_filename(content_type=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["url", "download_attribute", "default_name"])
def test_str_arguments_are_checked(name: str) -> None:
    arguments: dict[str, object] = {"url": "https://example.com/", name: b"x"}
    with pytest.raises(TypeError, match=name):
        suggested_filename(**arguments)  # type: ignore[arg-type]


def test_sanitize_filename_arguments_are_checked() -> None:
    with pytest.raises(TypeError, match=r"^name "):
        sanitize_filename(b"x")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="default_name"):
        sanitize_filename("x", default_name=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="default_name") as raised:
        sanitize_filename("x", default_name="")
    # None is no way out here, unlike in suggested_filename.
    assert "None" not in str(raised.value)


def test_empty_default_name_asks_for_none() -> None:
    with pytest.raises(ValueError, match="default_name=None"):
        suggested_filename(url="https://example.com/", default_name="")


def test_platform_is_validated() -> None:
    with pytest.raises(ValueError, match="platform"):
        suggested_filename(url="https://example.com/", platform="linux")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="platform"):
        sanitize_filename("x", platform="linux")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ({"default_name": ""}, ValueError),
        ({"platform": "linux"}, ValueError),
        ({"content_type": 5}, TypeError),
        ({"download_attribute": b"x"}, TypeError),
        ({"default_name": b"x"}, TypeError),
        ({"fallback_charset": "utf-7"}, LookupError),
    ],
)
def test_caller_errors_come_before_parsing(
    monkeypatch: pytest.MonkeyPatch, arguments: dict[str, object], error: type[Exception]
) -> None:
    def parse(*args: object) -> NoReturn:
        raise AssertionError("parsed before the arguments were checked")

    monkeypatch.setattr(_filename, "_parse", parse)
    monkeypatch.setattr(_filename, "parse_url", parse)
    with pytest.raises(error):
        suggested_filename(
            url="https://example.com/a.txt",
            content_disposition="attachment; filename=a.txt",
            **arguments,  # type: ignore[arg-type]
        )


def test_keyword_only_arguments() -> None:
    with pytest.raises(TypeError):
        parse_content_disposition("attachment", "utf-8")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        suggested_filename("https://example.com/a.pdf")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        sanitize_filename("a.txt", "untitled")  # type: ignore[call-arg]


def test_fallback_charset_applies_to_url() -> None:
    url = "https://example.com/caf%E9.txt"
    assert suggested_filename(url=url) == "download"
    assert suggested_filename(url=url, fallback_charset="windows-1252") == "café.txt"
    big5_url = "https://example.com/%A4%A4%A4%E5.txt"
    assert suggested_filename(url=big5_url, fallback_charset="big5") == "中文.txt"
