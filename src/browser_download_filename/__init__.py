"""Name downloaded files exactly as Chromium does.

:func:`parse_content_disposition` reads a Content-Disposition header the way
Chromium's HttpContentDisposition does, and :func:`suggested_filename` runs
Chromium's whole download naming: Content-Disposition, then an ``<a download>``
value, then the URL, then a default, followed by the same sanitization. Both
take a response's headers (:data:`HeadersLike`), or the header alone as raw
bytes or as the str an HTTP library produced, and neither raises on a
malformed header. :func:`sanitize_filename` applies that sanitization to a
name from anywhere else.
"""

from importlib.metadata import version as _version

from ._content_disposition import ContentDisposition, parse_content_disposition
from ._filename import sanitize_filename, suggested_filename
from ._headers import HeadersLike

__version__ = _version("browser-download-filename")

__all__ = [
    "ContentDisposition",
    "HeadersLike",
    "__version__",
    "parse_content_disposition",
    "sanitize_filename",
    "suggested_filename",
]
