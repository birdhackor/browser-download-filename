# Usage

## Name a download

```pycon
>>> from browser_download_filename import parse_content_disposition, suggested_filename
>>> suggested_filename("https://example.com/files/report.pdf")
'report.pdf'
>>> suggested_filename("https://example.com/files/report.pdf", 'attachment; filename="Q3 report.pdf"')
'Q3 report.pdf'
>>> suggested_filename("https://example.com/")
'download'
```

The first argument is the final URL of the response, after redirects. The
second is the Content-Disposition header; leave it out or pass `None` when the
response has none.

The result is always one non-empty file name: it never contains `/` or `\`,
control characters or other characters that file systems reject, and it never
starts or ends with a dot or a space. Put it in the directory of your choice:

```python
from pathlib import Path

path = Path(download_dir) / name
```

When a file with that name already exists, Chrome numbers the new one
(`report (1).pdf`). This package does not look at the file system, so what to
do with an existing file is up to you.

## Pass the header from your HTTP library

Chromium reads the header as bytes. Python HTTP libraries decode headers to str
first, and each does it in its own way, so give the package the bytes when you
can.

requests, urllib3, `urllib.request` and `http.client` decode every header as
Latin-1; encoding the str back to Latin-1 gives the bytes exactly:

```python
import requests
from browser_download_filename import suggested_filename

response = requests.get(url)
header = response.headers.get("Content-Disposition")
name = suggested_filename(
    response.url,
    header.encode("latin-1") if header is not None else None,
)
```

httpx decodes all headers of a response with one codec and tells you which. It
also does not follow redirects unless asked, and its `response.url` is a URL
object:

```python
import httpx

response = httpx.get(url, follow_redirects=True)
header = response.headers.get("Content-Disposition")
name = suggested_filename(
    str(response.url),
    header.encode(response.headers.encoding) if header is not None else None,
)
```

aiohttp decodes headers as UTF-8 and keeps the bytes it cannot decode as
surrogate escapes, which the package turns back into those bytes, so its str
can be passed as it is:

```python
async with session.get(url) as response:
    name = suggested_filename(
        str(response.url),
        response.headers.get("Content-Disposition"),
    )
```

A str works in the other cases too, as long as the header is ASCII or UTF-8,
which is almost always the case: a str of Latin-1 characters whose Latin-1
bytes are valid UTF-8 is read as those bytes, and any other str is encoded as
UTF-8. Only a header with bytes in a legacy charset, such as `caf\xe9.txt` in
Windows-1252, comes out differently from a str, because the str cannot tell
those bytes apart from text.

### Several Content-Disposition headers

requests and httpx join repeated headers with `, `, and `urllib.request` and
aiohttp return the first one. Chromium splits the header on commas outside
quotes and uses the first value, and the package does too. If the values
differ, Chrome refuses the whole response
(`ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION`) and nothing is
downloaded. That also happens with a single header that has a comma outside
quotes, such as `attachment; filename=a,b.txt`. The package cannot see what
your HTTP library dropped, and it always returns a name: here, `a`.

## Add an extension from the Content-Type

Pass the response's Content-Type as `mime_type` to get Chrome's extension rules:

```pycon
>>> suggested_filename("https://example.com/report", mime_type="application/pdf")
'report.pdf'
>>> suggested_filename("https://example.com/get.php?id=1", mime_type="application/pdf")
'get.pdf'
>>> suggested_filename("https://example.com/get.php", mime_type="application/pdf")
'get.php'
>>> suggested_filename(
...     "https://example.com/x", 'attachment; filename="report"', mime_type="application/pdf"
... )
'report'
```

- A name without an extension gets the MIME type's usual extension.
- A name from a URL with a query string is taken to come from a script, so its
  extension is replaced unless it is already one of the MIME type's extensions.
- A name from Content-Disposition keeps exactly the extension it has, or the
  lack of one.
- Parameters such as `; charset=utf-8` are ignored, and so are
  `application/octet-stream` and MIME types that Chromium has no extension for.

If the server does not send `X-Content-Type-Options: nosniff`, Chrome may sniff
the content and use another MIME type than the header says; pass the one Chrome
would use.

## Decode legacy charsets

A `filename` in raw bytes that are not UTF-8, or a URL with %-escaped bytes
that are not UTF-8, has no charset of its own. Chrome decodes it with the
browser's default text encoding, a setting that follows the language of the
browser: windows-1252 for English, Big5 for Traditional Chinese, GBK for
Simplified Chinese, Shift_JIS for Japanese and so on. DevTools and Playwright
use no fallback, and neither does this package by default; Chromium on Linux
then drops the name and falls back to the URL. To get the name Chrome would
save, pass the encoding as `fallback_charset`:

```pycon
>>> header = b'attachment; filename="caf\xe9.txt"'
>>> suggested_filename("https://example.com/get", header)
'get'
>>> suggested_filename("https://example.com/get", header, fallback_charset="windows-1252")
'café.txt'
>>> suggested_filename("https://example.com/%A4%A4%A4%E5.txt", fallback_charset="big5")
'中文.txt'
```

The name must be a label Chromium accepts, which are the labels of the [WHATWG
Encoding Standard](https://encoding.spec.whatwg.org/#names-and-labels);
`LookupError` is raised for others, such as `utf-7`. As in browsers,
`iso-8859-1`, `latin1` and `us-ascii` mean windows-1252.

## Windows

`platform` picks Chrome's rules for Linux, macOS and other POSIX systems
(`"posix"`, the default) or for Windows (`"windows"`). Use `"windows"` when the
file will be saved on Windows:

```pycon
>>> suggested_filename("https://example.com/x", 'attachment; filename="con.txt"', platform="windows")
'_con.txt'
>>> suggested_filename(
...     "https://example.com/x", 'attachment; filename="report.pdf..."', platform="windows"
... )
'report.pdf___'
>>> suggested_filename(
...     "https://example.com/x", 'attachment; filename="invoice.pdf.lnk"', platform="windows"
... )
'invoice.pdf.download'
```

On Windows, Chrome also

- puts `_` before reserved device names (`CON`, `PRN`, `AUX`, `NUL`,
  `COM1`–`COM9`, `LPT1`–`LPT9`, `CLOCK$`, with or without an extension) and
  before `desktop.ini`, `thumbs.db`, `CONIN$` and `CONOUT$`;
- turns trailing dots and spaces into `_`, since Windows would drop them;
- gives `.download` to names whose extension Windows treats as a shortcut or
  a shell object (`.lnk`, `.local`, `.scf`, `.url` and `{CLSID}` extensions);
- replaces `~` in a name that could be an 8.3 short name, such as `REPORT~1.PDF`.

## The download attribute

The value of an `<a download="...">` attribute is `suggested_name`. A name
from Content-Disposition comes before it; the URL comes after:

```pycon
>>> suggested_filename("https://example.com/files/1234", suggested_name="notes.txt")
'notes.txt'
>>> suggested_filename(
...     "https://example.com/files/1234",
...     'attachment; filename="server.txt"',
...     suggested_name="notes.txt",
... )
'server.txt'
```

Chrome ignores the attribute on links to another origin, so pass it only for
links to the same origin and for `data:` and `blob:` URLs.

## The default name

`default_name` is the name used when nothing else gives one, or when what
does is made only of `-` and `_`. `download` is the default name DevTools uses.
With an empty `default_name`, the URL's host is used, if there is one:

```pycon
>>> suggested_filename("https://example.com/", default_name="untitled")
'untitled'
>>> suggested_filename("https://example.com/", default_name="")
'example.com'
```

## Parse a header

`parse_content_disposition` returns the disposition type and the file name
without the rest of the naming:

```pycon
>>> cd = parse_content_disposition('attachment; filename="../../etc/passwd"')
>>> cd.type, cd.is_attachment
('attachment', True)
>>> cd.filename
'../../etc/passwd'
>>> parse_content_disposition("inline")
ContentDisposition(type='inline', filename=None)
>>> parse_content_disposition(None)
ContentDisposition(type='inline', filename=None)
```

The file name is decoded but not sanitized: it can contain path separators,
control characters and anything else the server sent. Never use it as a path;
use `suggested_filename` for a name to save under. Types other than `inline`
and `attachment` count as `attachment`, as they do in Chromium.

## Replacing another parser

| Before | After |
| --- | --- |
| `pyrfc6266.parse_filename(header)` | `parse_content_disposition(header).filename` |
| `email.message.Message.get_filename()` | `parse_content_disposition(header).filename` |
| Your own URL fallback and file name cleaning | `suggested_filename(url, header)` |

`parse_content_disposition` never raises on a malformed header and returns
`None` when there is no usable name. Its results differ from parsers that
follow the RFCs strictly wherever Chromium does, which is the point.
