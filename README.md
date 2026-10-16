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
inside quotes. This package gives the name Chrome gives.

## Features

- **Chromium's answer** — the header parser, the charset decoders and the
  file name sanitization are ports of Chromium's code at a pinned revision,
  tested with Chromium's own unit test cases. CI downloads more than 800 cases
  with a real Chromium and requires the same name for each one that the
  headers and the URL decide.
- **Bytes or str** — pass the header as the bytes on the wire, or as the str
  your HTTP library made of them; the Latin-1 strs of requests, urllib3 and
  `http.client` and the surrogate-escaped strs of aiohttp are mapped back to
  the bytes.
- **Never raises on a malformed header** — it returns what Chromium makes of
  it.
- **Safe names** — the result is a single file name, never empty, with path
  separators, control characters and other characters that file systems
  reject replaced. `platform="windows"` adds Windows' rules for reserved
  names, trailing dots and spaces, and shortcut extensions; by default they
  apply when the code runs on Windows.
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
>>> suggested_filename(url="https://example.com/download?id=42", content_disposition=header)
'報告.pdf'
>>> suggested_filename(content_disposition=header)
'報告.pdf'
>>> suggested_filename(url="https://example.com/files/r%C3%A9sum%C3%A9.pdf")
'résumé.pdf'
>>> parse_content_disposition('attachment; filename="a;b;c.txt";')
ContentDisposition(type='attachment', filename='a;b;c.txt', blocks_download=False)
```

`suggested_filename` downloads nothing: it takes the final URL of a response
(after redirects) and its Content-Disposition header, and returns the name
Chrome reports to DevTools and Playwright as the download's suggested file
name. The URL is optional and only matters when the header gives no name:
Chrome then takes the last segment of its path. Leave it out if you have no
URL. With requests:

```python
import requests
from browser_download_filename import suggested_filename

response = requests.get(url)
header = response.headers.get("Content-Disposition")
name = suggested_filename(
    url=response.url,
    content_disposition=header.encode("latin-1") if header else None,  # the bytes on the wire
    content_type=response.headers.get("Content-Type"),
)
```

## Documentation

Full documentation (English / 正體中文), including usage with requests, httpx,
httpx2, aiohttp and urllib, the options, how Chrome, Firefox and Safari differ,
how the package is checked against Chromium, the API reference and a changelog:
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
