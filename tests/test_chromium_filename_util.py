"""Chromium's filename generation unit tests, ported.

Source: net/base/filename_util_unittest.cc and base/i18n/
file_util_icu_unittest.cc at the Chromium revision in
browser_download_filename._data (BSD-3-Clause, see THIRD-PARTY-LICENSES).

Chromium builds different expectations for Windows and for POSIX; both sets
are kept, run through platform="windows" and platform="posix". Cases that
depend on the operating system's MIME database or that Chromium only runs on
ChromeOS are left out.
"""

from __future__ import annotations

from typing import NamedTuple

import pytest

from browser_download_filename._charset import require_charset
from browser_download_filename._filename import (
    _generate_safe_file_name,
    _get_suggested_filename,
    _replace_illegal_characters,
)
from browser_download_filename._url import parse_url

PLATFORMS = ("posix", "windows")


class Case(NamedTuple):
    url: str
    content_disposition: bytes
    referrer_charset: str
    suggested_name: str
    mime_type: str
    default_name: str
    #: The expected name, or a {"posix": ..., "windows": ...} dict.
    expected: str | dict[str, str]


def _expected(case: Case, platform: str) -> str:
    return case.expected if isinstance(case.expected, str) else case.expected[platform]


def _run(case: Case, platform: str, referrer_charset: str | None = None) -> str:
    # Chromium's own arguments, as the unit test passes them: mime_type is
    # the type the download code hands over, not a Content-Type header.
    charset = case.referrer_charset if referrer_charset is None else referrer_charset
    return _get_suggested_filename(
        parse_url(case.url),
        case.content_disposition,
        require_charset(charset or None),
        case.suggested_name,
        case.mime_type,
        case.default_name,
        windows=platform == "windows",
    )


SAFE_FILE_NAME_CASES: list[tuple[str, str, str | dict[str, str]]] = [
    ("text/html", "bar.htm", "bar.htm"),
    ("text/html", "bar.html", "bar.html"),
    ("application/x-chrome-extension", "bar", "bar.crx"),
    ("image/png", "bar.html", "bar.html"),
    ("text/html", "bar.exe", "bar.exe"),
    ("image/gif", "bar.exe", "bar.exe"),
    ("text/html", "google.com", "google.com"),
    # Allow extension synonyms.
    ("image/jpeg", "bar.jpg", "bar.jpg"),
    ("image/jpeg", "bar.jpeg", "bar.jpeg"),
    # Device names
    ("text/html", "con.htm", {"windows": "_con.htm", "posix": "con.htm"}),
    ("text/html", "lpt1.htm", {"windows": "_lpt1.htm", "posix": "lpt1.htm"}),
    ("application/x-chrome-extension", "con", {"windows": "_con.crx", "posix": "con.crx"}),
    # Looks like foo.{GUID} which get treated as namespace mounts on Windows.
    (
        "text/html",
        "harmless.{not-really-this-may-be-a-guid}",
        {"windows": "harmless.download", "posix": "harmless.{not-really-this-may-be-a-guid}"},
    ),
    ("text/html", "harmless.{mismatched-", "harmless.{mismatched-"),
    # Dangerous extensions
    ("text/html", "harmless.local", {"windows": "harmless.download", "posix": "harmless.local"}),
    ("text/html", "harmless.lnk", {"windows": "harmless.download", "posix": "harmless.lnk"}),
    ("text/html", "harmless.scf", {"windows": "harmless.download", "posix": "harmless.scf"}),
    ("text/html", "harmless.url", {"windows": "harmless.download", "posix": "harmless.url"}),
]


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize(("mime_type", "filename", "expected"), SAFE_FILE_NAME_CASES)
def test_generate_safe_file_name(
    platform: str, mime_type: str, filename: str, expected: str | dict[str, str]
) -> None:
    want = expected if isinstance(expected, str) else expected[platform]
    assert _generate_safe_file_name(mime_type, False, filename, platform == "windows") == want


# Tests whether the correct filename is selected from the the given
# parameters and that Content-Disposition headers are properly handled
# including failovers when the header is malformed.
SELECTION_CASES: list[Case] = [
    # Picks the filename from the C-D header.
    Case("http://www.google.com/", b"attachment; filename=test.html", "", "", "", "", "test.html"),
    # Ditto. The C-D header uses a quoted string.
    Case(
        "http://www.google.com/", b'attachment; filename="test.html"', "", "", "", "", "test.html"
    ),
    # Ditto. Extra whilespace after the '=' sign.
    Case(
        "http://www.google.com/", b'attachment; filename= "test.html"', "", "", "", "", "test.html"
    ),
    # Ditto. Whitespace before and after '=' sign.
    Case(
        "http://www.google.com/",
        b'attachment; filename   =   "test.html"',
        "",
        "",
        "",
        "",
        "test.html",
    ),
    # Filename is whitespace.  Should failover to URL host
    Case("http://www.google.com/", b"attachment; filename=  ", "", "", "", "", "www.google.com"),
    # No filename.
    Case("http://www.google.com/path/test.html", b"attachment", "", "", "", "", "test.html"),
    # Ditto
    Case("http://www.google.com/path/test.html", b"attachment;", "", "", "", "", "test.html"),
    # No C-D, and no URL path.
    Case("http://www.google.com/", b"", "", "", "", "", "www.google.com"),
    # No C-D. URL has a path.
    Case("http://www.google.com/test.html", b"", "", "", "", "", "test.html"),
    # No C-D. URL's path ends in a slash which results in an empty final
    # component.
    Case("http://www.google.com/path/", b"", "", "", "", "", "www.google.com"),
    # No C-D. URL has a path, but the path has no extension.
    Case("http://www.google.com/path", b"", "", "", "", "", "path"),
    # No C-D. URL gives no filename hints.
    Case("file:///", b"", "", "", "", "", "download"),
    # file:// URL.
    Case("file:///path/testfile", b"", "", "", "", "", "testfile"),
    # Unknown scheme.
    Case("non-standard-scheme:", b"", "", "", "", "", "download"),
    # C-D overrides default
    Case(
        "http://www.google.com/",
        b'attachment; filename ="test.html"',
        "",
        "",
        "",
        "download",
        "test.html",
    ),
    # But the URL doesn't
    Case("http://www.google.com/", b"", "", "", "", "download", "download"),
    # Below is a small subset of cases taken from HttpContentDisposition
    # tests.
    Case(
        "http://www.google.com/",
        b'attachment; filename="%EC%98%88%EC%88%A0%20%EC%98%88%EC%88%A0.jpg"',
        "",
        "",
        "",
        "",
        "예술 예술.jpg",
    ),
    Case(
        "http://www.google.com/%EC%98%88%EC%88%A0%20%EC%98%88%EC%88%A0.jpg",
        b"",
        "",
        "",
        "",
        "download",
        "예술 예술.jpg",
    ),
    Case(
        "http://www.google.com/",
        b"attachment;",
        "",
        "",
        "",
        "다운로드",
        "다운로드",
    ),
    Case(
        "http://www.google.com/",
        b'attachment; filename="=?EUC-JP?Q?=B7=DD=BD=D13=2Epng?="',
        "",
        "",
        "",
        "download",
        "芸術3.png",
    ),
    Case(
        "http://www.example.com/images?id=3",
        b"attachment; filename=caf\xc3\xa9.png",
        "iso-8859-1",
        "",
        "",
        "",
        "café.png",
    ),
    Case(
        "http://www.example.com/images?id=3",
        b"attachment; filename=caf\xe5.png",
        "windows-1253",
        "",
        "",
        "",
        "caf\u03b5.png",
    ),
    # Invalid C-D header. Name value is skipped now.
    Case(
        "http://www.example.com/file?id=3",
        b"attachment; name=\xcf\xc2\xd4\xd8.zip",
        "GBK",
        "",
        "",
        "",
        "file",
    ),
    # Invalid C-D header. Extracts filename from url.
    Case(
        "http://www.google.com/test.html",
        b"attachment; filename==?iiso88591?Q?caf=EG?=",
        "",
        "",
        "",
        "",
        "test.html",
    ),
    # about: and data: URLs
    Case("about:chrome", b"", "", "", "", "", "download"),
    Case("data:,looks/like/a.path", b"", "", "", "", "", "download"),
    Case("data:text/plain;base64,VG8gYmUgb3Igbm90IHRvIGJlLg=", b"", "", "", "", "", "download"),
    Case(
        "data:,looks/like/a.path",
        b"",
        "",
        "",
        "",
        "default_filename_is_given",
        "default_filename_is_given",
    ),
    Case(
        "data:,looks/like/a.path",
        b"",
        "",
        "",
        "",
        "日本語",  # Japanese Kanji.
        "日本語",
    ),
    # The filename encoding is specified by the referrer charset.
    Case(
        "http://example.com/V%FDvojov%E1%20psychologie.doc",
        b"",
        "iso-8859-1",
        "",
        "",
        "",
        "Vývojová psychologie.doc",
    ),
    # Suggested filename takes precedence over URL
    Case("http://www.google.com/test", b"", "", "suggested", "", "", "suggested"),
    # The content-disposition has higher precedence over the suggested name.
    Case(
        "http://www.google.com/test",
        b"attachment; filename=test.html",
        "",
        "suggested",
        "",
        "",
        "test.html",
    ),
    Case(
        "http://www.google.com/test",
        b"attachment; filename=test",
        "utf-8",
        "",
        "image/png",
        "",
        "test",
    ),
    # Raw 8bit characters in C-D
    Case(
        "http://www.example.com/images?id=3",
        b"attachment; filename=caf\xc3\xa9.png",
        "iso-8859-1",
        "",
        "image/png",
        "",
        "café.png",
    ),
    Case(
        "http://www.example.com/images?id=3",
        b"attachment; filename=caf\xe5.png",
        "windows-1253",
        "",
        "image/png",
        "",
        "caf\u03b5.png",
    ),
    # No 'filename' keyword in the disposition, use the URL
    Case(
        "http://www.evil.com/my_download.txt",
        b"a_file_name.txt",
        "",
        "",
        "text/plain",
        "download",
        "my_download.txt",
    ),
    # Spaces in the disposition file name
    Case(
        "http://www.frontpagehacker.com/a_download.exe",
        b"filename=My Downloaded File.exe",
        "",
        "",
        "application/octet-stream",
        "download",
        "My Downloaded File.exe",
    ),
    # % encoded
    Case(
        "http://www.examples.com/",
        b'attachment; filename="%EC%98%88%EC%88%A0%20%EC%98%88%EC%88%A0.jpg"',
        "",
        "",
        "application/x-chrome-extension",
        "download",
        "예술 예술.jpg",
    ),
    # Invalid C-D header. Name value is skipped now.
    Case(
        "http://www.examples.com/q.cgi?id=abc",
        b"attachment; name=abc de.pdf",
        "",
        "",
        "application/octet-stream",
        "download",
        "q.cgi",
    ),
    Case(
        "http://www.example.com/path",
        b'filename="=?EUC-JP?Q?=B7=DD=BD=D13=2Epng?="',
        "",
        "",
        "image/png",
        "download",
        "芸術3.png",
    ),
    # The following two have invalid CD headers and filenames come from the
    # URL.
    Case(
        "http://www.example.com/test%20123",
        b"attachment; filename==?iiso88591?Q?caf=EG?=",
        "",
        "",
        "",
        "download",
        "test 123",
    ),
    Case(
        "http://www.google.com/%EC%98%88%EC%88%A0%20%EC%98%88%EC%88%A0.jpg",
        b"malformed_disposition",
        "",
        "",
        "",
        "download",
        "예술 예술.jpg",
    ),
    # Invalid C-D. No filename from URL. Falls back to 'download'.
    Case(
        "http://www.google.com/path1/path2/",
        b"attachment; filename==?iso88591?Q?caf=E3?",
        "",
        "",
        "",
        "download",
        "download",
    ),
]


# Tests filename generation.  Once the correct filename is selected, they
# should be passed through the validation steps and a correct extension
# should be added if necessary.
GENERATION_CASES: list[Case] = [
    # Dotfiles. Ensures preceeding period(s) stripped.
    Case("http://www.google.com/.test.html", b"", "", "", "", "", "test.html"),
    Case("http://www.google.com/.test", b"", "", "", "", "", "test"),
    Case("http://www.google.com/..test", b"", "", "", "", "", "test"),
    # Disposition has relative paths, remove directory separators
    Case(
        "",
        b"filename=../../../../././../a_file_name.txt",
        "",
        "",
        "text/plain",
        "download",
        "_.._.._.._._._.._a_file_name.txt",
    ),
    # Disposition has parent directories, remove directory separators
    Case(
        "",
        b"filename=dir1/dir2/a_file_name.txt",
        "",
        "",
        "text/plain",
        "download",
        "dir1_dir2_a_file_name.txt",
    ),
    # Disposition has relative paths, remove directory separators
    Case(
        "",
        b"filename=..\\..\\..\\..\\.\\.\\..\\a_file_name.txt",
        "",
        "",
        "text/plain",
        "download",
        "_.._.._.._._._.._a_file_name.txt",
    ),
    # Disposition has parent directories, remove directory separators
    Case(
        "",
        b"filename=dir1\\dir2\\a_file_name.txt",
        "",
        "",
        "text/plain",
        "download",
        "dir1_dir2_a_file_name.txt",
    ),
    # Filename looks like HTML?
    Case(
        "",
        b'filename="<blink>Hello kitty</blink>"',
        "",
        "",
        "text/plain",
        "default",
        "_blink_Hello kitty__blink_",
    ),
    # A normal avi should get .avi and not .avi.avi
    Case("https://example.com/misc/2.avi", b"", "", "", "video/x-msvideo", "download", "2.avi"),
    # Slashes are illegal, and should be replaced with underscores.
    Case(
        "http://example.com/foo%2f..%2fbar.jpg",
        b"",
        "",
        "",
        "text/plain",
        "download",
        "foo_.._bar.jpg",
    ),
    # "%00" decodes to the NUL byte, which is illegal and should be replaced
    # with an underscore. (Note: This can't be tested with a URL, since "%00"
    # is illegal in a URL. Only applies to Content-Disposition.)
    Case(
        "http://example.com/download.py",
        b"filename=foo%00bar.jpg",
        "",
        "",
        "text/plain",
        "download",
        "foo_bar.jpg",
    ),
    # Extension generation for C-D derived filenames.
    Case("", b"filename=my-cat", "", "", "image/jpeg", "download", "my-cat"),
    # Unknown MIME type
    Case("", b"filename=my-cat", "", "", "dance/party", "download", "my-cat"),
    # Known MIME type.
    Case("", b"filename=my-cat.jpg", "", "", "text/plain", "download", "my-cat.jpg"),
    # Test truncation of trailing dots and spaces
    Case("", b"filename=evil.exe ", "", "", "binary/octet-stream", "download", "evil.exe"),
    Case(
        "",
        b"filename=evil.exe.",
        "",
        "",
        "binary/octet-stream",
        "download",
        {"windows": "evil.exe_", "posix": "evil.exe"},
    ),
    Case(
        "",
        b"filename=evil.exe.  .  .",
        "",
        "",
        "binary/octet-stream",
        "download",
        {"windows": "evil.exe_______", "posix": "evil.exe.  . _"},
    ),
    Case(
        "",
        b"filename=evil.",
        "",
        "",
        "binary/octet-stream",
        "download",
        {"windows": "evil_", "posix": "evil"},
    ),
    Case(
        "",
        b"filename=. . . . .",
        "",
        "",
        "binary/octet-stream",
        "download",
        {"windows": "download", "posix": "_. . ._"},
    ),
    Case(
        "", b'attachment; filename="meh.exe\xc2\xa0"', "", "", "binary/octet-stream", "", "meh.exe_"
    ),
    # Disappearing directory references:
    Case("", b"filename=.", "", "", "dance/party", "download", "download"),
    Case("", b"filename=..", "", "", "dance/party", "download", "download"),
    Case("", b"filename=...", "", "", "dance/party", "download", "download"),
    # Reserved words on Windows
    Case(
        "",
        b"filename=COM1",
        "",
        "",
        "application/foo-bar",
        "download",
        {"windows": "_COM1", "posix": "COM1"},
    ),
    Case(
        "",
        b"filename=COM4.txt",
        "",
        "",
        "text/plain",
        "download",
        {"windows": "_COM4.txt", "posix": "COM4.txt"},
    ),
    Case(
        "",
        b"filename=lpt1.TXT",
        "",
        "",
        "text/plain",
        "download",
        {"windows": "_lpt1.TXT", "posix": "lpt1.TXT"},
    ),
    Case(
        "",
        b"filename=clock$.txt",
        "",
        "",
        "text/plain",
        "download",
        {"windows": "_clock$.txt", "posix": "clock$.txt"},
    ),
    # Validation should also apply to sugested name
    Case(
        "",
        b"",
        "",
        "clock$.txt",
        "text/plain",
        "download",
        {"windows": "_clock$.txt", "posix": "clock$.txt"},
    ),
    # Device names only work when present at the start of the string.
    Case("", b"filename=mycom1.foo", "", "", "", "download", "mycom1.foo"),
    Case(
        "",
        b"filename=Setup.exe.local",
        "",
        "",
        "",
        "download",
        {"windows": "Setup.exe.download", "posix": "Setup.exe.local"},
    ),
    Case(
        "",
        b"filename=Setup.exe.local.local",
        "",
        "",
        "",
        "download",
        {"windows": "Setup.exe.local.download", "posix": "Setup.exe.local.local"},
    ),
    Case(
        "",
        b"filename=Setup.exe.lnk",
        "",
        "",
        "",
        "download",
        {"windows": "Setup.exe.download", "posix": "Setup.exe.lnk"},
    ),
    Case(
        "",
        b"filename=Desktop.ini",
        "",
        "",
        "",
        "download",
        {"windows": "_Desktop.ini", "posix": "Desktop.ini"},
    ),
    Case(
        "",
        b"filename=Thumbs.db",
        "",
        "",
        "",
        "download",
        {"windows": "_Thumbs.db", "posix": "Thumbs.db"},
    ),
    # Regression tests for older issues:
    # http://crbug.com/5772.
    Case(
        "http://www.example.com/foo.tar.gz",
        b"",
        "",
        "",
        "application/x-tar",
        "download",
        "foo.tar.gz",
    ),
    # http://crbug.com/52250.
    Case("http://www.example.com/foo.tgz", b"", "", "", "application/x-tar", "download", "foo.tgz"),
    # http://crbug.com/7337.
    Case(
        "http://maged.lordaeron.org/blank.reg",
        b"",
        "",
        "",
        "text/x-registry",
        "download",
        "blank.reg",
    ),
    Case("http://www.example.com/bar.tar", b"", "", "", "application/x-tar", "download", "bar.tar"),
    Case(
        "http://www.example.com/bar.bogus",
        b"",
        "",
        "",
        "application/x-tar",
        "download",
        "bar.bogus",
    ),
    # http://crbug.com/20337
    Case(
        "http://www.example.com/.download.txt",
        b"filename=.download.txt",
        "",
        "",
        "text/plain",
        "-download",
        "download.txt",
    ),
    # http://crbug.com/56855.
    Case("http://www.example.com/bar.sh", b"", "", "", "application/x-sh", "download", "bar.sh"),
    # http://crbug.com/61571
    Case(
        "http://www.example.com/npdf.php?fn=foobar.pdf",
        b"",
        "",
        "",
        "application/x-chrome-extension",
        "download",
        "npdf.crx",
    ),
    # Shouldn't overwrite C-D specified extension.
    Case(
        "http://www.example.com/npdf.php?fn=foobar.pdf",
        b"filename=foobar.jpg",
        "",
        "",
        "text/plain",
        "download",
        "foobar.jpg",
    ),
    # http://crbug.com/87719
    Case(
        "http://www.example.com/image.aspx?id=blargh",
        b"",
        "",
        "",
        "application/x-chrome-extension",
        "download",
        "image.crx",
    ),
    Case("http://www.example.com/image.aspx?id=blargh", b"", "", " .foo", "", "download", "_.foo"),
    # Note that the next 4 tests will not fail on all platforms on regression.
    # They only fail if application/[x-]gzip has a default extension, which
    # can vary across platforms (And even by OS install).
    Case(
        "http://www.example.com/goat.tar.gz?wearing_hat=true",
        b"",
        "",
        "",
        "application/gzip",
        "",
        "goat.tar.gz",
    ),
    Case(
        "http://www.example.com/goat.tar.gz?wearing_hat=true",
        b"",
        "",
        "",
        "application/x-gzip",
        "",
        "goat.tar.gz",
    ),
    Case(
        "http://www.example.com/goat.tgz?wearing_hat=true",
        b"",
        "",
        "",
        "application/gzip",
        "",
        "goat.tgz",
    ),
    Case(
        "http://www.example.com/goat.tgz?wearing_hat=true",
        b"",
        "",
        "",
        "application/x-gzip",
        "",
        "goat.tgz",
    ),
    # U+3000 IDEOGRAPHIC SPACE (http://crbug.com/849794): In URL file name.
    Case(
        "http://www.example.com/%E5%B2%A1%E3%80%80%E5%B2%A1.txt",
        b"",
        "",
        "",
        "text/plain",
        "",
        "岡\u3000岡.txt",
    ),
    # U+3000 IDEOGRAPHIC SPACE (http://crbug.com/849794): In
    # Content-Disposition filename.
    Case(
        "http://www.example.com/download.py",
        b"filename=%E5%B2%A1%E3%80%80%E5%B2%A1.txt",
        "utf-8",
        "",
        "text/plain",
        "",
        "岡\u3000岡.txt",
    ),
]


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("case", SELECTION_CASES + GENERATION_CASES)
def test_generate_file_name(case: Case, platform: str) -> None:
    assert _run(case, platform) == _expected(case, platform)


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("case", GENERATION_CASES)
def test_generate_file_name_with_gbk_referrer_charset(case: Case, platform: str) -> None:
    assert _run(case, platform, referrer_charset="GBK") == _expected(case, platform)


class IllegalCharacterCase(NamedTuple):
    bad_name: str
    good_name_with_dash: str
    good_name_with_space: str
    windows_only: bool = False
    posix_only: bool = False


# kIllegalCharacterCases from base/i18n/file_util_icu_unittest.cc.
ILLEGAL_CHARACTER_CASES: list[IllegalCharacterCase] = [
    IllegalCharacterCase("bad*file:name?.jpg", "bad-file-name-.jpg", "bad file name .jpg"),
    IllegalCharacterCase("**********::::.txt", "--------------.txt", "_.txt"),
    IllegalCharacterCase(
        "bad\x03\x91 file\u200e\u200fname.png", "bad-- file--name.png", "bad   file  name.png"
    ),
    IllegalCharacterCase("bad*file\\?name.jpg", "bad-file--name.jpg", "bad file  name.jpg"),
    IllegalCharacterCase("\t  bad*file\\name/.jpg", "-  bad-file-name-.jpg", "bad file name .jpg"),
    IllegalCharacterCase(
        "this_file_name is okay!.mp3", "this_file_name is okay!.mp3", "this_file_name is okay!.mp3"
    ),
    IllegalCharacterCase("一가.mp3", "一가.mp3", "一가.mp3"),
    IllegalCharacterCase("ص\u200cل.mp3", "ص-ل.mp3", "ص ل.mp3"),
    IllegalCharacterCase(
        "\U00010330\U00010331.mp3", "\U00010330\U00010331.mp3", "\U00010330\U00010331.mp3"
    ),
    # Unassigned codepoints are ok.
    IllegalCharacterCase("\u0378\U00040001.mp3", "\u0378\U00040001.mp3", "\u0378\U00040001.mp3"),
    # Non-characters are not allowed.
    IllegalCharacterCase(
        "bad\ufffffile\U0010fffename.jpg", "bad-file-name.jpg", "bad file name.jpg"
    ),
    IllegalCharacterCase("bad\ufdd0file\ufdefname.jpg", "bad-file-name.jpg", "bad file name.jpg"),
    # CVE-2014-9390
    IllegalCharacterCase(
        "(\u200c.\u200d.\u200e.\u200f.\u202a.\u202b.\u202c.\u202d.\u202e.\u206a.\u206b.\u206c.\u206d.\u206f.\ufeff)",
        "(-.-.-.-.-.-.-.-.-.-.-.-.-.-.-)",
        "( . . . . . . . . . . . . . . )",
    ),
    IllegalCharacterCase(" _ ", "-_-", "_"),
    IllegalCharacterCase(" ", "-", "_ _"),
    IllegalCharacterCase("\u2008.(\u2007).\u3000", "-.(\u2007).-", "(\u2007)"),
    IllegalCharacterCase("     ", "-   -", "_     _"),
    IllegalCharacterCase(".    ", "-   -", "_.    _"),
    # '~' is only invalid on Windows, and only if the file name could possibly
    # be an 8.3 short name.
    IllegalCharacterCase("config~1", "config-1", "config 1", windows_only=True),
    IllegalCharacterCase("config~1.txt", "config-1.txt", "config 1.txt", windows_only=True),
    IllegalCharacterCase("config~1", "config~1", "config~1", posix_only=True),
    IllegalCharacterCase("config~1.txt", "config~1.txt", "config~1.txt", posix_only=True),
    # Tildes are always illegal at ends.
    IllegalCharacterCase("~config1.txt", "-config1.txt", "config1.txt"),
    IllegalCharacterCase("config1.txt~", "config1.txt-", "config1.txt"),
    # Some characters, such as spaces, are not allowed in 8.3 short names.
    # Don't replace the '~' if these characters are present.
    IllegalCharacterCase("conf g~1", "conf g~1", "conf g~1"),
    IllegalCharacterCase("conf,g~1.txt", "conf,g~1.txt", "conf,g~1.txt"),
    # File names with periods in invalid positions are not legal 8.3 names.
    IllegalCharacterCase("conf~1.jpeg", "conf~1.jpeg", "conf~1.jpeg"),
    IllegalCharacterCase("config~12.md", "config~12.md", "config~12.md"),
    # Short names without a '~' character are allowed.
    IllegalCharacterCase("config.txt", "config.txt", "config.txt"),
    # Names long enough to not be short names are allowed.
    IllegalCharacterCase("config~12.txt", "config~12.txt", "config~12.txt"),
    IllegalCharacterCase(
        "config~1VeryLongCannotBeShortNameOK.txt",
        "config~1VeryLongCannotBeShortNameOK.txt",
        "config~1VeryLongCannotBeShortNameOK.txt",
    ),
    # Base name is longer than 8 characters, without a dot.
    IllegalCharacterCase("config~1txt", "config~1txt", "config~1txt"),
]

# kLinuxIllegalCharacterCases, minus the one built from invalid UTF-8 bytes,
# which a str cannot hold.
LINUX_ILLEGAL_CHARACTER_CASES: list[tuple[str, str]] = [
    ("bad*\\/file:name?.jpg", "bad---file-name-.jpg"),
    ("**********::::.txt", "--------------.txt"),
    (" _ ", "-_-"),
    (".", "-"),
    (" .( ). ", "-.( ).-"),
    ("     ", "-   -"),
]


def _illegal_character_params() -> list[tuple[str, IllegalCharacterCase]]:
    return [
        (platform, case)
        for case in ILLEGAL_CHARACTER_CASES
        for platform in PLATFORMS
        if not (case.windows_only and platform != "windows")
        and not (case.posix_only and platform != "posix")
    ]


@pytest.mark.parametrize(("platform", "case"), _illegal_character_params())
def test_replace_illegal_characters_in_path(platform: str, case: IllegalCharacterCase) -> None:
    windows = platform == "windows"
    assert _replace_illegal_characters(case.bad_name, windows, "-") == case.good_name_with_dash


@pytest.mark.parametrize(("platform", "case"), _illegal_character_params())
def test_replace_illegal_characters_in_path_with_illegal_end_char(
    platform: str, case: IllegalCharacterCase
) -> None:
    windows = platform == "windows"
    assert _replace_illegal_characters(case.bad_name, windows, " ") == case.good_name_with_space


@pytest.mark.parametrize(("bad_name", "good_name"), LINUX_ILLEGAL_CHARACTER_CASES)
def test_replace_illegal_characters_in_path_linux(bad_name: str, good_name: str) -> None:
    assert _replace_illegal_characters(bad_name, False, "-") == good_name
