# API reference

Everything below is importable from `browser_download_filename`. See
[Usage](usage.md) for examples.

## suggested_filename

```python
def suggested_filename(
    *,
    url: str | None = None,
    content_disposition: str | bytes | None = None,
    content_type: str | bytes | None = None,
    download_attribute: str | None = None,
    default_name: str | None = "download",
    fallback_charset: str | None = None,
    platform: Literal["posix", "windows"] | None = None,
) -> str
```

The file name Chromium suggests for a download (`net::GetSuggestedFilename`),
which is the name Chrome reports to DevTools and Playwright. It is never empty.

| Parameter | Meaning |
| --- | --- |
| `url` | The final URL of the response, after redirects; `None` for no URL. Used only when Content-Disposition and `download_attribute` give no name: the last segment of its path (none for `about:` and `data:` URLs), else its host if `default_name` is `None`. |
| `content_disposition` | The Content-Disposition header, as bytes or as the str an HTTP library produced; `None` when the response has none. Only its first comma-separated value is used. |
| `content_type` | The response's Content-Type, as str or as bytes, which are read as Latin-1; parameters are ignored. It adds or corrects an extension when the name does not come from Content-Disposition. |
| `download_attribute` | The value of an `<a download>` attribute. Used when Content-Disposition gives no name. |
| `default_name` | The name when nothing else gives one; it cannot be empty. With `None`, the URL's host is tried first, and `download` is the last resort. |
| `fallback_charset` | A charset for raw bytes that are not UTF-8, in `filename` and in the URL's path; Chrome uses the browser's default text encoding here. A label Chromium knows, such as `"windows-1252"` or `"big5"`. |
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

## parse_content_disposition

```python
def parse_content_disposition(
    value: str | bytes | None,
    *,
    fallback_charset: str | None = None,
) -> ContentDisposition
```

Parses a Content-Disposition header as Chromium's `net::HttpContentDisposition`
does. `value` is the header as bytes, or as the str an HTTP library produced;
`None` stands for a missing header. Only its first comma-separated value is
used. `fallback_charset` is as above.

## ContentDisposition

```python
@dataclass(frozen=True, slots=True)
class ContentDisposition:
    type: Literal["inline", "attachment"]
    filename: str | None

    @property
    def is_attachment(self) -> bool: ...
```

A parsed header: an immutable value that compares and hashes by its fields.

| Attribute | Meaning |
| --- | --- |
| `type` | `"attachment"` for `attachment` and for any other valid disposition type Chromium does not know; `"inline"` for `inline`, a missing header, or a header that does not start with a valid type. |
| `filename` | The decoded file name, or `None` when the header has none that Chromium can use. It is not sanitized: it can contain path separators, control characters and other characters that are unsafe in a file name. |
| `is_attachment` | Whether `type` is `"attachment"`. |

## `__version__`

The installed version of the package, as a str.

## Exceptions

Malformed headers and URLs never raise; only invalid arguments do.

| Exception | When it occurs |
| --- | --- |
| `LookupError` | `fallback_charset` is not a charset Chromium can decode, such as `utf-7`. |
| `TypeError` | A header value or `content_type` is not str, bytes or `None`; `url`, `download_attribute`, `fallback_charset` or the `default_name` of `suggested_filename` is not str or `None`; or `name` or the `default_name` of `sanitize_filename` is not a str. |
| `ValueError` | `platform` is not `"posix"`, `"windows"` or `None`; or `default_name` is an empty string. |

## Inputs as str

Chromium reads headers as bytes, so a str is mapped back to bytes first. If
every character is in U+0000–U+00FF and their Latin-1 bytes are valid UTF-8,
those bytes are used; that is how requests, urllib3, `http.client` and WSGI
pass on a header that carried UTF-8. Any other str is encoded as UTF-8, with
the surrogate escapes that aiohttp uses for undecodable bytes turned back into
those bytes. URLs and the other str arguments are taken as text; lone
surrogates in them become U+FFFD.
