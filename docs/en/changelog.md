# Changelog

Each release names the Chromium revision it follows. A release that follows a
newer revision can return different names wherever Chromium changed its rules,
even when the API stays the same.

## 0.2.0

- Follows the same Chromium revision as 0.1.0,
  `dfd5cca812cefda32e909ae39965ed22041d5e65` (main, 2026-10-16), and its
  ICU 78.
- `suggested_filename()` takes a response's headers as a whole and works out
  the MIME type from them as Chrome does, short of sniffing the body, and the
  new `sanitize_filename()` cleans a name from anywhere. Calls written for
  0.1.0 may need the changes below.

### Incompatible changes

| 0.1.0 | 0.2.0 |
| --- | --- |
| `suggested_filename(url)` | `suggested_filename(url=url)` |
| `suggested_filename(url, header)` | `suggested_filename(url=url, content_disposition=header)` |
| `suggested_filename(None, header)` | `suggested_filename(content_disposition=header)` |
| `suggested_filename(url, suggested_name=name)` | `suggested_filename(url=url, download_attribute=name)` |
| `suggested_filename(url, mime_type=content_type)` | `suggested_filename(url=url, content_type=content_type)` |
| `suggested_filename(url, default_name="")` | `suggested_filename(url=url, default_name=None)` |
| `suggested_filename(url=url, content_disposition=header)` on Windows | `suggested_filename(url=url, content_disposition=header, platform="posix")` |
| `parse_content_disposition(value=header)` | `parse_content_disposition(header)` |

- `suggested_filename()` takes only one argument by position, the new
  `headers`, which cannot be a str or bytes: a URL or a header passed by
  position raises `TypeError`.
- `suggested_name` is now `download_attribute`, and `mime_type` is now
  `content_type`, the Content-Type header as the server sent it (see Changed
  behavior).
- `default_name=None` asks for the URL's host. An empty `default_name`, which
  did that in 0.1.0, raises `ValueError`.
- `platform` defaults to `None`, which picks Windows' rules when the code runs
  on Windows and the POSIX rules elsewhere. 0.1.0 used the POSIX rules
  everywhere: on Windows, pass `platform="posix"` to keep its names.
- The `value` of `parse_content_disposition()` is positional-only.

To pass all of a response's headers instead of one header, see
[Usage](usage.md#pass-the-headers-from-your-http-library).

### New features

- `suggested_filename(headers, url=...)` takes the response's headers, as a
  mapping or as (name, value) pairs with str or bytes values (`HeadersLike`,
  exported for type hints). The first value of the first Content-Disposition
  line names the file, and the Content-Type lines and X-Content-Type-Options
  give the MIME type. `content_disposition` and `content_type`, when not
  `None`, take the place of those lines.
- `parse_content_disposition()` also takes a response's headers, and its
  result has a new field, `blocks_download`: whether Chrome refuses the
  response because the Content-Disposition values, split on commas outside
  quotes, are not all the same, or because the headers hold a NUL.
  `suggested_filename()` names the file from the first value all the same.
  The field counts in equality and shows in the repr: for
  `attachment; filename=a,b.txt`, the result no longer equals
  `ContentDisposition("attachment", "a")`.
- `headers_encoding` names the codec your HTTP library decoded the headers
  with, such as `"latin-1"` for requests and `urllib.request`, and turns every
  str header value back into the bytes it was decoded from.
- `content_type` also takes bytes.
- `sanitize_filename()` cleans a name from anywhere, such as a page title, as
  Chrome cleans an `<a download>` value.
- [Usage](usage.md#pass-the-headers-from-your-http-library) shows how to pass
  the headers from httpx2, httpx, requests, aiohttp and `urllib.request`, and
  tests fetch responses with each of them to check it.

### Changed behavior

Some calls give another result in 0.2.0. The changes are of three kinds.

**Closer to Chromium.**

- Every header value, including `content_disposition`, `content_type` and
  the `value` of `parse_content_disposition()`, is read as the rest of its
  header line as it was sent (see [Reading header
  lines](behavior.md#reading-header-lines)): a line that starts with a space
  or a tab is joined on with one space, and any other line, or a blank line,
  ends the value. 0.1.0 read CR and LF as characters of the value:
  `attachment;\r\n filename=wire.pdf` gave no file name, and
  `attachment; filename=a.pdf\r\nX-Note: 1` took the next line into the
  name, where 0.2.0 gives `wire.pdf` and `a.pdf`. Values without CR or LF are
  not affected.
- `content_type` is read the way Chrome's network stack reads a Content-Type
  header (see [The MIME type](behavior.md#the-mime-type)): the type ends at
  the first space, tab, `;` or `(`, and of comma-separated values, the last
  one that gives a type wins, while the value `*/*` itself changes nothing.
  So with the URL `https://example.com/page`,
  `text/html(comment)`, `text/html charset=utf-8` and `text/plain, text/html`
  give `page.html`, where 0.1.0 gave `page`.
- The feed types `application/rss+xml` and `application/atom+xml` are
  `text/plain`, as in Chrome: they give `page.txt`, where 0.1.0 gave
  `page.rss` and `page`.
- Chrome sniffs the body for a MIME type only with `http:`, `https:`, `file:`
  and `filesystem:` URLs. With a valid URL of another scheme, such as
  `ftp://example.com/page`, a `content_type` that gives no type, such as an
  empty one, is `text/plain`: it gives `page.txt`, where 0.1.0 gave `page`.

**`content_type` is the header as sent.** 0.1.0 said to pass the MIME type
Chrome would use when the server does not send
`X-Content-Type-Options: nosniff`, since Chrome may then sniff the body for
another type. 0.2.0 takes that back: `content_type` is the Content-Type
header as the server sent it, and where Chrome sniffs the body, which the
package never sees, the package uses the type the headers declare. For a
response from `https://example.com/page` without Content-Type whose body is
HTML, the advice was to pass `mime_type="text/html"`, which gave `page.html`;
0.2.0 gives `page` for these headers, while Chrome reports `page.html` (see
[When Chrome sniffs the body](usage.md#when-chrome-sniffs-the-body)).

**Passing the whole headers.** Moving from one header to all of them can
change the name:

- `X-Content-Type-Options: nosniff` counts. With it, Chrome does not sniff,
  and a response without a Content-Type, or with one that gives no type, is
  `text/plain`: `https://example.com/page` gives `page.txt`, where 0.1.0 gave
  `page`.
- Every Content-Type line counts: the last value that gives a type wins, and
  the value `*/*` itself changes nothing.
  `urllib.request` and aiohttp give the first line when you look a header up
  by name: for the lines `text/plain` and `application/pdf`, 0.1.0 gave
  `page.txt` for the first one, and 0.2.0 gives `page.pdf` for both.
- The first value of the first Content-Disposition line names the file, as
  before. Lines joined into one, as the `response.headers` of requests, httpx
  and httpx2 give them, can give another result than the lines themselves
  (see [Joined lines and guessed
  bytes](usage.md#joined-lines-and-guessed-bytes)).

## 0.1.0

- Initial release, following Chromium revision
  `dfd5cca812cefda32e909ae39965ed22041d5e65` (main, 2026-10-16) and its ICU 78.
- `suggested_filename()` gives the name Chromium suggests for a download, and
  `parse_content_disposition()` reads a Content-Disposition header as Chromium
  does. Both take the header as bytes or str.
- Pure Python with no dependencies, for CPython 3.11 and later, and PyPy.
