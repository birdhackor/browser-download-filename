"""A response's headers given as a whole, and repeated Content-Disposition."""

from __future__ import annotations

import io
from collections.abc import Iterator
from http.client import HTTPMessage, parse_headers

import pytest

from browser_download_filename import (
    ContentDisposition,
    HeadersLike,
    parse_content_disposition,
    suggested_filename,
)

URL = "https://example.com/files/from-url.bin"
A = b'attachment; filename="a.txt"'
B = b'attachment; filename="b.txt"'


def _message(*lines: bytes) -> HTTPMessage:
    """Headers as http.client and urllib.request give them."""
    return parse_headers(io.BytesIO(b"".join(line + b"\r\n" for line in lines) + b"\r\n"))


class ItemsOnly:
    """Headers with an items() method and no other way to read them."""

    def __init__(self, pairs: list[tuple[str, bytes]]) -> None:
        self._pairs = pairs

    def items(self) -> list[tuple[str, bytes]]:
        return list(self._pairs)


# Typed as HeadersLike, so that mypy checks that each shape is one.
SHAPES: dict[str, HeadersLike] = {
    "dict": {"Content-Disposition": A.decode()},
    "pairs": [("Content-Disposition", A)],
    "tuple-of-pairs": (("Content-Disposition", A),),
    "bytes-name": [(b"Content-Disposition", A)],
    "list-values": {b"Content-Disposition": [A], b"Content-Type": [b"text/plain"]},
    "tuple-value": [("Content-Disposition", (A,))],
    "http-client": _message(b"Content-Type: text/plain", b"Content-Disposition: " + A),
    "items-only": ItemsOnly([("Content-Disposition", A)]),
}


@pytest.mark.parametrize("headers", SHAPES.values(), ids=SHAPES.keys())
def test_shapes(headers: HeadersLike) -> None:
    assert parse_content_disposition(headers) == ContentDisposition("attachment", "a.txt")
    assert suggested_filename(headers, url=URL) == "a.txt"


def test_pairs_can_be_lists() -> None:
    # As JSON gives them. HeadersLike leaves this shape out: a list type
    # cannot say that it holds a name and then a value.
    headers: list[list[str]] = [["Content-Disposition", A.decode()]]
    assert parse_content_disposition(headers) == ContentDisposition("attachment", "a.txt")  # type: ignore[arg-type]


def test_no_content_disposition() -> None:
    empty: list[HeadersLike] = [
        {},
        [],
        [("Content-Type", "text/plain")],
        {"Content-Disposition": []},
    ]
    for headers in empty:
        assert parse_content_disposition(headers) == ContentDisposition("inline", None)
        assert suggested_filename(headers, url=URL) == "from-url.bin"
    assert suggested_filename(None, url=URL) == "from-url.bin"


def test_names_match_in_any_ascii_case() -> None:
    headers: list[tuple[str | bytes, bytes]] = [
        ("cONTENT-dISPOSITION", A),
        (b"CONTENT-DISPOSITION", B),
    ]
    assert parse_content_disposition(headers) == ContentDisposition("attachment", "a.txt", True)
    # U+017F LATIN SMALL LETTER LONG S casefolds to "s", but it is no ASCII
    # letter, so the name is another one.
    assert parse_content_disposition([("Content-Dispo\u017fition", A)]).filename is None


@pytest.mark.parametrize(
    "name",
    [
        b"Content-Disposition\xff",
        b"\xff",
        "Content-Disposition\u00e9",
        "Content-Disposition\ud800",
        # The byte 0xFF as a surrogate escape, as aiohttp keeps it.
        b"Content-Disposition\xff".decode("ascii", "surrogateescape"),
    ],
    ids=["bytes-xff", "bytes-only-xff", "str-non-ascii", "str-lone-surrogate", "str-escaped-byte"],
)
def test_non_ascii_header_names_never_raise_and_are_not_content_disposition(
    name: str | bytes,
) -> None:
    headers: list[tuple[str | bytes, bytes]] = [(name, B)]
    assert parse_content_disposition(headers) == ContentDisposition("inline", None)
    assert suggested_filename(headers, url=URL) == "from-url.bin"
    # A real Content-Disposition line after it is still the first one.
    headers.append(("Content-Disposition", A))
    assert parse_content_disposition(headers) == ContentDisposition("attachment", "a.txt")
    assert suggested_filename(headers, url=URL) == "a.txt"


def test_lines_keep_their_order() -> None:
    headers: list[tuple[str, str | bytes]] = [
        ("Content-Disposition", B),
        ("Content-Type", "text/plain"),
        ("content-disposition", A),
    ]
    assert parse_content_disposition(headers) == ContentDisposition("attachment", "b.txt", True)
    assert suggested_filename(headers, url=URL) == "b.txt"
    assert suggested_filename(headers[::-1], url=URL) == "a.txt"
    assert suggested_filename({b"Content-Disposition": [B, A]}, url=URL) == "b.txt"
    message = _message(b"Content-Disposition: " + B, b"Content-Disposition: " + A)
    assert parse_content_disposition(message) == ContentDisposition("attachment", "b.txt", True)


def test_headers_are_read_once() -> None:
    def pairs() -> Iterator[tuple[str, bytes]]:
        yield ("Content-Disposition", A)
        yield ("Content-Disposition", B)

    assert parse_content_disposition(pairs()) == ContentDisposition("attachment", "a.txt", True)
    assert suggested_filename(pairs(), url=URL) == "a.txt"

    class OneShotItems:
        """items() hands out the same generator every time."""

        def __init__(self) -> None:
            self._pairs = pairs()

        def items(self) -> Iterator[tuple[str, bytes]]:
            return self._pairs

    assert parse_content_disposition(OneShotItems()) == ContentDisposition(
        "attachment", "a.txt", True
    )
    assert suggested_filename(OneShotItems(), url=URL) == "a.txt"


def test_lines_and_joined_values_are_the_same() -> None:
    joined = A + b", " + B
    expected = ContentDisposition("attachment", "a.txt", True)
    assert parse_content_disposition([("Content-Disposition", A), ("Content-Disposition", B)]) == (
        expected
    )
    assert parse_content_disposition([("Content-Disposition", joined)]) == expected
    assert parse_content_disposition(joined) == expected


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        # The same value, on several lines or joined with commas.
        ([A, A], ContentDisposition("attachment", "a.txt")),
        ([A, A + b", " + A], ContentDisposition("attachment", "a.txt")),
        # Spaces and tabs around a value do not count.
        ([b"attachment , attachment\t,attachment"], ContentDisposition("attachment", None)),
        # A comma inside quotes does not split the value.
        ([b'attachment; filename="a,b.txt"'], ContentDisposition("attachment", "a,b.txt")),
        (
            [b'attachment; filename="a,b.txt"', b'attachment; filename="a,b.txt"'],
            ContentDisposition("attachment", "a,b.txt"),
        ),
        # Values that differ: the first one still gives the type and name.
        ([A, B], ContentDisposition("attachment", "a.txt", True)),
        ([A, A, B], ContentDisposition("attachment", "a.txt", True)),
        ([b"inline; filename=a.pdf, attachment"], ContentDisposition("inline", "a.pdf", True)),
        ([b"attachment; filename=a,b.txt"], ContentDisposition("attachment", "a", True)),
        # Values are compared byte for byte.
        ([A, A.upper()], ContentDisposition("attachment", "a.txt", True)),
        # An empty value counts as a value.
        ([b"attachment,"], ContentDisposition("attachment", None, True)),
        ([b",attachment"], ContentDisposition("inline", None, True)),
        ([A, b""], ContentDisposition("attachment", "a.txt", True)),
        ([b""], ContentDisposition("inline", None)),
    ],
)
def test_blocks_download(lines: list[bytes], expected: ContentDisposition) -> None:
    headers = [("Content-Disposition", line) for line in lines]
    assert parse_content_disposition(headers) == expected
    # suggested_filename names the file from the first value regardless.
    assert suggested_filename(headers, url=URL) == (expected.filename or "from-url.bin")


def test_content_disposition_argument_replaces_the_headers() -> None:
    headers = [("Content-Disposition", b'attachment; filename="server.txt"')]
    assert suggested_filename(headers, url=URL) == "server.txt"
    assert suggested_filename(headers, url=URL, content_disposition=None) == "server.txt"
    assert suggested_filename(headers, url=URL, content_disposition=A) == "a.txt"
    # Even an empty value replaces them, so the server's name is ignored.
    assert suggested_filename(headers, url=URL, content_disposition="") == "from-url.bin"
    assert suggested_filename(headers, url=URL, content_disposition=b"") == "from-url.bin"
    # Every line is replaced, not only the first.
    headers += [("Content-Disposition", B)]
    assert suggested_filename(headers, url=URL, content_disposition="attachment") == (
        "from-url.bin"
    )


@pytest.mark.parametrize(
    "headers",
    ["attachment", "https://example.com/a.pdf", A, bytearray(A), memoryview(A)],
    ids=["str", "url", "bytes", "bytearray", "memoryview"],
)
def test_one_header_is_not_headers(headers: object) -> None:
    with pytest.raises(TypeError, match=r"content_disposition=, or a URL as url=$"):
        suggested_filename(headers)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        (5, "must be .*mapping"),
        (object(), "must be .*mapping"),
        (["Content-Disposition"], r"a \(name, value\) pair, not str"),
        ([("Content-Disposition",)], "pair, not a tuple of length 1"),
        ([("Content-Disposition", A, A)], "pair, not a tuple of length 3"),
        ([(5, A)], "header name must be str or bytes, not int"),
        ([(bytearray(b"Content-Disposition"), A)], "header name"),
        ([("Content-Disposition", None)], "header value must be .*, not NoneType"),
        ({"Content-Disposition": 5}, "header value must be .*, not int"),
        ([("Content-Disposition", [A, 5])], "header value must be .*, not int"),
        ([("Content-Disposition", [[A]])], "header value must be .*, not list"),
    ],
)
def test_malformed_headers_raise(headers: object, message: str) -> None:
    with pytest.raises(TypeError, match=message):
        suggested_filename(headers)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=message):
        parse_content_disposition(headers)  # type: ignore[arg-type]


def test_every_header_is_checked() -> None:
    # A bad header after Content-Disposition is reported too, and so is one
    # in a header the package does not read.
    for headers in ([("Content-Disposition", A), ("X-Count", 5)], [("X-Count", 5)]):
        with pytest.raises(TypeError, match="header value"):
            suggested_filename(headers)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="header value"):
            parse_content_disposition(headers)  # type: ignore[arg-type]


# --- Header lines as they were sent -------------------------------------------

# Content-Disposition values with line breaks, and the names Chromium gives
# for them on the wire, for a URL that ends in /<id>.bin. A line that starts
# with a space or a tab continues the header; any other line is another one.
LINE_BREAKS: dict[str, tuple[bytes, str]] = {
    "folded": (b"attachment;\r\n filename=wire.pdf", "wire.pdf"),
    "folded-with-lf": (b"attachment;\n filename=wire.pdf", "wire.pdf"),
    "folded-with-a-lone-cr": (b"attachment;\r filename=wire.pdf", "wire.pdf"),
    "folded-onto-an-empty-line": (b"\r\n attachment; filename=wire.pdf", "wire.pdf"),
    "folded-in-quotes": (b'attachment; filename="wire\r\n\t file.pdf"', "wire file.pdf"),
    "folded-after-spaces": (b'attachment; filename="wire\r\n   file.pdf"', "wire file.pdf"),
    # The spaces and tabs before the line break stay; each continued line
    # adds one space, even one made only of spaces and tabs.
    "folded-after-a-space": (b'attachment; filename="a \r\n b.pdf"', "a  b.pdf"),
    "folded-after-a-tab": (b'attachment; filename="a\t\r\n\tb.pdf"', "a  b.pdf"),
    "folded-twice-after-a-space": (b'attachment; filename="a\r\n b \r\n c.pdf"', "a b  c.pdf"),
    "folded-lines-of-spaces": (b'attachment; filename="a\r\n   \r\n\t\r\n  b.pdf"', "a   b.pdf"),
    # A run of CRs and LFs is one line break, unless it holds a blank line.
    "folded-across-two-crs": (b"attachment;\n\r\r\n filename=wire.pdf", "wire.pdf"),
    "folded-across-cr-cr": (b"attachment;\r\r filename=wire.pdf", "wire.pdf"),
    "line-break-before-text": (b"attachment;\r\nfilename=wire.pdf", "line-break-before-text.bin"),
    "line-break-at-the-start": (
        b"\r\nattachment; filename=wire.pdf",
        "line-break-at-the-start.bin",
    ),
    # Only CR and LF break lines; a vertical tab or a form feed is no space.
    "line-break-before-a-vertical-tab": (
        b"attachment;\r\n\x0bfilename=wire.pdf",
        "line-break-before-a-vertical-tab.bin",
    ),
    "line-break-before-a-form-feed": (
        b"attachment;\r\n\x0cfilename=wire.pdf",
        "line-break-before-a-form-feed.bin",
    ),
    "vertical-tab-and-form-feed": (b'attachment; filename="a\x0bb\x0cc.txt"', "a_b_c.txt"),
    "lone-cr-before-another-header": (b"attachment; filename=wire.pdf\rX-Note: 1", "wire.pdf"),
    "lone-cr-before-content-type": (
        b"attachment; filename=noext\rContent-Type: image/png",
        "noext",
    ),
    # A blank line ends the headers.
    "blank-line": (b"attachment;\r\n\r\n filename=wire.pdf", "blank-line.bin"),
    "blank-line-of-lfs": (b"attachment;\n\n filename=wire.pdf", "blank-line-of-lfs.bin"),
    "blank-line-of-lf-cr-lf": (
        b"attachment;\n\r\n filename=wire.pdf",
        "blank-line-of-lf-cr-lf.bin",
    ),
    "blank-line-at-the-start": (
        b"\n\nattachment; filename=wire.pdf",
        "blank-line-at-the-start.bin",
    ),
    "lf-at-the-end": (b'attachment; filename="a.txt"\n', "a.txt"),
}


@pytest.mark.parametrize("case_id", LINE_BREAKS)
def test_line_breaks_in_a_value_are_read_as_on_the_wire(case_id: str) -> None:
    value, expected = LINE_BREAKS[case_id]
    url = f"https://example.com/{case_id}.bin"
    text = value.decode("latin-1")
    names = [
        suggested_filename([("Content-Disposition", value)], url=url, platform="posix"),
        suggested_filename({"Content-Disposition": [value]}, url=url, platform="posix"),
        suggested_filename(
            [("Content-Disposition", text)], url=url, headers_encoding="latin-1", platform="posix"
        ),
        suggested_filename(url=url, content_disposition=value, platform="posix"),
    ]
    assert names == [expected] * len(names)
    parsed = {
        parse_content_disposition(value),
        parse_content_disposition(text, headers_encoding="latin-1"),
        parse_content_disposition([("Content-Disposition", value)]),
    }
    assert len(parsed) == 1
    assert not parsed.pop().blocks_download


def test_content_type_and_options_are_read_as_on_the_wire() -> None:
    url = "https://example.com/page"
    nosniff = ("X-Content-Type-Options", b"nosniff")
    for content_type, expected in [
        (b"\r\n text/html", "page.html"),
        (b"text/html;\r\n\tcharset=utf-8", "page.html"),
        # The type ends at the space that the folded line brings.
        (b"text/\r\n html", "page"),
        (b"image/png\r\nX-Note: text/html", "page.png"),
        (b"text/html\r\n\r\nimage/png", "page.html"),
    ]:
        assert suggested_filename([("Content-Type", content_type), nosniff], url=url) == expected
        assert suggested_filename([nosniff], url=url, content_type=content_type) == expected
    # A folded nosniff stops the sniffing, so no Content-Type is text/plain.
    assert suggested_filename([("X-Content-Type-Options", b"\r\n nosniff")], url=url) == "page.txt"
    assert suggested_filename([("X-Content-Type-Options", b"\r\nnosniff")], url=url) == "page"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        # In Content-Disposition, in another header, and in a header name.
        ([("Content-Disposition", b"attachment; filename=wi\0re.pdf")], "wi_re.pdf"),
        ([("X-Note", b"a\0b"), ("Content-Disposition", A)], "a.txt"),
        ([("Content-Disposition", A), ("X-Note", "a\0b")], "a.txt"),
        ([(b"X-No\0te", b"a"), ("Content-Disposition", A)], "a.txt"),
        ([("X-No\0te", "a")], "from-url.bin"),
        ({"X-Note": [b"a", b"b\0"], "Content-Disposition": A}, "a.txt"),
        # After a line break, in a line that is not part of the value: it is
        # still in the headers.
        ([("Content-Disposition", A + b"\r\nX-Note: \0")], "a.txt"),
        ([("Content-Disposition", b"attachment;\r\n\0filename=wire.pdf")], "from-url.bin"),
    ],
)
def test_a_nul_in_the_headers_blocks_the_download(headers: HeadersLike, expected: str) -> None:
    assert parse_content_disposition(headers).blocks_download
    # suggested_filename names the file all the same, from the first value.
    assert suggested_filename(headers, url=URL, platform="posix") == expected


def test_a_nul_in_one_value_blocks_the_download() -> None:
    value = b"attachment; filename=wi\0re.pdf"
    blocked = ContentDisposition("attachment", "wi\0re.pdf", True)
    assert parse_content_disposition(value) == blocked
    assert parse_content_disposition(value.decode("ascii")) == blocked
    assert suggested_filename(url=URL, content_disposition=value) == "wi_re.pdf"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        # After a blank line, which ends the headers: it is in the body.
        ([("Content-Disposition", A + b"\r\n\r\n\0")], ContentDisposition("attachment", "a.txt")),
        ([("Content-Disposition", A + b"\n\n\0")], ContentDisposition("attachment", "a.txt")),
        (
            [("Content-Disposition", A), ("X-Note", b"a\n\r\n\0")],
            ContentDisposition("attachment", "a.txt"),
        ),
        # A name with no value has no line.
        ([("X-No\0te", [])], ContentDisposition("inline", None)),
    ],
)
def test_a_nul_outside_the_headers_does_not_block(
    headers: HeadersLike, expected: ContentDisposition
) -> None:
    assert parse_content_disposition(headers) == expected


def test_the_package_does_not_read_the_header_lines_that_values_make_on_the_wire() -> None:
    # Chromium reads a second Content-Disposition here, which differs from the
    # first, and refuses the response.
    second = b"attachment; filename=a.pdf\rContent-Disposition: attachment; filename=b.pdf"
    assert parse_content_disposition(second) == ContentDisposition("attachment", "a.pdf")
    assert suggested_filename(url=URL, content_disposition=second) == "a.pdf"
    # Chromium ends the headers at the blank line, and finds no
    # Content-Disposition after it.
    headers = [("X-Note", b"a\r\n\r\n"), ("Content-Disposition", A)]
    assert parse_content_disposition(headers) == ContentDisposition("attachment", "a.txt")
    assert suggested_filename(headers, url=URL) == "a.txt"
