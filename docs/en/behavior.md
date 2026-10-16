# Behavior and browser differences

This page describes the rules the package follows, which are Chromium's, what
Chrome does beyond them, and where Firefox and Safari name files differently.

## Reading Content-Disposition

- **First value only.** Every Content-Disposition line is split on commas
  outside quoted strings, and the file is named from the first value of the
  first line, so it makes no difference whether repeated headers come as
  several lines or joined with `, ` by an HTTP library. When any value differs
  from the first, byte for byte once the spaces and tabs around it are trimmed,
  Chrome refuses the response and downloads nothing; a link with a `download`
  attribute starts a download that fails instead (see
  [Usage](usage.md#several-content-disposition-headers)). That happens with
  repeated headers that differ, and also with a single header that has a comma
  outside quotes, such as `filename=a,b.txt` or a trailing comma.
  `parse_content_disposition` reports it as `blocks_download`;
  `suggested_filename` names the file from the first value all the same.
- **Disposition type.** `inline` is inline; `attachment` and any other token
  are attachment. A header that does not start with a token, such as
  `filename=report.pdf`, is read as parameters with the type inline, and its
  file name is still used.
- **Parameters** are read left to right and the first malformed one ends the
  header: one without `=`, with an empty value, or with a quote in its name.
- **`filename*` comes first**, whatever the order, when it decodes. Its value
  is `charset'language'%-encoded-bytes` (RFC 8187); the language is ignored,
  the charset can be any one Chromium knows (`UTF-8`, `ISO-8859-1`,
  `Shift_JIS`, …), the bytes must be valid in it, and the result is normalized
  to NFC. A `filename*` that does not decode is skipped, and `filename` is used.
- **`filename`** may be a token or a quoted string, and it is decoded the way
  browsers do although the RFCs do not allow it:
    - raw UTF-8 bytes are UTF-8;
    - %-escapes are decoded (`%E4%B8%AD%E6%96%87.zip` is `中文.zip`), and the
      name is dropped if they do not decode to UTF-8;
    - RFC 2047 encoded words are decoded (`=?UTF-8?B?5Lit5paHLnppcA==?=`);
    - other raw bytes are decoded with `fallback_charset` if one is given;
      otherwise they are dropped, as Chrome on Linux does, which usually
      leaves no name.
- **Not supported**, as in Chromium: RFC 2231 continuations (`filename*0=`,
  `filename*1*=`), which are ignored.

## Picking the name

`suggested_filename` takes the first of these that is not empty:

1. the file name from Content-Disposition, whatever the disposition type;
2. `download_attribute`, the `<a download>` value;
3. the last segment of the URL's path: after the last `/` or `\`, up to a `;`,
   with %-escapes decoded. Its bytes must be UTF-8, or decode with
   `fallback_charset`. `data:` and `about:` URLs, and URLs that are not valid,
   give no name.
4. the URL's host, but only if `default_name` is `None`.

## Sanitizing it

Then, in this order:

1. Leading and trailing dots are removed (on Windows, trailing dots and spaces
   first become `_`), and `/` and `\` become `_`.
2. A name that is now empty, or made only of `-` and `_`, is replaced with
   `default_name` (`download` unless you pass another), or with `download` if
   `default_name` is `None`.
3. Characters that are not allowed anywhere become `_`: `"`, `*`, `/`, `:`,
   `<`, `>`, `?`, `\` and `|`, control characters, Unicode format characters
   such as the right-to-left override U+202E, and noncharacters. Whitespace,
   `.` and `~` at the start or end also become `_`.
4. The extension rules for `content_type` and the Windows rules apply, as
   described in [Usage](usage.md#add-an-extension-from-the-content-type).

So a name made of `report`, U+202E and `txt.exe`, which displays as
`reportexe.txt`, becomes `report_txt.exe`.

## What Chrome does beyond this

The package returns the name that Chrome reports to DevTools and Playwright
when a download starts. The file Chrome finally writes can differ:

- **Default text encoding.** For raw bytes that are not UTF-8, Chrome uses the
  browser's default text encoding. Pass it as `fallback_charset` (see
  [Usage](usage.md#decode-legacy-charsets)).
- **MIME sniffing.** Without `X-Content-Type-Options: nosniff`, Chrome may
  sniff a different MIME type than the Content-Type header and pick the
  extension from it.
- **Existing files.** Chrome numbers the name, as in `report (1).pdf`.
- **Long names.** Chrome shortens a name that is too long for the file system,
  keeping the extension.
- **The operating system.** Chrome on Windows and macOS also asks the system
  which extension a MIME type has, while the package uses Chromium's built-in
  table, which is all Chrome on Linux uses. For raw non-UTF-8 names without a
  default encoding, Chrome on Windows decodes with the system's ANSI code page
  and Chrome on macOS replaces the bytes with U+FFFD; the package drops them,
  as Chrome on Linux does. ChromeOS also normalizes names to NFC.
- **Everything around the name**: the Save As dialog, Safe Browsing and
  dangerous file warnings, extensions that rename downloads, and enterprise
  policies.

## Other browsers

Firefox and Safari agree with Chrome on well-formed headers and on the most
common deviations: `filename*` comes first in either order, language tags are
ignored, raw UTF-8 in `filename` is UTF-8, semicolons inside quotes are part
of the name, a trailing `;` is fine, and a header without a disposition type
is still read. On the rest they differ:

| Behavior | Chrome | Firefox | Safari |
| --- | --- | --- | --- |
| %-escapes in `filename` are decoded | yes | yes | no |
| RFC 2047 encoded words are decoded | yes | yes | no |
| RFC 2231 continuations (`filename*0=`) are joined | no | yes | no |
| Characters Windows does not allow, such as `<`, `?` and `*`, are replaced | yes | yes | no |
| A trailing space becomes | `_` | nothing | a space |

The [Browsers
workflow](https://github.com/birdhackor/browser-download-filename/actions/workflows/browsers.yml)
downloads every test case with Firefox, and with WebKit on Linux and on macOS,
and each run's summary lists the cases where they differ from this package.
The table comes from those runs, with Playwright 1.64: Firefox 157, and WebKit
27.2 on macOS for Safari, since WebKit on macOS names downloads with Apple's
networking code, as Safari does. Of the 831 cases, Firefox gives Chrome's name
for 423 and WebKit on macOS for 309.

## Limits of the port

- **Hosts.** Chromium converts a non-ASCII host with UTS #46; the package uses
  Python's IDNA 2003 codec. They can disagree on whether a host is valid (a
  right-to-left label that ends in a digit, a label longer than 63 characters)
  and on the host's ASCII form (`ß` and `ς`). This only matters for URLs with
  non-ASCII hosts, which HTTP libraries do not put in `response.url`: requests,
  httpx and aiohttp give the host in its ASCII form.
- **URL validity.** Hosts are not parsed as IPv4 addresses, so a URL that
  Chromium rejects for a malformed address can still give a name here. A URL
  that a browser could load gives the same name either way.
- **Unicode version.** NFC normalization of `filename*` uses the Unicode
  version of the running Python; Chromium's ICU has Unicode 17.0, which Python
  3.15 also has. They differ only on characters that the older version does
  not have.
