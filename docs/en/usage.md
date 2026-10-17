# Usage

## Name a download

`suggested_filename` downloads nothing. Make the request with your HTTP library
as usual, then give the package the response's headers, all of them, and its
URL. With a streaming response, both are there before you read the body. With
httpx2:

```python
from pathlib import Path

import httpx2
from browser_download_filename import suggested_filename

with httpx2.stream("GET", url, follow_redirects=True) as response:
    response.raise_for_status()
    name = suggested_filename(response.headers.raw, url=str(response.url))
    with open(Path(download_dir) / name, "wb") as file:
        for chunk in response.iter_bytes():
            file.write(chunk)
```

`response.headers.raw` holds the header lines in bytes, each line on its own.
httpx2 follows redirects only with `follow_redirects=True`, and `response.url`
is a URL object, which `str()` turns into the URL. The code is the same for
httpx, with `httpx2` replaced by `httpx`. For requests, aiohttp and
`urllib.request`, see [Pass the headers from your HTTP
library](#pass-the-headers-from-your-http-library).

The headers can also be a dict or a list of `(name, value)` pairs, with values
in bytes or str:

```pycon
>>> from browser_download_filename import parse_content_disposition, suggested_filename
>>> headers = [("Content-Disposition", 'attachment; filename="Q3 report.pdf"')]
>>> suggested_filename(headers, url="https://example.com/files/report.pdf")
'Q3 report.pdf'
>>> suggested_filename(headers)
'Q3 report.pdf'
>>> headers = [("Content-Disposition", "attachment")]
>>> suggested_filename(headers, url="https://example.com/files/report.pdf?id=1")
'report.pdf'
>>> suggested_filename(headers)
'download'
```

Chrome takes the name from the first of these that gives one:

1. Content-Disposition: the Content-Disposition lines in `headers` (see
   [Several Content-Disposition headers](#several-content-disposition-headers)),
   or `content_disposition`, which takes their place when you pass it;
2. `download_attribute`, the value of an `<a download>` attribute (see
   [The download attribute](#the-download-attribute));
3. `url`, the URL: the last segment of its path, percent-decoded, without the
   query string (`about:` and `data:` URLs give none);
4. `default_name`, which is `download` unless you pass another (see
   [The default name](#the-default-name)).

`url` is the final URL of the response, after redirects. It gives the name
only when Content-Disposition and `download_attribute` give none, for example
when the response has no Content-Disposition, when the header has neither
`filename` nor `filename*`, or when the name in it cannot be decoded (see
[Decode legacy charsets](#decode-legacy-charsets)). Leave it out when you have
no URL, and Chrome goes on to `default_name` instead.

The URL can also change the extension of a name that does not come from
Content-Disposition. When the name comes from a URL with a query string, the
response's MIME type may replace its extension (see
[Add an extension from the Content-Type](#add-an-extension-from-the-content-type)).
And the URL's scheme decides whether Chrome may sniff the body for a MIME
type: only `http:`, `https:`, `file:` and `filesystem:` URLs are sniffed, and
without a `url` the package assumes one of them (see
[The MIME type](behavior.md#the-mime-type)). Without sniffing, a response that
has no Content-Type is `text/plain`. Here `[]` is a response without headers:

```pycon
>>> suggested_filename([], download_attribute="saved", url="https://example.com/x")
'saved'
>>> suggested_filename([], download_attribute="saved", url="ftp://example.com/x")
'saved.txt'
```

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

## Pass the headers from your HTTP library

Chromium reads the header lines of a response as bytes, each line on its own.
Python HTTP libraries decode headers to str, and some join the lines of a
header that comes more than once. Each library here has a way to pass the
headers that gives the same name as the lines on the wire, except for header
lines that HTTP does not allow, such as folded lines, which some libraries
read otherwise than Chrome or refuse, and for headers larger than a library
takes (see [Joined lines and guessed bytes](#joined-lines-and-guessed-bytes)
and [Header lines that HTTP does not
allow](#header-lines-that-http-does-not-allow)):

| Library | `headers` | `headers_encoding` | Folded lines |
| --- | --- | --- | --- |
| httpx2, httpx | `response.headers.raw` | none: the lines are bytes | joined as in Chrome |
| aiohttp | `response.raw_headers` | none: the lines are bytes | joined, keeping the spaces and tabs that start the next line |
| requests | `response.raw.headers` | `"latin-1"` | after CR LF, one space in place of the spaces and tabs on both sides |
| `urllib.request` | `response.headers` | `"latin-1"` | as they came, for the package to join |

The last column is about folds after CR LF or LF; see [Joined lines and
guessed bytes](#joined-lines-and-guessed-bytes). For httpx2 and httpx, see
[Name a download](#name-a-download). aiohttp keeps every line in bytes in
`response.raw_headers`, and its `response.url` is a URL object too:

```python
async with session.get(url) as response:
    name = suggested_filename(response.raw_headers, url=str(response.url))
```

requests decodes headers as Latin-1, and its `response.headers` joins the
lines of a header into one. The urllib3 response under it, `response.raw`,
keeps every line, and `headers_encoding="latin-1"` turns the strs back into the
bytes exactly:

```python
with requests.get(url, stream=True) as response:
    name = suggested_filename(response.raw.headers, url=response.url, headers_encoding="latin-1")
```

`urllib.request` decodes headers as Latin-1 too, and its `response.headers`
keeps every line:

```python
with urllib.request.urlopen(url) as response:
    name = suggested_filename(response.headers, url=response.url, headers_encoding="latin-1")
```

### Joined lines and guessed bytes

The `response.headers` of requests, httpx and httpx2 join the lines of a header
into one, with `, `. Passed with `headers_encoding` (`"latin-1"` for requests,
`response.headers.encoding` for httpx and httpx2), they give the same result,
unless a Content-Disposition line other than the last leaves a quote open. In
the joined line, that quote runs on into the next line. On the first line, the
name can take in what follows; on any line, the values can change, and
`blocks_download` with them, so that it no longer tells whether Chrome refuses
the response (see [Reading
Content-Disposition](behavior.md#reading-content-disposition)).

A folded line, which goes on in the next line that starts with a space or a
tab, is joined on with one space in Chrome (see [Reading header
lines](behavior.md#reading-header-lines)). httpx2 and httpx join it the same
way, and `urllib.request` gives it as it came, for the package to join.
requests and aiohttp join it otherwise: requests also drops the spaces and
tabs before a CR LF line break, and aiohttp keeps all the spaces and tabs that
start the next line. Inside quotes, that changes the name:
`filename="a \r\n b.pdf"` is `a  b.pdf` in Chrome and `a b.pdf` with
requests, and `filename="wire\r\n\t file.pdf"` is `wire file.pdf` in Chrome
and `wire  file.pdf` with aiohttp. The package cannot undo either. A line
break with a lone CR in it, or with a line of nothing but CRs, is another
matter (see [Header lines that HTTP does not
allow](#header-lines-that-http-does-not-allow)).

Without `headers_encoding`, the package guesses the bytes behind each str (see
[Inputs as str](api-reference.md#inputs-as-str)). The guess can be wrong for
bytes in a legacy charset, such as `caf\xe9.txt` in windows-1252, that a
library decoded as Latin-1, and the name can then differ.

### Header lines that HTTP does not allow

Chrome reads some header lines that HTTP does not allow (see [Reading header
lines](behavior.md#reading-header-lines)), and the libraries do not all read
them as Chrome does:

- **NUL.** A NUL in the headers makes Chrome refuse the response (see
  [Several Content-Disposition headers](#several-content-disposition-headers)).
  requests and `urllib.request` give a NUL in a header line on, and
  `blocks_download` tells you that Chrome refuses the response, unless the NUL
  keeps them from reading the line as a header line (see the next item).
  httpx2, httpx and aiohttp refuse the response themselves, with an
  exception.
- **Lines that are not header lines.** requests and `urllib.request` stop
  reading the headers at a line they cannot read as a header line, and lose
  the header lines after it: text without a colon after a line break in a
  value, which Chrome skips; a header name with a NUL in it, or a line that
  starts with a NUL, for which Chrome refuses the response; and a line of
  nothing but CRs, such as the one that a CR at the end of a value makes with
  the line break after it, which is no blank line to Chrome. aiohttp's Python
  parser also ends the headers at a line of CRs. httpx2, httpx and aiohttp
  refuse a line that is not a header line.
- **Lone CRs.** A CR that no LF follows breaks the line, for Chrome as for
  requests and `urllib.request`. httpx2, httpx and aiohttp's C parser refuse
  the response; aiohttp's Python parser drops the CRs at the end of a line and
  refuses the others.
- **Vertical tabs and form feeds** are part of a value to Chrome. httpx2 and
  httpx refuse the response.

Each library also refuses headers past limits of its own: aiohttp a header
line of more than about 8 KB or more than about 128 lines, requests and
`urllib.request` a line of more than 64 KiB or more than about 100 lines, and
httpx2 and httpx more than 100 to 164 KiB of headers in all, depending on how
the bytes arrive.

### Several Content-Disposition headers

A response can send Content-Disposition more than once: in several header
lines, or as values joined with commas in one line. Chromium splits every line
on commas outside quotes and names the file from the first value. If any value
differs from the first, Chrome refuses the whole response
(`ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION`). That also happens with a
single header that has a comma outside quotes, such as
`attachment; filename=a,b.txt`. Chrome also refuses a response whose headers
hold a NUL, in any header (`ERR_INVALID_HTTP_RESPONSE`; see [Reading header
lines](behavior.md#reading-header-lines)).

The package sees every value when it gets every line, as in [Pass the
headers from your HTTP library](#pass-the-headers-from-your-http-library). A
header looked up by name is not the same: `urllib.request` and aiohttp give
only its first line, and requests, httpx and httpx2 join its lines into one
(see [Joined lines and guessed bytes](#joined-lines-and-guessed-bytes)). Pass
the headers to `suggested_filename`, or to `parse_content_disposition`, whose
`blocks_download` tells you whether Chrome refuses the response for either
reason:

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
>>> parse_content_disposition([("X-Note", "a\x00b"), ("Content-Disposition", "attachment")])
ContentDisposition(type='attachment', filename=None, blocks_download=True)
```

When Chrome refuses a response, a plain link to it downloads nothing: Chrome
shows an error page instead. A link with a `download` attribute still starts a
download, which fails; Chrome names it from the attribute or the URL, without
the Content-Disposition and the Content-Type of the response.
`suggested_filename` does not model the refusal: it names the file from the
first value all the same, `a.pdf` above.

## Add an extension from the Content-Type

When the name does not come from Content-Disposition, Chrome adds the
extension of the response's MIME type, or corrects the extension the name
has. Give the package the response's headers, and it reads the MIME type from
them as Chrome does:

```pycon
>>> headers = [("Content-Type", "application/pdf")]
>>> suggested_filename(headers, url="https://example.com/report")
'report.pdf'
>>> suggested_filename(headers, url="https://example.com/get.php?id=1")
'get.pdf'
>>> suggested_filename(headers, url="https://example.com/get.php")
'get.php'
>>> suggested_filename(
...     [*headers, ("Content-Disposition", 'attachment; filename="report"')],
...     url="https://example.com/x",
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
- RSS and Atom feeds get `.txt`, and so does a response that has no
  Content-Type and sends `X-Content-Type-Options: nosniff`.

The package reads every Content-Type line, and X-Content-Type-Options, the way
Chrome's network stack does (see [The MIME type](behavior.md#the-mime-type)).
To give the Content-Type apart from the headers, or without them, pass its raw
value as `content_type`, as bytes or as the str your HTTP library produced. It
takes the place of every Content-Type line in `headers`; `None`, the default,
keeps them. An empty string is an empty Content-Type, not a missing one.
X-Content-Type-Options is read only from `headers`, and with neither `headers`
nor `content_type` no MIME type is used:

```pycon
>>> headers = [("Content-Type", "application/pdf"), ("X-Content-Type-Options", "nosniff")]
>>> suggested_filename(headers, url="https://example.com/report", content_type="text/html")
'report.html'
>>> suggested_filename(headers, url="https://example.com/report", content_type="")
'report.txt'
>>> suggested_filename(url="https://example.com/report", content_type="application/pdf")
'report.pdf'
```

### When Chrome sniffs the body

Unless the response sends `X-Content-Type-Options: nosniff`, Chrome looks at
the start of the body when the Content-Type is missing or says little:
`text/plain`, `application/octet-stream`, XML, Microsoft Office types and
unknown ones. It may then use another MIME type than the headers give. The
package never sees the body, so it uses the type the headers declare, and its
name can differ from the one Chrome and Playwright report: a response with no
Content-Type that holds HTML is `page.html` to Chrome, but `page` here. To
predict the name exactly, have the actual response send
`X-Content-Type-Options: nosniff`, use a type that Chrome does not sniff, or
give the name in Content-Disposition.

This covers downloads that Chrome loads over the network. Other ways of
loading a response, such as Playwright's `route.fulfill`, and `blob:`, `data:`
and `file:` URLs, are not modeled; they can end up with another MIME type.

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
| Your own URL fallback and file name cleaning | `suggested_filename(headers, url=url)` |
| Your own cleaning of a name from elsewhere | `sanitize_filename(name)` |

`parse_content_disposition` never raises on a malformed header and returns
`None` when there is no usable name. Its results differ from parsers that
follow the RFCs strictly wherever Chromium does, which is the point.
