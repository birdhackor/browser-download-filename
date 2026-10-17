<!-- This file is also the package page on PyPI. PyPI breaks relative links: keep every link absolute. -->
# browser-download-filename

[![PyPI](https://img.shields.io/pypi/v/browser-download-filename.svg)](https://pypi.org/project/browser-download-filename/)
[![CI](https://github.com/birdhackor/browser-download-filename/actions/workflows/ci.yml/badge.svg)](https://github.com/birdhackor/browser-download-filename/actions/workflows/ci.yml)
[![Browsers](https://github.com/birdhackor/browser-download-filename/actions/workflows/browsers.yml/badge.svg)](https://github.com/birdhackor/browser-download-filename/actions/workflows/browsers.yml)
[![License: MIT OR Apache-2.0](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](https://github.com/birdhackor/browser-download-filename#license)

Name downloaded files the way Chrome does. A pure-Python port of the
Content-Disposition parser and the download naming rules of Chromium, the
open-source core of Chrome, Edge and other browsers.

HTTP clients hand you a response, not a file name. The usual ways to get one
(the standard library's `email` module, RFC 6266 parsers on PyPI) disagree
with browsers on headers that real servers send: an ASCII fallback before
`filename*`, raw UTF-8, percent-encoded names, language tags, semicolons
inside quotes. On those headers, this package gives the name Chrome gives.

## Features

- **Chromium's answer** — the header parser, the MIME type rules, the
  charset decoders and the file name sanitization are ports of Chromium's
  code at a pinned revision, and Chromium's own unit test cases are part of
  the tests. CI downloads more than 800 cases with a real Chromium and checks
  every result ([How it is
  checked](https://birdhackor.github.io/browser-download-filename/en/verification/)).
- **The whole response** — pass all the headers of a response. As in Chrome,
  the first Content-Disposition value names the file, and the Content-Type
  lines and X-Content-Type-Options give the MIME type, which can add an
  extension to a name that does not come from Content-Disposition. Where
  Chrome sniffs the body for another type, the package, which never sees the
  body, keeps the declared one. `blocks_download` tells you when Chrome
  refuses the response instead, for Content-Disposition values that differ
  or a NUL in the headers.
- **Bytes or str** — pass the headers as the bytes on the wire, folded lines
  included, or as the strs your HTTP library made of them, such as the Latin-1
  strs of requests, urllib3 and `http.client` or the surrogate-escaped strs of
  aiohttp; name the codec as `headers_encoding`, and they are mapped back to
  the bytes exactly. Some libraries join folded lines their own way first; the
  documentation lists them.
- **Never raises on a malformed header** — it returns what Chromium makes of
  it.
- **Safe names** — the result is a single file name, never empty, with path
  separators, control characters and other characters that file systems
  reject replaced. `platform="windows"` adds Windows' rules for reserved
  names, trailing dots and spaces, and shortcut extensions; by default they
  apply when the code runs on Windows. `sanitize_filename` cleans a name from
  anywhere else, such as a page title, the same way.
- **No dependencies** — pure Python, one wheel for every platform: CPython
  3.11+ and PyPy.

## Install

```sh
pip install browser-download-filename      # or: uv add browser-download-filename
```

## Usage

```pycon
>>> from browser_download_filename import parse_content_disposition, suggested_filename
>>> header = b"attachment; filename=report.pdf; filename*=UTF-8''%E5%A0%B1%E5%91%8A.pdf"
>>> headers = [("Content-Disposition", header)]
>>> suggested_filename(headers, url="https://example.com/download?id=42")
'報告.pdf'
>>> suggested_filename(headers)
'報告.pdf'
>>> suggested_filename(url="https://example.com/files/r%C3%A9sum%C3%A9.pdf")
'résumé.pdf'
>>> parse_content_disposition('attachment; filename="a;b;c.txt";')
ContentDisposition(type='attachment', filename='a;b;c.txt', blocks_download=False)
```

`suggested_filename` downloads nothing: it takes the headers of a response and
its final URL (after redirects), and returns the name Chrome reports to
DevTools and Playwright as the download's suggested file name, except in the
cases listed under [Limits of the
port](https://birdhackor.github.io/browser-download-filename/en/behavior/#limits-of-the-port).
The URL is optional: when the headers give no name, Chrome takes the last
segment of its path. Leave it out if you have no URL. With httpx2:

```python
import httpx2
from browser_download_filename import suggested_filename

with httpx2.stream("GET", url, follow_redirects=True) as response:
    name = suggested_filename(response.headers.raw, url=str(response.url))
```

`response.headers.raw` holds the header lines in bytes, each line on its own.
The documentation shows the same for httpx, requests, aiohttp and
`urllib.request`.

`sanitize_filename` cleans a name from anywhere else, such as a page title or
user input, as Chrome cleans an `<a download>` value:

```pycon
>>> from browser_download_filename import sanitize_filename
>>> sanitize_filename("Q3 report: draft?.pdf")
'Q3 report_ draft_.pdf'
```

## Documentation

Full documentation (English / 正體中文), including usage with httpx2, httpx,
requests, aiohttp and `urllib.request`, the options, how Chrome, Firefox and
Safari differ, how the package is checked against Chromium, the API reference
and a changelog:
**https://birdhackor.github.io/browser-download-filename/**

## License

Licensed under either of
[MIT](https://github.com/birdhackor/browser-download-filename/blob/main/LICENSE-MIT) or
[Apache-2.0](https://github.com/birdhackor/browser-download-filename/blob/main/LICENSE-APACHE)
at your option.

The package contains code ported from Chromium (BSD-3-Clause) and tables
generated from ICU and the WHATWG Encoding Standard (Unicode-3.0 and
BSD-3-Clause), so the distributions as a whole are under
`(MIT OR Apache-2.0) AND BSD-3-Clause AND Unicode-3.0`; see
[THIRD-PARTY-LICENSES](https://github.com/birdhackor/browser-download-filename/blob/main/THIRD-PARTY-LICENSES).
