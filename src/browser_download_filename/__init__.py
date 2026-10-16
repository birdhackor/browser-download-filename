"""Name downloaded files exactly as Chromium does.

:func:`parse_content_disposition` reads a Content-Disposition header the way
Chromium's HttpContentDisposition does, and :func:`suggested_filename` runs
Chromium's whole download naming: Content-Disposition, then the URL, then a
default, followed by the same sanitization. Both accept the header as raw
bytes or as the str an HTTP library produced, and neither raises on a
malformed header.
"""

from importlib.metadata import version as _version

from ._content_disposition import ContentDisposition, parse_content_disposition
from ._filename import suggested_filename

__version__ = _version("browser-download-filename")

__all__ = [
    "ContentDisposition",
    "__version__",
    "parse_content_disposition",
    "suggested_filename",
]
