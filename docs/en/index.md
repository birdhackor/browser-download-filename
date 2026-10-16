# Overview

browser-download-filename names downloaded files the way Chrome does. It is a
pure-Python port of two parts of Chromium, the open-source core of Chrome, Edge
and other browsers: the Content-Disposition header parser
(`net::HttpContentDisposition`) and the function that picks a download's file
name from the response (`net::GetSuggestedFilename`).

## Quick start

```console
python -m pip install browser-download-filename
```

```pycon
>>> from browser_download_filename import suggested_filename
>>> header = b"attachment; filename=report.pdf; filename*=UTF-8''%E5%A0%B1%E5%91%8A.pdf"
>>> suggested_filename(url="https://example.com/download?id=42", content_disposition=header)
'報告.pdf'
```

The result is what Chrome reports to DevTools and Playwright as the download's
suggested file name, and a safe file name to save under. See
[Usage](usage.md) for passing headers from requests, httpx, httpx2, aiohttp and
urllib.

## Why

When a program downloads a file with an HTTP library, picking the file name is
up to the program. The server's suggestion is in the Content-Disposition
header, and servers write it in many ways that the standards do not allow but
browsers accept. Code that reads the header by the standards gets those names
wrong; the standard library's `email` module, for example:

| Content-Disposition | Chrome and this package | `email.message.Message.get_filename()` |
| --- | --- | --- |
| `attachment; filename="fallback.zip"; filename*=UTF-8''%E4%B8%AD%E6%96%87.zip` | `中文.zip` | `fallback.zip` |
| `attachment; filename="%E4%B8%AD%E6%96%87.zip"` | `中文.zip` | `%E4%B8%AD%E6%96%87.zip` |
| `attachment; filename="=?UTF-8?B?5Lit5paHLnppcA==?="` | `中文.zip` | `=?UTF-8?B?5Lit5paHLnppcA==?=` |
| `attachment; filename="中文.zip"` in raw UTF-8, read with requests | `中文.zip` | `'ä¸\xadæ\x96\x87.zip'` |

No standard says what to do with such headers either: the HTML standard
defers to RFC 6266, and the web-platform-tests have no test of file name
parsing. Browsers agree on well-formed headers and differ on the rest; Chrome
is the most used of them, so it is the reference this package follows.
[Behavior and browser differences](behavior.md) shows where Firefox and
Safari differ.

The name in the header is only the start. Chrome falls back to the URL and then
to `download`, and it sanitizes whatever it picked: path separators, control
characters and other characters that file systems reject are replaced, and
leading and trailing dots are removed, so `../../etc/passwd` becomes
`_.._etc_passwd`. `suggested_filename` does all of it.

## What you get

| Function | What it does |
| --- | --- |
| `suggested_filename(url=..., content_disposition=..., ...)` | The file name Chrome picks for a download: from Content-Disposition, an `<a download>` value, the URL or a default, then sanitized. Optional arguments add Chrome's extension rules for a MIME type and choose between its Windows and POSIX rules. |
| `sanitize_filename(name)` | Chrome's sanitization applied to a name from anywhere, such as a page title or user input, the way Chrome cleans an `<a download>` value. |
| `parse_content_disposition(value)` | The disposition type and the decoded file name of a header, as Chromium reads them, without sanitizing. |

`suggested_filename` and `parse_content_disposition` take the header as bytes
or as a str and never raise on a malformed header. The package has no
dependencies outside the standard library and supports CPython 3.11 and later,
and PyPy.

## How exact it is

The parser, the charset decoders and the file name rules are ports of
Chromium's code at a pinned revision, and Chromium's own unit test cases are
part of the test suite. CI also downloads more than 800 cases with a real
Chromium and requires the same name for every one. [How it is
checked](verification.md) describes the tests; [Behavior and browser
differences](behavior.md) lists what Chrome does that this package leaves to
you, such as numbering files that already exist.

Next: examples are in [Usage](usage.md); the full API is in [API
reference](api-reference.md).
