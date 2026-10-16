# Usage

## Name a download

`suggested_filename` downloads nothing. Make the request with your HTTP library
as usual, then give the package what the response says: its Content-Disposition
header and its URL. With a streaming response, both are there before you read
the body.

```pycon
>>> from browser_download_filename import parse_content_disposition, suggested_filename
>>> suggested_filename(content_disposition='attachment; filename="Q3 report.pdf"')
'Q3 report.pdf'
>>> suggested_filename(
...     url="https://example.com/files/report.pdf",
...     content_disposition='attachment; filename="Q3 report.pdf"',
... )
'Q3 report.pdf'
>>> suggested_filename(
...     url="https://example.com/files/report.pdf?id=1", content_disposition="attachment"
... )
'report.pdf'
>>> suggested_filename(content_disposition="attachment")
'download'
```

Chrome takes the name from the first of these that gives one:

1. `content_disposition`, the Content-Disposition header, or the
   Content-Disposition lines in `headers` (see [Several Content-Disposition
   headers](#several-content-disposition-headers)); leave both out when the
   response has none;
2. `download_attribute`, the value of an `<a download>` attribute (see
   [The download attribute](#the-download-attribute));
3. `url`, the URL: the last segment of its path, percent-decoded, without the
   query string (`about:` and `data:` URLs give none);
4. `default_name`, which is `download` unless you pass another (see
   [The default name](#the-default-name)).

`url` is the final URL of the response, after redirects. It only matters
when the header gives no name, for example when the response has no
Content-Disposition, when the header has neither `filename` nor `filename*`,
or when the name in it cannot be decoded (see
[Decode legacy charsets](#decode-legacy-charsets)). Leave it out when you have
no URL, and Chrome goes on to `default_name` instead. When the name comes from
a URL with a query string, `content_type` may also replace its extension (see
[Add an extension from the Content-Type](#add-an-extension-from-the-content-type)).

The result is always one non-empty file name: it never contains `/` or `\`,
control characters or other characters that file systems reject, and it never
starts or ends with a dot or a space. Put it in the directory of your choice:

```python
from pathlib import Path

path = Path(download_dir) / name
```

The package only suggests a name; it does not touch the file system. Two
things are up to you: the name can be longer than the file system allows (ext4
on Linux, for example, takes at most 255 bytes per file name, which is about 85
Chinese characters in UTF-8), and a file with that name may already exist
(Chrome numbers the new one: `report (1).pdf`).

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
    url=response.url,
    content_disposition=header.encode("latin-1") if header is not None else None,
)
```

httpx and httpx2 decode all headers of a response with one codec and tell you
which. They do not follow redirects unless asked, and `response.url` is a URL
object. With a streaming response, name the file before you read the body. The
code is the same for httpx2, with `httpx` replaced by `httpx2`:

```python
from pathlib import Path

import httpx
from browser_download_filename import suggested_filename

with httpx.stream("GET", url, follow_redirects=True) as response:
    response.raise_for_status()
    header = response.headers.get("Content-Disposition")
    name = suggested_filename(
        url=str(response.url),
        content_disposition=(
            header.encode(response.headers.encoding) if header is not None else None
        ),
    )
    with open(Path(download_dir) / name, "wb") as file:
        for chunk in response.iter_bytes():
            file.write(chunk)
```

aiohttp decodes headers as UTF-8 and keeps the bytes it cannot decode as
surrogate escapes, which the package turns back into those bytes, so its str
can be passed as it is:

```python
async with session.get(url) as response:
    name = suggested_filename(
        url=str(response.url),
        content_disposition=response.headers.get("Content-Disposition"),
    )
```

A str works in the other cases too, as long as the header is ASCII or UTF-8,
which is almost always the case: a str of Latin-1 characters whose Latin-1
bytes are valid UTF-8 is read as those bytes, and any other str is encoded as
UTF-8. Only a header with bytes in a legacy charset, such as `caf\xe9.txt` in
Windows-1252, comes out differently from a str, because the str cannot tell
those bytes apart from text. Pass the codec your HTTP library decoded the
headers with as `headers_encoding`, and a str gives back the bytes exactly (see
[Inputs as str](api-reference.md#inputs-as-str)).

### Several Content-Disposition headers

A response can send Content-Disposition more than once: in several header
lines, or as values joined with commas in one line. Chromium splits every line
on commas outside quotes and names the file from the first value. If any value
differs from the first, Chrome refuses the whole response
(`ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION`). That also happens with a
single header that has a comma outside quotes, such as
`attachment; filename=a,b.txt`.

The package sees every value only when you give it the whole headers. For one
name, requests, httpx and httpx2 return repeated headers joined with `, `, but
`urllib.request` and aiohttp return only the first one. Pass `response.headers`
to `suggested_filename`, as its first argument, or to
`parse_content_disposition`, whose `blocks_download` tells you whether Chrome
refuses the response:

```pycon
>>> headers = [
...     ("Content-Disposition", 'attachment; filename="a.pdf"'),
...     ("Content-Disposition", 'attachment; filename="b.pdf"'),
... ]
>>> parse_content_disposition(headers)
ContentDisposition(type='attachment', filename='a.pdf', blocks_download=True)
>>> suggested_filename(headers, url="https://example.com/get")
'a.pdf'
>>> parse_content_disposition("attachment; filename=a,b.txt")
ContentDisposition(type='attachment', filename='a', blocks_download=True)
```

When Chrome refuses a response, a plain link to it downloads nothing: Chrome
shows an error page instead. A link with a `download` attribute still starts a
download, which fails; Chrome names it from the attribute or the URL, without
the Content-Disposition and the Content-Type of the response.
`suggested_filename` does not model the refusal: it names the file from the
first value all the same, `a.pdf` above.

## Add an extension from the Content-Type

Pass the response's Content-Type, as str or bytes, as `content_type` to get
Chrome's extension rules:

```pycon
>>> suggested_filename(url="https://example.com/report", content_type="application/pdf")
'report.pdf'
>>> suggested_filename(url="https://example.com/get.php?id=1", content_type="application/pdf")
'get.pdf'
>>> suggested_filename(url="https://example.com/get.php", content_type="application/pdf")
'get.php'
>>> suggested_filename(
...     url="https://example.com/x",
...     content_disposition='attachment; filename="report"',
...     content_type="application/pdf",
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
>>> suggested_filename(url="https://example.com/get", content_disposition=header)
'get'
>>> suggested_filename(
...     url="https://example.com/get", content_disposition=header, fallback_charset="windows-1252"
... )
'café.txt'
>>> suggested_filename(url="https://example.com/%A4%A4%A4%E5.txt", fallback_charset="big5")
'中文.txt'
```

The name must be a label Chromium accepts, which are the labels of the [WHATWG
Encoding Standard](https://encoding.spec.whatwg.org/#names-and-labels);
`LookupError` is raised for others, such as `utf-7`. As in browsers,
`iso-8859-1`, `latin1` and `us-ascii` mean windows-1252.

## Windows

`platform` picks Chrome's rules for Linux, macOS and other POSIX systems
(`"posix"`) or for Windows (`"windows"`). By default it follows the operating
system the code runs on: Windows' rules on Windows, the POSIX rules everywhere
else. To get the same name wherever the code runs, pass `platform="posix"` or
`platform="windows"`, for example when the file will be saved on another
machine:

```pycon
>>> suggested_filename(content_disposition='attachment; filename="con.txt"', platform="posix")
'con.txt'
>>> suggested_filename(content_disposition='attachment; filename="con.txt"', platform="windows")
'_con.txt'
>>> suggested_filename(content_disposition='attachment; filename="report.pdf..."', platform="windows")
'report.pdf___'
>>> suggested_filename(content_disposition='attachment; filename="invoice.pdf.lnk"', platform="windows")
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

The value of an `<a download="...">` attribute is `download_attribute`. A name
from Content-Disposition comes before it; the URL comes after:

```pycon
>>> suggested_filename(url="https://example.com/files/1234", download_attribute="notes.txt")
'notes.txt'
>>> suggested_filename(
...     url="https://example.com/files/1234",
...     content_disposition='attachment; filename="server.txt"',
...     download_attribute="notes.txt",
... )
'server.txt'
```

Chrome ignores the attribute on links to another origin, so pass it only for
links to the same origin and for `data:` and `blob:` URLs.

## The default name

`default_name` is the name used when nothing else gives one, or when what
does is made only of `-` and `_`. `download` is the default name DevTools uses.
With `default_name=None`, the URL's host is used when nothing else gives a
name, if there is one, and `download` otherwise. An empty `default_name` raises
`ValueError`.

```pycon
>>> suggested_filename(url="https://example.com/", default_name="untitled")
'untitled'
>>> suggested_filename(url="https://example.com/", default_name=None)
'example.com'
```

## Sanitize a name

`sanitize_filename` applies Chrome's cleaning rules to a name from anywhere
else, such as a page title or user input. It cleans the name as Chrome cleans
an `<a download>` value, so the result is as safe to save under as what
`suggested_filename` returns:

```pycon
>>> from browser_download_filename import sanitize_filename
>>> sanitize_filename("Q3 report: draft?.pdf")
'Q3 report_ draft_.pdf'
>>> sanitize_filename("季度報告.pdf")
'季度報告.pdf'
>>> sanitize_filename("../../etc/passwd")
'_.._etc_passwd'
>>> sanitize_filename("con.txt", platform="windows")
'_con.txt'
>>> sanitize_filename("...", default_name="untitled")
'untitled'
```

`default_name` and `platform` work as in `suggested_filename`, except that
`default_name` cannot be `None`: there is no URL to take a host from.

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
ContentDisposition(type='inline', filename=None, blocks_download=False)
>>> parse_content_disposition(None)
ContentDisposition(type='inline', filename=None, blocks_download=False)
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
| Your own URL fallback and file name cleaning | `suggested_filename(url=url, content_disposition=header)` |
| Your own cleaning of a name from elsewhere | `sanitize_filename(name)` |

`parse_content_disposition` never raises on a malformed header and returns
`None` when there is no usable name. Its results differ from parsers that
follow the RFCs strictly wherever Chromium does, which is the point.
