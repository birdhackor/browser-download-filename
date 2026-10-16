"""How header values reach the parser, and argument validation."""

from __future__ import annotations

from typing import NoReturn

import pytest

from browser_download_filename import (
    _content_disposition,
    _filename,
    parse_content_disposition,
    sanitize_filename,
    suggested_filename,
)
from browser_download_filename._bytes import header_bytes

RAW_UTF8 = 'attachment; filename="中文.zip"'.encode()
RAW_UTF8_LATIN_RANGE = 'attachment; filename="café.txt"'.encode()
RAW_BIG5 = b'attachment; filename="' + "中文.txt".encode("big5") + b'"'
URL = "https://example.com/files/from-url.bin"


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
    assert parse_content_disposition(memoryview(header)).filename == "a.txt"
    assert suggested_filename(content_disposition=bytearray(header)) == "a.txt"  # type: ignore[arg-type]
    page = "https://example.com/page"
    assert suggested_filename(url=page, content_type=bytearray(b"text/html")) == "page.html"  # type: ignore[arg-type]
    assert suggested_filename(url=page, content_type=memoryview(b"text/html")) == "page.html"  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [5, 0, ["attachment"]])
def test_other_header_types_raise(value: object) -> None:
    # bytes(5) would be five NUL bytes, which would silently parse as no header.
    with pytest.raises(TypeError, match="header value"):
        suggested_filename(content_disposition=value)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="content_type"):
        suggested_filename(content_type=value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (5, "value must be str, bytes, None, a mapping"),
        (0, "value must be str, bytes, None, a mapping"),
        # Not one header but headers, holding a str where a pair should be.
        (["attachment"], r"\(name, value\) pair, not str"),
    ],
)
def test_other_types_are_not_a_header(value: object, message: str) -> None:
    with pytest.raises(TypeError, match=message):
        parse_content_disposition(value)  # type: ignore[arg-type]


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
        ({"headers_encoding": b"latin-1"}, TypeError),
        ({"headers_encoding": "no-such-codec"}, LookupError),
        ({"headers_encoding": "rot13"}, LookupError),
        ({"headers": "attachment; filename=a.txt"}, TypeError),
        (
            {"content_disposition": "attachment; filename=中.txt", "headers_encoding": "latin-1"},
            ValueError,
        ),
        ({"content_type": "text/plain; name=中", "headers_encoding": "latin-1"}, ValueError),
    ],
)
def test_caller_errors_come_before_parsing(
    monkeypatch: pytest.MonkeyPatch, arguments: dict[str, object], error: type[Exception]
) -> None:
    def parse(*args: object) -> NoReturn:
        raise AssertionError("parsed before the arguments were checked")

    monkeypatch.setattr(_filename, "_parse", parse)
    monkeypatch.setattr(_filename, "parse_url", parse)
    arguments = {
        "url": "https://example.com/a.txt",
        "content_disposition": "attachment; filename=a.txt",
        **arguments,
    }
    with pytest.raises(error):
        suggested_filename(**arguments)  # type: ignore[arg-type]


VALID = ("Content-Disposition", "attachment; filename=a.txt")


# A valid Content-Disposition line comes before what is wrong, so a check
# that stopped at the first Content-Disposition would let it through.
@pytest.mark.parametrize(
    ("headers", "arguments", "error"),
    [
        (5, {}, TypeError),
        ([VALID, ("X-Count", 5)], {}, TypeError),
        ([VALID, (5, "x")], {}, TypeError),
        ([VALID, ("X",)], {}, TypeError),
        ([VALID, ("X-Note", "中")], {"headers_encoding": "latin-1"}, ValueError),
        ([VALID], {"headers_encoding": "no-such-codec"}, LookupError),
        ([VALID], {"fallback_charset": "utf-7"}, LookupError),
    ],
)
def test_header_errors_come_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
    headers: object,
    arguments: dict[str, object],
    error: type[Exception],
) -> None:
    def parse(*args: object) -> NoReturn:
        raise AssertionError("parsed before the arguments were checked")

    monkeypatch.setattr(_filename, "_parse", parse)
    monkeypatch.setattr(_filename, "parse_url", parse)
    monkeypatch.setattr(_content_disposition, "_parse", parse)
    with pytest.raises(error):
        suggested_filename(headers, url="https://example.com/a.txt", **arguments)  # type: ignore[arg-type]
    with pytest.raises(error):
        parse_content_disposition(headers, **arguments)  # type: ignore[arg-type]
    # The same with Content-Disposition given apart from the headers.
    with pytest.raises(error):
        suggested_filename(headers, content_disposition=VALID[1], **arguments)  # type: ignore[arg-type]


def test_header_value_errors_come_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    def parse(*args: object) -> NoReturn:
        raise AssertionError("parsed before the arguments were checked")

    monkeypatch.setattr(_content_disposition, "_parse", parse)
    with pytest.raises(ValueError, match="headers_encoding"):
        parse_content_disposition("attachment; filename=中.txt", headers_encoding="latin-1")
    with pytest.raises(LookupError):
        parse_content_disposition("attachment", headers_encoding="rot13")


def test_headers_encoding_gives_back_the_bytes() -> None:
    as_requests_gives_it = RAW_BIG5.decode("latin-1")
    from_bytes = parse_content_disposition(RAW_BIG5, fallback_charset="big5")
    assert from_bytes.filename == "中文.txt"
    restored = parse_content_disposition(
        as_requests_gives_it, fallback_charset="big5", headers_encoding="latin-1"
    )
    assert restored == from_bytes
    # Without it, Latin-1 characters whose bytes are not UTF-8 are taken as
    # text, and the Big5 bytes come out as those characters.
    guessed = parse_content_disposition(as_requests_gives_it, fallback_charset="big5")
    assert guessed.filename == "\u00a4\u00a4\u00a4\u00e5.txt"
    for headers in (
        [("Content-Disposition", as_requests_gives_it)],
        {"Content-Disposition": [as_requests_gives_it]},
    ):
        assert (
            parse_content_disposition(headers, fallback_charset="big5", headers_encoding="latin-1")
            == from_bytes
        )
        assert (
            suggested_filename(
                headers, url=URL, fallback_charset="big5", headers_encoding="latin-1"
            )
            == "中文.txt"
        )
        assert suggested_filename(headers, url=URL, fallback_charset="big5") == (
            "\u00a4\u00a4\u00a4\u00e5.txt"
        )

    def named(headers_encoding: str | None) -> str:
        return suggested_filename(
            url=URL,
            content_disposition=as_requests_gives_it,
            fallback_charset="big5",
            headers_encoding=headers_encoding,
        )

    assert named("latin-1") == "中文.txt"
    assert named(None) == "\u00a4\u00a4\u00a4\u00e5.txt"


def test_headers_encoding_turns_surrogate_escapes_back() -> None:
    as_aiohttp_gives_it = RAW_BIG5.decode("utf-8", "surrogateescape")
    parsed = parse_content_disposition(
        as_aiohttp_gives_it, fallback_charset="big5", headers_encoding="utf-8"
    )
    assert parsed.filename == "中文.txt"


def test_headers_encoding_must_fit_every_str() -> None:
    as_text = 'attachment; filename="中文.txt"'
    with pytest.raises(ValueError, match="headers_encoding='latin-1'") as raised:
        parse_content_disposition(as_text, headers_encoding="latin-1")
    assert isinstance(raised.value.__cause__, UnicodeEncodeError)
    with pytest.raises(ValueError, match="headers_encoding='ascii'"):
        suggested_filename([("Content-Disposition", as_text)], headers_encoding="ascii")
    with pytest.raises(ValueError, match="headers_encoding"):
        suggested_filename(content_disposition=as_text, headers_encoding="latin-1")
    with pytest.raises(ValueError, match="headers_encoding"):
        suggested_filename(content_type="text/plain; name=中", headers_encoding="latin-1")
    # Also a header the package does not read: the codec is the wrong one.
    with pytest.raises(ValueError, match="headers_encoding"):
        parse_content_disposition([("X-Note", "中")], headers_encoding="latin-1")
    # The same str encodes with the codec it was decoded with.
    assert parse_content_disposition(as_text, headers_encoding="utf-8").filename == "中文.txt"


@pytest.mark.parametrize("encoding", ["no-such-codec", "rot13", "base64"])
def test_unknown_headers_encoding_raises(encoding: str) -> None:
    # Checked even when no str needs it.
    with pytest.raises(LookupError):
        parse_content_disposition(b"attachment", headers_encoding=encoding)
    with pytest.raises(LookupError):
        suggested_filename(headers_encoding=encoding)


def test_headers_encoding_must_be_str() -> None:
    with pytest.raises(TypeError, match="headers_encoding"):
        parse_content_disposition("attachment", headers_encoding=b"latin-1")  # type: ignore[arg-type]


@pytest.mark.parametrize("encoding", ["ascii", "utf-16"])
def test_headers_encoding_leaves_bytes_alone(encoding: str) -> None:
    raw = RAW_UTF8_LATIN_RANGE
    assert parse_content_disposition(raw, headers_encoding=encoding).filename == "café.txt"
    for name in ("Content-Disposition", b"Content-Disposition"):
        headers = [(name, raw)]
        assert parse_content_disposition(headers, headers_encoding=encoding).filename == "café.txt"
        assert suggested_filename(headers, url=URL, headers_encoding=encoding) == "café.txt"
    assert suggested_filename(content_disposition=raw, headers_encoding=encoding) == "café.txt"
    page = "https://example.com/page"
    assert (
        suggested_filename(url=page, content_type=b"text/html", headers_encoding=encoding)
        == "page.html"
    )


def test_keyword_only_arguments() -> None:
    with pytest.raises(TypeError):
        parse_content_disposition("attachment", "utf-8")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        parse_content_disposition(value="attachment")  # type: ignore[call-arg]
    # The only positional argument of suggested_filename is the headers.
    with pytest.raises(TypeError, match="url="):
        suggested_filename("https://example.com/a.pdf")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        suggested_filename(None, "https://example.com/a.pdf")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        sanitize_filename("a.txt", "untitled")  # type: ignore[call-arg]


def test_fallback_charset_applies_to_url() -> None:
    url = "https://example.com/caf%E9.txt"
    assert suggested_filename(url=url) == "download"
    assert suggested_filename(url=url, fallback_charset="windows-1252") == "café.txt"
    big5_url = "https://example.com/%A4%A4%A4%E5.txt"
    assert suggested_filename(url=big5_url, fallback_charset="big5") == "中文.txt"
