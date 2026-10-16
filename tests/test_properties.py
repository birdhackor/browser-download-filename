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
TEXT = st.text(max_size=80)
PLATFORMS = st.sampled_from(["posix", "windows"])


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
