"""Properties that must hold for any input."""

from __future__ import annotations

import time

from hypothesis import example, given, settings
from hypothesis import strategies as st

from browser_download_filename import (
    ContentDisposition,
    parse_content_disposition,
    sanitize_filename,
    suggested_filename,
)
from browser_download_filename._filename import _ILLEGAL_ANYWHERE, _ILLEGAL_AT_ENDS

PIECES = st.sampled_from(
    [
        b"attachment", b"inline", b"filename", b"filename*", b"=", b";", b" ", b"\t", b'"', b"'",
        b"\\", b"%", b"%41", b"%E4%B8%AD", b"UTF-8''", b"=?", b"?=", b"?Q?", b"?B?", b",",
        b"\xc3\xa9", b"\xe9", b"..", b"/", b"a.txt", b"\x00", b"\x7f", b"~",
    ]
)  # fmt: skip
HEADERS = st.one_of(st.binary(max_size=200), st.lists(PIECES, max_size=30).map(b"".join))
# The Content-Disposition lines of one response. Lines that name a file mix
# in, so that lines naming different files come up often.
NAMED = st.sampled_from([b"a.txt", b"b.pdf", b"c"]).map(
    lambda name: b"attachment; filename=" + name
)
LINES = st.lists(st.one_of(HEADERS, NAMED), max_size=4)
TEXT = st.text(max_size=80)
PLATFORMS = st.sampled_from(["posix", "windows"])
CONTENT_TYPE_PIECES = st.sampled_from(
    [
        b"text/html", b"text/plain", b"TEXT/HTML", b"image/png", b"application/rss+xml",
        b"application/octet-stream", b"*/*", b"text", b"/", b",", b", ", b";", b"; charset=",
        b"utf-8", b'"', b"\\", b" ", b"\t", b"(", b")", b"=", b"\xe9", b"\xc3\xa9", b"bogus",
    ]
)  # fmt: skip
CONTENT_TYPE_VALUES = st.lists(CONTENT_TYPE_PIECES, max_size=8).map(b"".join)
CONTENT_TYPES = st.one_of(
    st.binary(max_size=60),
    CONTENT_TYPE_VALUES,
    st.lists(CONTENT_TYPE_VALUES, min_size=2, max_size=3).map(b", ".join),
)
OPTIONS = st.lists(
    st.one_of(
        st.binary(max_size=20),
        st.sampled_from([b"nosniff", b"NOSNIFF", b'"nosniff"', b"nosniff, x", b"x, nosniff"]),
    ),
    max_size=2,
).map(lambda values: [("X-Content-Type-Options", value) for value in values])


@settings(max_examples=500)
@given(HEADERS)
def test_parse_never_raises(header: bytes) -> None:
    parsed = parse_content_disposition(header)
    assert isinstance(parsed, ContentDisposition)
    assert parsed.type in ("inline", "attachment")
    assert parsed.filename is None or (isinstance(parsed.filename, str) and parsed.filename)


@settings(max_examples=300)
@given(st.text(max_size=120))
def test_parse_accepts_any_str(header: str) -> None:
    parse_content_disposition(header)


@settings(max_examples=300)
@given(LINES, TEXT, PLATFORMS)
def test_the_first_line_names_the_file(lines: list[bytes], path: str, platform: str) -> None:
    url = "https://example.com/" + path
    headers = [("Content-Disposition", line) for line in lines]
    assert suggested_filename(
        headers,
        url=url,
        platform=platform,  # type: ignore[arg-type]
    ) == suggested_filename(
        url=url,
        content_disposition=lines[0] if lines else None,
        platform=platform,  # type: ignore[arg-type]
    )


@settings(max_examples=300)
@given(LINES)
def test_parse_reads_the_first_line(lines: list[bytes]) -> None:
    parsed = parse_content_disposition([("Content-Disposition", line) for line in lines])
    first = parse_content_disposition(lines[0] if lines else None)
    assert (parsed.type, parsed.filename) == (first.type, first.filename)


@settings(max_examples=300)
@given(HEADERS, st.integers(min_value=1, max_value=3))
def test_repeating_a_line_changes_nothing(line: bytes, count: int) -> None:
    headers = [("Content-Disposition", line)] * count
    assert parse_content_disposition(headers) == parse_content_disposition(line)


def _assert_safe(name: str) -> None:
    assert name
    assert not any(_ILLEGAL_ANYWHERE.match(char) for char in name)
    assert name[0] not in _ILLEGAL_AT_ENDS
    assert name[-1] not in _ILLEGAL_AT_ENDS


@settings(max_examples=400)
@given(HEADERS, TEXT, PLATFORMS)
def test_suggested_filename_is_always_a_safe_name(header: bytes, path: str, platform: str) -> None:
    name = suggested_filename(
        url="https://example.com/" + path,
        content_disposition=header,
        platform=platform,  # type: ignore[arg-type]
    )
    _assert_safe(name)


@settings(max_examples=400)
@given(st.lists(CONTENT_TYPES, max_size=3), OPTIONS, TEXT, PLATFORMS)
def test_any_content_type_gives_a_safe_name(
    content_types: list[bytes], options: list[tuple[str, bytes]], path: str, platform: str
) -> None:
    headers = [("Content-Type", value) for value in content_types] + options
    name = suggested_filename(
        headers,
        # A query lets the MIME type replace the extension.
        url="https://example.com/" + path + "?q",
        platform=platform,  # type: ignore[arg-type]
    )
    _assert_safe(name)


@settings(max_examples=300)
@given(CONTENT_TYPES, OPTIONS, TEXT)
@example(b"text/plain, text/html", [], "page")
def test_content_type_argument_is_a_content_type_line(
    value: bytes, options: list[tuple[str, bytes]], path: str
) -> None:
    url = "https://example.com/" + path + "?q"
    assert suggested_filename(options, url=url, content_type=value, platform="posix") == (
        suggested_filename([("Content-Type", value), *options], url=url, platform="posix")
    )


@settings(max_examples=300)
@given(st.lists(CONTENT_TYPES, min_size=1, max_size=3), OPTIONS)
@example([b'text/plain; note="', b"text/html"], [])
def test_content_type_lines_are_their_values_joined(
    values: list[bytes], options: list[tuple[str, bytes]]
) -> None:
    # Chromium joins the lines, trimmed, with ", " before it splits them, so
    # a quote left open on one line goes on into the next.
    joined = b", ".join(value.strip(b" \t") for value in values)
    url = "https://example.com/page"
    assert suggested_filename(
        [*(("Content-Type", value) for value in values), *options], url=url, platform="posix"
    ) == suggested_filename([("Content-Type", joined), *options], url=url, platform="posix")


@settings(max_examples=400)
@given(TEXT, st.one_of(st.just("download"), st.text(min_size=1, max_size=20)), PLATFORMS)
def test_sanitize_filename_names_a_download_attribute(
    name: str, default_name: str, platform: str
) -> None:
    sanitized = sanitize_filename(
        name,
        default_name=default_name,
        platform=platform,  # type: ignore[arg-type]
    )
    assert sanitized == suggested_filename(
        download_attribute=name,
        default_name=default_name,
        platform=platform,  # type: ignore[arg-type]
    )
    _assert_safe(sanitized)


@settings(max_examples=400)
@given(TEXT, PLATFORMS)
# On Windows, ReplaceIllegalCharactersInPath decides from the name it is given
# whether that could be an 8.3 short name, and replaces every '~' only if so.
# In "0~|" the '|' rules a short name out, so the '~' stays while the '|'
# becomes '_'; "0~_" could be a short name, so the next cleaning replaces the
# '~'. A '~' in a name that can never be a short name stays both times.
@example("0~|", "windows")
def test_sanitizing_twice_changes_nothing_but_windows_tildes(name: str, platform: str) -> None:
    once = suggested_filename(download_attribute=name, platform=platform)  # type: ignore[arg-type]
    twice = suggested_filename(download_attribute=once, platform=platform)  # type: ignore[arg-type]
    if not once.strip("-_"):
        # Chromium replaces a name made only of '-' and '_' with the default,
        # so "_" (what '"' becomes) turns into "download" the second time.
        assert twice == "download"
    elif platform == "windows":
        assert twice in (once, once.replace("~", "_"))
    else:
        assert twice == once


@settings(max_examples=200)
@given(st.text(min_size=1, max_size=60).filter(lambda name: "\x00" not in name))
def test_ext_value_round_trip(name: str) -> None:
    """An RFC 8187 filename* of any text comes back NFC-normalized."""
    import unicodedata
    import urllib.parse

    quoted = urllib.parse.quote(name.encode("utf-8", "surrogatepass"), safe="")
    parsed = parse_content_disposition(f"attachment; filename*=UTF-8''{quoted}")
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        assert parsed.filename is None  # lone surrogates are not UTF-8
    else:
        assert parsed.filename == unicodedata.normalize("NFC", name)


def test_large_adversarial_inputs_are_fast() -> None:
    inputs = [
        b"attachment; filename=" + b'"' * 200_000,
        b'attachment; filename="' + b"\\" * 200_000,
        b"attachment" + b"; a=b" * 40_000,
        b"attachment; filename=" + b"=?a?b?c?=" * 20_000,
        b"attachment; filename*=UTF-8''" + b"%41" * 60_000,
        b"attachment; filename*=shift_jis''" + b"%81" * 60_000,
        b"attachment; filename=" + b"a " * 100_000,
    ]
    for header in inputs:
        started = time.perf_counter()
        suggested_filename(url="https://example.com/x", content_disposition=header)
        assert time.perf_counter() - started < 2.0
    # parse_content_disposition also splits every value, to compare them. The
    # inputs are long enough that copying the rest of the header for each
    # value would take too long.
    for header in [*inputs, b"attachment" + b"," * 500_000, b'"a",' * 125_000]:
        started = time.perf_counter()
        parse_content_disposition(header)
        assert time.perf_counter() - started < 2.0
    lines = [("Content-Disposition", b"attachment")] * 20_000 + [("Content-Disposition", b"x")]
    started = time.perf_counter()
    assert parse_content_disposition(lines).blocks_download
    assert suggested_filename(lines) == "download"
    assert time.perf_counter() - started < 2.0


def test_large_adversarial_content_types_are_fast() -> None:
    url = "https://example.com/x"
    for value in [
        b"," * 500_000,
        b'"' * 200_000,
        b'"a",' * 125_000,
        b"text/html, " * 50_000,
        b"text/html;" + b"(" * 200_000,
        b"/" * 200_000,
        b"\\" * 200_000,
        b" " * 200_000 + b"text/html",
    ]:
        started = time.perf_counter()
        # Both as one line and as the value of each of many lines.
        suggested_filename([("Content-Type", value), ("X-Content-Type-Options", value)], url=url)
        suggested_filename([("Content-Type", value[:50])] * 10_000, url=url)
        assert time.perf_counter() - started < 2.0
    lines = [("Content-Type", b"text/html")] * 20_000 + [("X-Content-Type-Options", b"x")] * 20_000
    started = time.perf_counter()
    assert suggested_filename(lines, url=url) == "x.html"
    assert time.perf_counter() - started < 2.0
