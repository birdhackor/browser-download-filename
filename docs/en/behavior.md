# Behavior and browser differences

This page describes the rules the package follows, which are Chromium's, what
Chrome does beyond them, and where Firefox and Safari name files differently.

## Reading header lines

Chrome reads the headers of a response as the bytes that arrive, before it
reads any one header. The package reads each header value the same way, as
the rest of its header line as it was sent, so a value can hold line breaks,
which HTTP has long deprecated inside a header:

- **A blank line ends the headers.** A line feed, then an optional CR and
  another line feed make a blank line, and what follows it is the body.
- **A line that starts with a space or a tab continues the header.** It is
  joined on with one space, in place of the line break and the spaces and tabs
  that start the line; the spaces and tabs at the end of the line before it
  stay. So `filename="a \r\n b.pdf"` names the file `a  b.pdf`, with two
  spaces.
- **Any other line is another header line**, so the value ends at the line
  break before it. Only CR and LF break lines: a vertical tab or a form feed is
  part of the value, and it does not start a continued line either.
- **A NUL anywhere in the headers**, in a name or a value, makes Chrome refuse
  the whole response (`ERR_INVALID_HTTP_RESPONSE`), as it refuses a response
  whose Content-Disposition values differ (see [Reading
  Content-Disposition](#reading-content-disposition)).
  `parse_content_disposition` reports it as `blocks_download`, and
  `suggested_filename` names the file all the same. A NUL after a blank line
  is in the body, and changes nothing.

The package reads one value at a time, so it does not read every header line
that values make on the wire the way Chrome does (see [Limits of the
port](#limits-of-the-port)).

## Reading Content-Disposition

- **First value only.** Every Content-Disposition line is split on commas
  outside quoted strings, and the file is named from the first value of the
  first line. So as long as every quote is closed, it makes no difference
  whether repeated headers come as several lines or joined with `, ` by an
  HTTP library. A quote left open runs to the end of its line, which in a
  joined line takes in the values after it: the lines
  `attachment; filename="a` and `attachment; filename=b` give the name `a`
  and two values that differ, while joined they are one value, whose name is
  `a, attachment; filename=b`. When any value differs
  from the first, byte for byte once the spaces and tabs around it are trimmed,
  Chrome refuses the response and downloads nothing; a link with a `download`
  attribute starts a download that fails instead (see
  [Usage](usage.md#several-content-disposition-headers)). That happens with
  repeated headers that differ, and also with a single header that has a comma
  outside quotes, such as `filename=a,b.txt` or a trailing comma.
  `parse_content_disposition` reports it as `blocks_download`, as it reports a
  NUL in the headers (see [Reading header lines](#reading-header-lines));
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
4. The extension rules for the MIME type (see [The MIME type](#the-mime-type))
   and the Windows rules apply, as described in
   [Usage](usage.md#add-an-extension-from-the-content-type).

So a name made of `report`, U+202E and `txt.exe`, which displays as
`reportexe.txt`, becomes `report_txt.exe`.

## The MIME type

The extension comes from the MIME type that Chrome's network stack hands to
the download code. The package works it out the same way from `headers` and
`content_type`; with neither, it uses none.

- **Content-Type.** All Content-Type lines are joined with `, ` and split on
  commas outside quoted strings, so a quote left open on one line runs on into
  the next. A value's type runs from its start to the first space, tab, `;`
  or `(`, and must hold the value's first `/`. Nothing else is checked, so
  `text/` and `"text/html"` are types, with no extension. The last value that
  has a type gives it, in ASCII lowercase; a value without one, and the value
  `*/*` itself, change nothing. So `text/plain, text/html` is `text/html`,
  `text/html, bogus` is `text/html`, and `*/*; q=1` is `*/*`.
- **Sniffing.** Chrome sniffs the body for another MIME type when the type is
  missing, `text/plain`, `application/octet-stream`, `text/xml`,
  `application/xml`, a Microsoft Office type, or unknown (`unknown/unknown`,
  `application/unknown`, `*/*`), unless the first value of the first
  X-Content-Type-Options line is `nosniff`, in any ASCII case. It sniffs only
  `http:`, `https:`, `file:` and `filesystem:` URLs; without a `url`, the
  package assumes it sniffs. The package never sees the body: where Chrome
  sniffs, it uses the declared type, or none (see
  [Usage](usage.md#when-chrome-sniffs-the-body)).
- **Without sniffing**, a missing type becomes `text/plain`, and so do the
  feed types `application/rss+xml` and `application/atom+xml`.

## What Chrome does beyond this

The package returns the name that Chrome reports to DevTools and Playwright
when a download starts, except in the cases listed under [Limits of the
port](#limits-of-the-port). The file Chrome finally writes can differ:

- **Default text encoding.** For raw bytes that are not UTF-8, Chrome uses the
  browser's default text encoding. Pass it as `fallback_charset` (see
  [Usage](usage.md#decode-legacy-charsets)).
- **Existing files.** Chrome numbers the name, as in `report (1).pdf`.
- **Long names.** Chrome shortens a name that is too long for the file system,
  keeping the extension.
- **ChromeOS.** ChromeOS normalizes the name to NFC.
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
and each run's summary lists the cases where they differ from Chrome.
The table comes from those runs, with Playwright 1.64: Chromium 156 for Chrome
and Firefox 157, both on Linux, and WebKit 27.2 on macOS for Safari, since
WebKit on macOS names downloads with Apple's networking code, as Safari does.
Of the 916 cases in the exact set, Firefox gives Chrome's name for 468 and
WebKit on macOS for 351; of the 16 cases in the limited set, Firefox does for
13 and WebKit on macOS for 15 (the two sets are described in [How it is
checked](verification.md#a-real-chromium)). Where Chrome refuses a response (see
[Limits of the port](#limits-of-the-port)) and downloads nothing, a browser
gives Chrome's name only if it downloads nothing either.

## Limits of the port

- **Refused responses.** Chrome refuses a response whose Content-Disposition
  values differ or whose headers hold a NUL (see [Reading
  Content-Disposition](#reading-content-disposition) and [Reading header
  lines](#reading-header-lines)), which `blocks_download` reports. It also
  refuses responses for reasons that the package does not look for, such as
  Location headers that are repeated with different values. In every case,
  `suggested_filename` names the file all the same.
- **Headers that are not the lines on the wire.** The package reads the
  headers it is given as the lines that Chrome received, so the name can
  differ where they are not: where an HTTP library changed the lines, or
  where strs are passed without `headers_encoding` (see [Pass the headers
  from your HTTP library](usage.md#pass-the-headers-from-your-http-library)),
  and where a `content_type` is given without the other headers, which leaves
  out X-Content-Type-Options (see [Add an extension from the
  Content-Type](usage.md#add-an-extension-from-the-content-type)).
- **Header lines inside a value.** The package reads each header value on its
  own (see [Reading header lines](#reading-header-lines)). A line break in a
  value before another header line ends the value, but the package does not
  read that line as a header, as Chrome does: in
  `attachment; filename=a.pdf\rContent-Disposition: attachment; filename=b.pdf`
  it misses the second Content-Disposition, for which Chrome refuses the
  response. A blank line in a value, or a line feed at its end, which makes a
  blank line with the line break after it, ends the headers on the wire; the
  package ends the value there, but it goes on to read the header lines after
  it. The HTTP libraries that [Usage](usage.md#pass-the-headers-from-your-http-library)
  shows make header lines of their own out of such lines, end the headers at
  the blank line, or refuse the response, so this matters only for header
  lines that you put together yourself.
- **MIME sniffing.** Where Chrome sniffs the body for a MIME type, the package
  uses the declared one, so the extension can differ from Chrome's. Only
  downloads that Chrome loads over the network are modeled: Playwright's
  `route.fulfill`, and `blob:`, `data:` and `file:` URLs, can give another
  MIME type.
- **Windows and macOS.** Chrome on Windows and macOS also asks the system
  which extension a MIME type has, while the package uses Chromium's built-in
  table, which is all Chrome on Linux uses: `platform="windows"` adds
  Windows' rules for names, not the system's table. For a raw non-UTF-8 name
  without a default encoding, Chrome on Windows decodes it with the system's
  ANSI code page, where the package, like Chrome on Linux, does not use the
  name.
- **Hosts.** Chromium converts a non-ASCII host with UTS #46; the package uses
  Python's IDNA 2003 codec. They can disagree on whether a host is valid (a
  right-to-left label that ends in a digit, a label longer than 63 characters)
  and on the host's ASCII form (`ß` and `ς`). This only matters for URLs with
  non-ASCII hosts. requests, httpx, httpx2 and aiohttp give the host in
  `response.url` in its ASCII form, but `urllib.request` gives the URL as it
  was requested.
- **URL validity.** Hosts are not parsed as IPv4 addresses, so a URL that
  Chromium rejects for a malformed address can still give a name here. A URL
  that a browser could load gives the same name either way.
- **Unicode version.** NFC normalization of `filename*` uses the Unicode
  version of the running Python; Chromium's ICU has Unicode 17.0, which Python
  3.15 also has. They differ only on characters that the older version does
  not have.
