# Changelog

Each release names the Chromium revision it follows. A release that follows a
newer revision can return different names wherever Chromium changed its rules,
even when the API stays the same.

## 0.1.0

- Initial release, following Chromium revision
  `dfd5cca812cefda32e909ae39965ed22041d5e65` (main, 2026-10-16) and its ICU 78.
- `suggested_filename()` gives the name Chromium suggests for a download, and
  `parse_content_disposition()` reads a Content-Disposition header as Chromium
  does. Both take the header as bytes or str.
- Pure Python with no dependencies, for CPython 3.11 and later, and PyPy.
