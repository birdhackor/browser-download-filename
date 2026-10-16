# API reference

Everything below is importable from `browser_download_filename`. See
[Usage](usage.md) for examples.

## suggested_filename

```python
def suggested_filename(
    url: str | None,
    content_disposition: str | bytes | None = None,
    *,
    suggested_name: str | None = None,
    mime_type: str | None = None,
    default_name: str = "download",
    fallback_charset: str | None = None,
    platform: Literal["posix", "windows"] = "posix",
) -> str
```

The file name Chromium suggests for a download (`net::GetSuggestedFilename`),
which is the name Chrome reports to DevTools and Playwright. It is never empty.

| Parameter | Meaning |
| --- | --- |
| `url` | The final URL of the response, after redirects. `None` for no URL. |
| `content_disposition` | The Content-Disposition header, as bytes or as the str an HTTP library produced; `None` when the response has none. Only its first comma-separated value is used. |
| `suggested_name` | The value of an `<a download>` attribute. Used when Content-Disposition gives no name. |
| `mime_type` | The response's Content-Type; parameters are ignored. It adds or corrects an extension when the name does not come from Content-Disposition. |
| `default_name` | The name when nothing else gives one. If empty, the URL's host is tried first, and `download` is the last resort. |
| `fallback_charset` | A charset for raw bytes that are not UTF-8, in `filename` and in the URL's path; Chrome uses the browser's default text encoding here. A label Chromium knows, such as `"windows-1252"` or `"big5"`. |
| `platform` | `"posix"` for Chrome's rules on Linux, macOS and other POSIX systems, `"windows"` for its rules on Windows. |

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
| `TypeError` | A header value is not str, bytes or `None`; `url`, `suggested_name`, `mime_type` or `fallback_charset` is not str or `None`; or `default_name` is not a str. |
| `ValueError` | `platform` is not `"posix"` or `"windows"`. |

## Inputs as str

Chromium reads headers as bytes, so a str is mapped back to bytes first. If
every character is in U+0000–U+00FF and their Latin-1 bytes are valid UTF-8,
those bytes are used; that is how requests, urllib3, `http.client` and WSGI
pass on a header that carried UTF-8. Any other str is encoded as UTF-8, with
the surrogate escapes that aiohttp uses for undecodable bytes turned back into
those bytes. URLs and the other str arguments are taken as text; lone
surrogates in them become U+FFFD.
