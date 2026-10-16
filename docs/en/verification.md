# How it is checked

The package claims to name files as Chromium does. These tests back the claim
up, and CI runs them on every change, on CPython 3.11 to 3.15 and PyPy 3.11,
on Linux, macOS and Windows.

## Chromium's own test cases

The parts of Chromium that the package ports come with unit tests:
`net/http/http_content_disposition_unittest.cc`,
`net/base/filename_util_unittest.cc` and `base/i18n/file_util_icu_unittest.cc`.
Their cases are ported one by one, including the expectations for Windows,
into more than 600 tests in `tests/test_chromium_*.py`.

## The charset decoders

Chromium decodes legacy charsets with its own copy of ICU, which is not the
same as Python's codecs. The tables for single-byte charsets are generated
from that ICU data. For the multi-byte charsets (Shift_JIS, EUC-JP,
ISO-2022-JP, GBK, gb18030, Big5 and EUC-KR), the package uses Python's codecs,
corrected where Chromium's ICU maps a sequence differently, and splits invalid
input the way ICU does. A test decodes every byte sequence that ICU's state
table for each charset accepts and compares a digest of the results with one
generated from ICU's mapping files, so a Python whose codecs disagree with
Chromium fails the test.

## A real Chromium

The browser tests in `tests/browser/` serve each case from a local HTTP server
that writes the response headers byte for byte, download it with Chromium
through Playwright, and compare the suggested file name that Chromium reports
with what `suggested_filename` returns for the same URL, headers and MIME type.
There are 831 cases:

- the headers of Chromium's unit tests;
- headers seen in practice: both parameter orders, language tags, raw UTF-8,
  %-escapes, RFC 2047, quotes and semicolons, trailing semicolons, repeated
  headers;
- URLs, MIME types and `<a download>` values;
- every charset label Chromium knows;
- every character of every single-byte charset, every character of up to three
  bytes in every multi-byte charset, samples of gb18030's four-byte
  characters, and the byte sequences on which Python's codecs and ICU
  disagree;
- 150 headers made by randomly mutating the others.

Chromium must give the same name for every case, or CI fails. The cases also
run with Firefox, and with WebKit on Linux and macOS; those runs list the
differences in their summary instead of failing (see [Behavior and browser
differences](behavior.md#other-browsers)).

To run the browser tests yourself:

```console
uv sync
uv run playwright install chromium
uv run pytest tests/browser --with-browser chromium --browser-report report.json
```

`--with-browser` takes `chromium`, `firefox` or `webkit` and can be repeated;
`--browser-report` also writes a Markdown summary next to the JSON file.

## Properties

Hypothesis generates inputs to check that:

- parsing any bytes or str never raises;
- `suggested_filename` always returns a non-empty name with no character that
  is illegal anywhere, and none that is illegal at the start or end;
- cleaning a name a second time does not change it, with two exceptions, both
  as in Chromium: a name made only of `-` and `_` becomes `download`, and with
  `platform="windows"` a `~` can become `_` the second time, because whether a
  name could be an 8.3 short name, and so has its `~` replaced, is decided
  before its other illegal characters are replaced (`0~|` becomes `0~_`, then
  `0__`);
- names survive a round trip through `filename*`;
- large adversarial inputs are handled in linear time.

## Following Chromium

The port follows Chromium at a pinned revision (`CHROMIUM_REVISION` in
`browser_download_filename._data`) and the ICU revision that Chromium pins. A
weekly canary

- runs the browser tests against the newest Chromium that Playwright ships,
  so a change in Chromium's behavior shows up as a failing case;
- checks whether the ported Chromium files or the ICU revision changed since
  the pinned revision;
- installs the published package on the newest Python and runs the tests with
  the newest versions of the test tools.
