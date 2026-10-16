# API reference

Everything below is importable from `browser_download_filename`. See
[Usage](usage.md) for examples.

## suggested_filename

```python
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
    platform: Literal["posix", "windows"] | None = None,
) -> str
```

The file name Chromium suggests for a download (`net::GetSuggestedFilename`),
which is the name Chrome reports to DevTools and Playwright. It is never empty.

| Parameter | Meaning |
| --- | --- |
| `headers` | The response's headers (see [`HeadersLike`](#headerslike)); `None` for none. Three headers are read from them: Content-Disposition, the first comma-separated value of its first line; every Content-Type line, for the MIME type; and X-Content-Type-Options, whose first value tells whether Chrome sniffs the body for another MIME type (see [The MIME type](behavior.md#the-mime-type)). |
| `url` | The final URL of the response, after redirects; `None` for no URL. Used only when Content-Disposition and `download_attribute` give no name: the last segment of its path (none for `about:` and `data:` URLs), else its host if `default_name` is `None`. |
| `content_disposition` | The Content-Disposition header, as bytes or as the str an HTTP library produced. `None`, the default, reads it from `headers`, if any. Any other value takes the place of every Content-Disposition line in `headers`, even an empty string: pass `""` to ignore the file name the server sent. Only its first comma-separated value is used. |
| `content_type` | The Content-Type header, as bytes or as the str an HTTP library produced. `None`, the default, reads it from `headers`, if any. Any other value takes the place of every Content-Type line in `headers`; an empty string is an empty Content-Type. The MIME type adds or corrects an extension when the name does not come from Content-Disposition; with neither `headers` nor `content_type`, no MIME type is used. |
| `download_attribute` | The value of an `<a download>` attribute. Used when Content-Disposition gives no name. |
| `default_name` | The name when nothing else gives one; it cannot be empty. With `None`, the URL's host is tried first, and `download` is the last resort. |
| `fallback_charset` | A charset for raw bytes that are not UTF-8, in `filename` and in the URL's path; Chrome uses the browser's default text encoding here. A label Chromium knows, such as `"windows-1252"` or `"big5"`. |
| `headers_encoding` | The Python codec your HTTP library decoded the headers with, such as `"latin-1"` for requests or `response.headers.encoding` for httpx. Every str header value, in `headers`, `content_disposition` and `content_type`, is encoded back to bytes with it; bytes are used as they are. `None` guesses the bytes instead (see [Inputs as str](#inputs-as-str)). It is a Python codec name, not a charset label: `"latin-1"` is ISO-8859-1 here, not windows-1252. |
| `platform` | `"posix"` for Chrome's rules on Linux, macOS and other POSIX systems, `"windows"` for its rules on Windows. `None`, the default, picks `"windows"` when the call runs on Windows (`sys.platform == "win32"`) and `"posix"` elsewhere. |

## sanitize_filename

```python
def sanitize_filename(
    name: str,
    *,
    default_name: str = "download",
    platform: Literal["posix", "windows"] | None = None,
) -> str
```

Chrome's file name cleaning, applied to a name from anywhere, such as a page
title or user input. The result is what
`suggested_filename(download_attribute=name, default_name=default_name, platform=platform)`
returns: `name` is cleaned as Chrome cleans an `<a download>` value. It is
never empty.

| Parameter | Meaning |
| --- | --- |
| `name` | The name to clean. |
| `default_name` | The name when `name` gives none, as in `suggested_filename`. A non-empty str. |
| `platform` | As in `suggested_filename`. |

## HeadersLike

```python
HeadersLike = SupportsHeaderItems | Iterable[tuple[str | bytes, HeaderValue]]
```

The type of a response's headers, in the shapes HTTP libraries hold them:

- an object with an `items()` method (`SupportsHeaderItems`), such as a dict,
  the `http.client.HTTPMessage` that `urllib.request` gives as
  `response.headers`, or the headers of requests, httpx and aiohttp; the
  package calls `items()`;
- otherwise, an iterable of `(name, value)` pairs, such as a list of tuples.

A name is a str or bytes, and names match whatever their ASCII case. A value
(`HeaderValue`) is a str or bytes, or a list or tuple of them, one for each
header line, as Scrapy gives them. The lines keep their order, and repeated
lines all count. The headers are read only once, so a generator works too.

A str or bytes is not headers: `suggested_filename` raises `TypeError` for one;
pass a single Content-Disposition value as `content_disposition`.

## parse_content_disposition

```python
def parse_content_disposition(
    value: str | bytes | HeadersLike | None,
    /,
    *,
    fallback_charset: str | None = None,
    headers_encoding: str | None = None,
) -> ContentDisposition
```

Parses Content-Disposition as Chromium's `net::HttpContentDisposition` does.
`value` is one header, as bytes or as the str an HTTP library produced; or a
response's headers (see [`HeadersLike`](#headerslike)), of which every
Content-Disposition line is read; `None` stands for a missing header. `type`
and `filename` come from the first comma-separated value of the first line,
which is the value Chrome's download code reads, and `blocks_download` says
whether Chrome refuses the response. `fallback_charset` and `headers_encoding`
are as above.

## ContentDisposition

```python
@dataclass(frozen=True, slots=True)
class ContentDisposition:
    type: Literal["inline", "attachment"]
    filename: str | None
    blocks_download: bool = False

    @property
    def is_attachment(self) -> bool: ...
```

A parsed header: an immutable value that compares and hashes by its fields.

| Attribute | Meaning |
| --- | --- |
| `type` | `"attachment"` for `attachment` and for any other valid disposition type Chromium does not know; `"inline"` for `inline`, a missing header, or a header that does not start with a valid type. |
| `filename` | The decoded file name, or `None` when the header has none that Chromium can use. It is not sanitized: it can contain path separators, control characters and other characters that are unsafe in a file name. |
| `blocks_download` | Whether Chrome refuses the whole response (`ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION`): `True` when the Content-Disposition values, split on commas outside quotes and trimmed of spaces and tabs, are not all the same, byte for byte. `type` and `filename` still come from the first value. See [Several Content-Disposition headers](usage.md#several-content-disposition-headers). |
| `is_attachment` | Whether `type` is `"attachment"`. |

## `__version__`

The installed version of the package, as a str.

## Exceptions

Malformed headers and URLs never raise; only invalid arguments do.

| Exception | When it occurs |
| --- | --- |
| `LookupError` | `fallback_charset` is not a charset Chromium can decode, such as `utf-7`; or `headers_encoding` is not a Python text codec, such as `rot13`. |
| `TypeError` | `headers` is a str or bytes; `headers`, or the `value` of `parse_content_disposition`, is not a [`HeadersLike`](#headerslike): neither a mapping nor an iterable, an item that is not a `(name, value)` pair, or a name or a value of another type; a header value or `content_type` is not str, bytes or `None`; `url`, `download_attribute`, `fallback_charset`, `headers_encoding` or the `default_name` of `suggested_filename` is not str or `None`; or `name` or the `default_name` of `sanitize_filename` is not a str. |
| `ValueError` | `platform` is not `"posix"`, `"windows"` or `None`; `default_name` is an empty string; or a str header value does not encode with `headers_encoding`, which means the headers were decoded with another codec. |

All of these are checked, for every header in `headers`, before any header is
parsed.

## Inputs as str

Chromium reads headers as bytes, so a str is mapped back to bytes first. With
`headers_encoding`, that is exact: the str is encoded with that codec, with
surrogate escapes turned back into the bytes they stand for
(`value.encode(headers_encoding, "surrogateescape")`).

Without it, the bytes are guessed. If every character is in U+0000–U+00FF and
their Latin-1 bytes are valid UTF-8, those bytes are used; that is how
requests, urllib3, `http.client` and WSGI pass on a header that carried UTF-8.
Any other str is encoded as UTF-8, with the surrogate escapes that aiohttp uses
for undecodable bytes turned back into those bytes. The guess can be wrong, for
example for bytes in a legacy charset that an HTTP library decoded as Latin-1,
such as `caf\xe9.txt` in windows-1252. It changes nothing in Content-Type and
X-Content-Type-Options, though: only ASCII characters can match a MIME type or
`nosniff`, and the guess always gives them back as the bytes they were.

URLs and the other str arguments are taken as text; lone surrogates in them
become U+FFFD.
