"""The URL fallback: the parts of GURL that decide the file name."""

from __future__ import annotations

import pytest

from browser_download_filename import suggested_filename
from browser_download_filename._url import parse_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/report.pdf", "report.pdf"),
        ("https://example.com/files/%E4%B8%AD%E6%96%87.zip", "中文.zip"),
        ("https://example.com/files/中文.zip", "中文.zip"),
        ("https://example.com/a/b/../c.txt", "c.txt"),
        ("https://example.com/a/b/..", "download"),
        ("https://example.com/a/b/.", "download"),
        ("https://example.com/a/%2e%2E/c.txt", "c.txt"),
        ("https://example.com/a/.%2e", "download"),
        ("https://example.com/a\\b.txt", "b.txt"),
        ("https://example.com/a%2Fb.txt", "a_b.txt"),
        ("https://example.com/a%5Cb.txt", "a_b.txt"),
        ("https://example.com/file.txt;jsessionid=ABC", "file.txt"),
        ("https://example.com/file.txt;a;b", "file.txt"),
        ("https://example.com/dir/", "download"),
        ("https://example.com/f.txt#fragment/x.y", "f.txt"),
        ("https://example.com/my%20file.txt", "my file.txt"),
        ("https://example.com/100%zz.txt", "100%zz.txt"),
        ("https://example.com/a%00b.txt", "a_b.txt"),
        ("https://example.com/.hidden", "hidden"),
        ("https://user:pass@example.com:8443/x.bin", "x.bin"),
        ("  https://example.com/trimmed.txt\n", "trimmed.txt"),
        ("https://exa\tmple.com/ta\nb.txt", "tab.txt"),
        ("HTTPS://EXAMPLE.COM/Upper.TXT", "Upper.TXT"),
        ("http:example.com/no-slashes.txt", "no-slashes.txt"),
        ("file:///home/user/doc.txt", "doc.txt"),
        (
            "blob:https://example.com/550e8400-e29b-41d4-a716-446655440000",
            "550e8400-e29b-41d4-a716-446655440000",
        ),
        ("about:blank", "download"),
        ("data:text/plain,hello/world.txt", "download"),
        ("relative/path.txt", "download"),
        ("", "download"),
        ("https:///no-host.txt", "download"),
        ("https://exa mple.com/bad-host.txt", "download"),
        ("https://example.com:99999/bad-port.txt", "download"),
    ],
)
def test_file_name_from_url(url: str, expected: str) -> None:
    assert suggested_filename(url) == expected


def test_query_lets_mime_type_replace_extension() -> None:
    assert suggested_filename("https://example.com/get.php?id=1", mime_type="application/pdf") == (
        "get.pdf"
    )
    assert suggested_filename("https://example.com/get.php?", mime_type="application/pdf") == (
        "get.pdf"
    )
    assert suggested_filename("https://example.com/get.php", mime_type="application/pdf") == (
        "get.php"
    )


def test_host_is_the_last_resort_without_default_name() -> None:
    assert suggested_filename("https://Example.COM/", default_name="") == "example.com"
    assert suggested_filename("https://例え.jp/", default_name="") == "xn--r8jz45g.jp"
    assert suggested_filename("https://[::1]:8080/", default_name="") == "[__1]"
    assert suggested_filename("file:///", default_name="") == "download"


def test_parse_url_parts() -> None:
    parsed = parse_url("https://user@Example.com:8080/a/./b/../c;p?q=1#f")
    assert parsed is not None
    assert parsed.scheme == "https"
    assert parsed.host == "example.com"
    assert parsed.path == "/a/c;p"
    assert parsed.has_query
    assert parsed.extract_file_name() == "c"
    assert parse_url("mailto:someone@example.com") is not None
    assert parse_url("no scheme here") is None
