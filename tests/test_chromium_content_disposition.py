"""Chromium's HttpContentDisposition unit tests, ported.

Source: net/http/http_content_disposition_unittest.cc at the Chromium
revision in browser_download_filename._data (BSD-3-Clause, see
THIRD-PARTY-LICENSES). Cases and comments are kept in Chromium's order;
cases that Chromium compiles out are left out here too.
"""

from __future__ import annotations

import pytest

from browser_download_filename import parse_content_disposition
from browser_download_filename._charset import require_charset
from browser_download_filename._content_disposition import _parse
from browser_download_filename._http import first_comma_separated_value

# (header, referrer charset, expected filename); "" means no filename.
FILENAME_CASES: list[tuple[bytes, str, str]] = [
    # Test various forms of C-D header fields emitted by web servers.
    (b'inline; filename="abcde.pdf"', "", "abcde.pdf"),
    (b'inline;filename="abcde.pdf"', "", "abcde.pdf"),
    (b'  inline   ; filename="abcde.pdf"', "", "abcde.pdf"),
    (b'\t\tinline\t\t; filename="abcde.pdf"', "", "abcde.pdf"),
    (b"attachment; filename=abcde.pdf", "", "abcde.pdf"),
    (b"attachment; filename=abc,de.pdf", "", "abc"),
    (b"filename=abcde.pdf", "", "abcde.pdf"),
    (b"filename= abcde.pdf", "", "abcde.pdf"),
    (b"filename =abcde.pdf", "", "abcde.pdf"),
    (b"filename = abcde.pdf", "", "abcde.pdf"),
    (b"filename\t=abcde.pdf", "", "abcde.pdf"),
    (b"filename \t\t  =abcde.pdf", "", "abcde.pdf"),
    (b'inline; filename="abc%20de.pdf"', "", "abc de.pdf"),
    # Name values are no longer synonyms for filename.
    (b'inline; name="abcde.pdf"', "", ""),
    (b"attachment; name=abcde.pdf", "", ""),
    (b"name=abcde.pdf", "", ""),
    # Unbalanced quotation mark
    (b'filename="abcdef.pdf', "", "abcdef.pdf"),
    # Whitespaces are converted to a space.
    (b'inline; filename="abc  \tde.pdf"', "", "abc   de.pdf"),
    # %-escaped UTF-8
    (
        b'attachment; filename="%EC%98%88%EC%88%A0%20%EC%98%88%EC%88%A0.jpg"',
        "",
        "예술 예술.jpg",
    ),
    (
        b'attachment; filename="%F0%90%8C%B0%F0%90%8C%B1abc.jpg"',
        "",
        "\U00010330\U00010331abc.jpg",
    ),
    (
        b'attachment; filename="%EC%98%88%EC%88%A0 \t%EC%98%88%EC%88%A0.jpg"',
        "",
        "예술  예술.jpg",
    ),
    # Characters that are not supposed to be displayed should still be
    # decoded.
    (
        b"attachment; filename=%E5%B2%A1%E3%80%80%E5%B2%A1.txt",
        "",
        "岡\u3000岡.txt",
    ),
    # RFC 2047 with various charsets and Q/B encodings
    (
        b'attachment; filename="=?EUC-JP?Q?=B7=DD=BD=D13=2Epng?="',
        "",
        "芸術3.png",
    ),
    (b"attachment; filename==?eUc-Kr?b?v7m8+iAzLnBuZw==?=", "", "예술 3.png"),
    (
        b"attachment; filename==?utf-8?Q?=E8=8A=B8=E8=A1=93_3=2Epng?=",
        "",
        "芸術 3.png",
    ),
    (b"attachment; filename==?utf-8?Q?=F0=90=8C=B0_3=2Epng?=", "", "\U00010330 3.png"),
    (b'inline; filename="=?iso88591?Q?caf=e9_=2epng?="', "", "café .png"),
    # Space after an encoded word should be removed.
    (b'inline; filename="=?iso88591?Q?caf=E9_?= .png"', "", "café .png"),
    # Two encoded words with different charsets (not very likely to be
    # emitted by web servers in the wild). Spaces between them are removed.
    (
        b'inline; filename="=?euc-kr?b?v7m8+iAz?= =?ksc5601?q?=BF=B9=BC=FA=2Epng?="',
        "",
        "예술 3예술.png",
    ),
    (
        b'attachment; filename="=?windows-1252?Q?caf=E9?=  =?iso-8859-7?b?4eI=?= .png"',
        "",
        "café\u03b1\u03b2.png",
    ),
    # Non-ASCII string is passed through and treated as UTF-8 as long as
    # it's valid as UTF-8 and regardless of |referrer_charset|.
    (b"attachment; filename=caf\xc3\xa9.png", "iso-8859-1", "café.png"),
    (b"attachment; filename=caf\xc3\xa9.png", "", "café.png"),
    # Non-ASCII/Non-UTF-8 string. Fall back to the referrer charset.
    (b"attachment; filename=caf\xe5.png", "windows-1253", "caf\u03b5.png"),
    # Failure cases
    # Invalid hex-digit "G"
    (b"attachment; filename==?iiso88591?Q?caf=EG?=", "", ""),
    # Incomplete RFC 2047 encoded-word (missing '='' at the end)
    (b"attachment; filename==?iso88591?Q?caf=E3?", "", ""),
    # Extra character at the end of an encoded word
    (b"attachment; filename==?iso88591?Q?caf=E3?==", "", ""),
    # Extra token at the end of an encoded word
    (b"attachment; filename==?iso88591?Q?caf=E3?=?", "", ""),
    (b"attachment; filename==?iso88591?Q?caf=E3?=?=", "", ""),
    # Incomplete hex-escaped chars
    (b"attachment; filename==?windows-1252?Q?=63=61=E?=", "", ""),
    (b"attachment; filename=%EC%98%88%EC%88%A", "", ""),
    # %-escaped non-UTF-8 encoding is an "error"
    (b"attachment; filename=%B7%DD%BD%D1.png", "", ""),
    # Two RFC 2047 encoded words in a row without a space is an error.
    (
        b"attachment; filename==?windows-1252?Q?caf=E3?==?iso-8859-7?b?4eIucG5nCg==?=",
        "",
        "",
    ),
    # RFC 5987 tests with Filename*  : see http://tools.ietf.org/html/rfc5987
    (b"attachment; filename*=foo.html", "", ""),
    (b"attachment; filename*=foo'.html", "", ""),
    (b"attachment; filename*=''foo'.html", "", ""),
    (b"attachment; filename*=''foo.html'", "", ""),
    (b"attachment; filename*=''f\"oo\".html'", "", ""),
    (b"attachment; filename*=bogus_charset''foo.html'", "", ""),
    (b"attachment; filename*='en'foo.html'", "", ""),
    (b"attachment; filename*=iso-8859-1'en'foo.html", "", "foo.html"),
    (b"attachment; filename*=utf-8'en'foo.html", "", "foo.html"),
    (
        b"attachment; filename*=utf-8'en'%E5%B2%A1%E3%80%80%E5%B2%A1.txt",
        "",
        "岡\u3000岡.txt",
    ),
    # charset cannot be omitted.
    (b"attachment; filename*='es'f\xfa.html'", "", ""),
    # Non-ASCII bytes are not allowed.
    (b"attachment; filename*=iso-8859-1'es'f\xfa.html", "", ""),
    (b"attachment; filename*=utf-8'es'f\xce\xba.html", "", ""),
    # TODO(jshin): Space should be %-encoded, but currently, we allow
    # spaces.
    (b"inline; filename*=iso88591''cafe foo.png", "", "cafe foo.png"),
    # Filename* tests converted from Q-encoded tests above.
    (b"attachment; filename*=EUC-JP''%B7%DD%BD%D13%2Epng", "", "芸術3.png"),
    (b"attachment; filename*=utf-8''%E8%8A%B8%E8%A1%93%203%2Epng", "", "芸術 3.png"),
    (b"attachment; filename*=utf-8''%F0%90%8C%B0 3.png", "", "\U00010330 3.png"),
    (b"inline; filename*=Euc-Kr'ko'%BF%B9%BC%FA%2Epng", "", "예술.png"),
    (b"attachment; filename*=windows-1252''caf%E9.png", "", "café.png"),
    # Multiple filename, filename*, name parameters specified.
    (b'attachment; name="foo"; filename="bar"', "", "bar"),
    (b'attachment; filename="bar"; name="foo"', "", "bar"),
    (b"attachment; filename=\"bar\"; filename*=utf-8''baz", "", "baz"),
    # http://greenbytes.de/tech/tc2231/ filename* test cases.
    # attwithisofn2231iso
    (b"attachment; filename*=iso-8859-1''foo-%E4.html", "", "foo-ä.html"),
    # attwithfn2231utf8
    (b"attachment; filename*=UTF-8''foo-%c3%a4-%e2%82%ac.html", "", "foo-ä-€.html"),
    # attwithfn2231noc : no encoding specified but UTF-8 is used.
    (b"attachment; filename*=''foo-%c3%a4-%e2%82%ac.html", "", ""),
    # attwithfn2231utf8comp
    (b"attachment; filename*=UTF-8''foo-a%cc%88.html", "", "foo-ä.html"),
    # attwithfn2231ws1
    (b"attachment; filename *=UTF-8''foo-%c3%a4.html", "", ""),
    # attwithfn2231ws2
    (b"attachment; filename*= UTF-8''foo-%c3%a4.html", "", "foo-ä.html"),
    # attwithfn2231ws3
    (b"attachment; filename* =UTF-8''foo-%c3%a4.html", "", "foo-ä.html"),
    # attwithfn2231quot
    (b"attachment; filename*=\"UTF-8''foo-%c3%a4.html\"", "", ""),
    # attfnboth
    (
        b"attachment; filename=\"foo-ae.html\"; filename*=UTF-8''foo-%c3%a4.html",
        "",
        "foo-ä.html",
    ),
    # attfnboth2
    (
        b"attachment; filename*=UTF-8''foo-%c3%a4.html; filename=\"foo-ae.html\"",
        "",
        "foo-ä.html",
    ),
    # attnewandfn
    (b'attachment; foobar=x; filename="foo.html"', "", "foo.html"),
]


@pytest.mark.parametrize(("header", "charset", "expected"), FILENAME_CASES)
def test_filename(header: bytes, charset: str, expected: str) -> None:
    parsed = parse_content_disposition(header, fallback_charset=charset or None)
    assert parsed.filename == (expected or None)


# Test cases from http://greenbytes.de/tech/tc2231/
TC2231_CASES: list[tuple[bytes, str, str]] = [
    # http://greenbytes.de/tech/tc2231/#inlonly
    (b"inline", "inline", ""),
    # http://greenbytes.de/tech/tc2231/#inlonlyquoted
    (b'"inline"', "inline", ""),
    # http://greenbytes.de/tech/tc2231/#inlwithasciifilename
    (b'inline; filename="foo.html"', "inline", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#inlwithfnattach
    (b'inline; filename="Not an attachment!"', "inline", "Not an attachment!"),
    # http://greenbytes.de/tech/tc2231/#inlwithasciifilenamepdf
    (b'inline; filename="foo.pdf"', "inline", "foo.pdf"),
    # http://greenbytes.de/tech/tc2231/#attonly
    (b"attachment", "attachment", ""),
    # http://greenbytes.de/tech/tc2231/#attonlyquoted
    (b'"attachment"', "inline", ""),
    # http://greenbytes.de/tech/tc2231/#attonlyucase
    (b"ATTACHMENT", "attachment", ""),
    # http://greenbytes.de/tech/tc2231/#attwithasciifilename
    (b'attachment; filename="foo.html"', "attachment", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attwithasciifnescapedchar
    (b'attachment; filename="f\\oo.html"', "attachment", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attwithasciifnescapedquote
    (
        b'attachment; filename="\\"quoting\\" tested.html"',
        "attachment",
        '"quoting" tested.html',
    ),
    # http://greenbytes.de/tech/tc2231/#attwithquotedsemicolon
    (
        b'attachment; filename="Here\'s a semicolon;.html"',
        "attachment",
        "Here's a semicolon;.html",
    ),
    # http://greenbytes.de/tech/tc2231/#attwithfilenameandextparam
    (b'attachment; foo="bar"; filename="foo.html"', "attachment", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attwithfilenameandextparamescaped
    (b'attachment; foo="\\"\\\\";filename="foo.html"', "attachment", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attwithasciifilenameucase
    (b'attachment; FILENAME="foo.html"', "attachment", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attwithasciifilenamenq
    (b"attachment; filename=foo.html", "attachment", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attwithasciifilenamenqs
    # Note: tc2231 says we should fail to parse this header.
    (b"attachment; filename=foo.html ;", "attachment", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attemptyparam
    # Note: tc2231 says we should fail to parse this header.
    (b"attachment; ;filename=foo", "attachment", "foo"),
    # http://greenbytes.de/tech/tc2231/#attwithasciifilenamenqws
    # Note: tc2231 says we should fail to parse this header.
    (b"attachment; filename=foo bar.html", "attachment", "foo bar.html"),
    # http://greenbytes.de/tech/tc2231/#attwithfntokensq
    (b"attachment; filename='foo.bar'", "attachment", "'foo.bar'"),
    # http://greenbytes.de/tech/tc2231/#attwithutf8fnplain
    # Note: We'll UTF-8 decode the file name, even though tc2231 says not to.
    (b'attachment; filename="foo-\xc3\xa4.html"', "attachment", "foo-ä.html"),
    # http://greenbytes.de/tech/tc2231/#attwithfnrawpctenca
    (b'attachment; filename="foo-%41.html"', "attachment", "foo-A.html"),
    # http://greenbytes.de/tech/tc2231/#attwithfnusingpct
    (b'attachment; filename="50%.html"', "attachment", "50%.html"),
    # http://greenbytes.de/tech/tc2231/#attwithfnrawpctencaq
    (b'attachment; filename="foo-%\\41.html"', "attachment", "foo-A.html"),
    # http://greenbytes.de/tech/tc2231/#attwithnamepct
    # Value is skipped like other UAs.
    (b'attachment; name="foo-%41.html"', "attachment", ""),
    # http://greenbytes.de/tech/tc2231/#attwithfnrawpctenclong
    (
        b'attachment; filename="foo-%c3%a4-%e2%82%ac.html"',
        "attachment",
        "foo-ä-€.html",
    ),
    # http://greenbytes.de/tech/tc2231/#attwithasciifilenamews1
    (b'attachment; filename ="foo.html"', "attachment", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attwith2filenames
    # Note: tc2231 says we should fail to parse this header.
    (b'attachment; filename="foo.html"; filename="bar.html"', "attachment", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attfnbrokentoken
    # Note: tc2231 says we should fail to parse this header.
    (b"attachment; filename=foo[1](2).html", "attachment", "foo[1](2).html"),
    # http://greenbytes.de/tech/tc2231/#attfnbrokentokenutf
    # Note: tc2231 says we should fail to parse this header.
    (b"attachment; filename=foo-\xc3\xa4.html", "attachment", "foo-ä.html"),
    # http://greenbytes.de/tech/tc2231/#attmissingdisposition
    # Note: tc2231 says we should fail to parse this header.
    (b"filename=foo.html", "inline", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attmissingdisposition2
    # Note: tc2231 says we should fail to parse this header.
    (b"x=y; filename=foo.html", "inline", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attmissingdisposition3
    # Note: tc2231 says we should fail to parse this header.
    (b'"foo; filename=bar;baz"; filename=qux', "inline", ""),  # Firefox gets qux
    # http://greenbytes.de/tech/tc2231/#attmissingdisposition4
    # Note: tc2231 says we should fail to parse this header.
    (b"filename=foo.html, filename=bar.html", "inline", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#emptydisposition
    # Note: tc2231 says we should fail to parse this header.
    (b"; filename=foo.html", "inline", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attandinline
    # Note: tc2231 says we should fail to parse this header.
    (b"inline; attachment; filename=foo.html", "inline", ""),
    # http://greenbytes.de/tech/tc2231/#attandinline2
    # Note: tc2231 says we should fail to parse this header.
    (b"attachment; inline; filename=foo.html", "attachment", ""),
    # http://greenbytes.de/tech/tc2231/#attbrokenquotedfn
    # Note: tc2231 says we should fail to parse this header.
    (b'attachment; filename="foo.html".txt', "attachment", 'foo.html".txt'),
    # http://greenbytes.de/tech/tc2231/#attbrokenquotedfn2
    # Note: tc2231 says we should fail to parse this header.
    (b'attachment; filename="bar', "attachment", "bar"),
    # http://greenbytes.de/tech/tc2231/#attbrokenquotedfn3
    # Note: tc2231 says we should fail to parse this header.
    (b'attachment; filename=foo"bar;baz"qux', "attachment", 'foo"bar;baz"qux'),
    # http://greenbytes.de/tech/tc2231/#attmultinstances
    # Note: tc2231 says we should fail to parse this header.
    (b"attachment; filename=foo.html, attachment; filename=bar.html", "attachment", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attmissingdelim
    (b"attachment; foo=foo filename=bar", "attachment", ""),
    # http://greenbytes.de/tech/tc2231/#attreversed
    # Note: tc2231 says we should fail to parse this header.
    (b"filename=foo.html; attachment", "inline", "foo.html"),
    # http://greenbytes.de/tech/tc2231/#attconfusedparam
    (b"attachment; xfilename=foo.html", "attachment", ""),
    # http://greenbytes.de/tech/tc2231/#attabspath
    (b'attachment; filename="/foo.html"', "attachment", "/foo.html"),
    # http://greenbytes.de/tech/tc2231/#attabspathwin
    (b'attachment; filename="\\\\foo.html"', "attachment", "\\foo.html"),
    # http://greenbytes.de/tech/tc2231/#dispext
    (b"foobar", "attachment", ""),
    # http://greenbytes.de/tech/tc2231/#dispextbadfn
    (b'attachment; example="filename=example.txt"', "attachment", ""),
    # http://greenbytes.de/tech/tc2231/#attnewandfn
    (b'attachment; foobar=x; filename="foo.html"', "attachment", "foo.html"),
]


@pytest.mark.parametrize(("header", "expected_type", "expected_filename"), TC2231_CASES)
def test_tc2231(header: bytes, expected_type: str, expected_filename: str) -> None:
    parsed = parse_content_disposition(header)
    assert parsed.type == expected_type
    assert parsed.filename == (expected_filename or None)


# ParseResult: Chromium checks flags. The HAS_FILENAME and HAS_EXT_FILENAME
# flags say whether a usable filename came out, which is what is checked here.
PARSE_RESULT_CASES: list[tuple[bytes, bool]] = [
    # Basic feature tests
    (b"", False),
    (b"example=x", False),
    (b"attachment; filename=", False),
    (b"attachment; name=", False),
    (b"attachment; filename*=", False),
    (b"attachment; filename==?utf-8?Q??=", False),
    (b"filename=x", True),
    (b"example; filename=x", True),
    (b"attachment; filename=x", True),
    (b"attachment; filename='x'", True),
    (b"attachment; filename=x; name=y", True),
    (b"attachment; name=y; filename*=utf-8''foo; name=x", True),
    # Feature tests for 'filename' attribute.
    (b"filename=foo\xcc\x88", True),
    (b"filename=foo%cc%88", True),
    (b"filename==?utf-8?Q?foo?=", True),
    (b'filename="=?utf-8?Q?foo?="', True),
    (b"filename==?utf-8?Q?foo?", False),
    # Test 'name' isn't a synonym for 'filename'.
    (b"name=foo\xcc\x88", False),
    # Shouldn't set |has_non_ascii_strings| based on 'name' attribute.
    (b"filename=x; name=foo\xcc\x88", True),
    (b"filename=foo\xcc\x88 foo%cc%88 =?utf-8?Q?foo?=", True),
    # If 'filename' attribute is invalid, should set any flags based on it.
    (b"filename=foo\xcc\x88 foo%cc%88 =?utf-8?Q?foo?", False),
    (b"filename=foo\xcc\x88 foo%cc%88 =?utf-8?Q?foo?; name=x", False),
]


@pytest.mark.parametrize(("header", "has_filename"), PARSE_RESULT_CASES)
def test_parse_result(header: bytes, has_filename: bool) -> None:
    parsed = parse_content_disposition(header, fallback_charset="utf-8")
    assert (parsed.filename is not None) == has_filename


@pytest.mark.parametrize(
    ("header", "expected_type"),
    [(b"example; filename=x", "attachment"), (b"filename=x", "inline")],
)
def test_parse_result_disposition_type(header: bytes, expected_type: str) -> None:
    assert parse_content_disposition(header).type == expected_type


def test_contains_nul() -> None:
    # Chromium runs this case only through HttpContentDisposition's
    # constructor that takes a string, which parses the first comma-separated
    # value as it is: NULs are not allowed in HTTP headers, and the network
    # stack refuses a response whose headers hold one (see test_headers.py).
    # Both the header and the expected filename include a trailing NUL.
    header = first_comma_separated_value(b"filename=ab\0c\0")
    parsed = _parse(header, require_charset("utf-8"))
    assert parsed.filename == "ab\0c\0"


def test_no_content_disposition() -> None:
    parsed = parse_content_disposition(None, fallback_charset="utf-8")
    assert parsed.type == "inline"
    assert not parsed.is_attachment
    assert parsed.filename is None


def test_multiple_content_disposition() -> None:
    # A single header with comma-separated values is treated just as if
    # there were multiple Content-Disposition headers: only the first counts.
    parsed = parse_content_disposition(
        b"inline; filename=abc.pdf, attachment; filename=def.pdf", fallback_charset="utf-8"
    )
    assert not parsed.is_attachment
    assert parsed.type == "inline"
    assert parsed.filename == "abc.pdf"
