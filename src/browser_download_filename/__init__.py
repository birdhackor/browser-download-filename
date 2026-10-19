"""Name downloaded files the way Chrome does.

:func:`parse_content_disposition` reads a Content-Disposition header the way
Chromium's HttpContentDisposition does, and :func:`suggested_filename` runs
Chromium's whole download naming: Content-Disposition, then an ``<a download>``
value, then the URL, then a default, followed by the same sanitization. Both
take a response's headers (:data:`HeadersLike`), or the header alone as raw
bytes or as the str an HTTP library produced, and neither raises on a
malformed header. :func:`sanitize_filename` applies that sanitization to a
name from anywhere else.
"""

from typing import TYPE_CHECKING

from ._content_disposition import ContentDisposition, parse_content_disposition
from ._filename import sanitize_filename, suggested_filename
from ._headers import HeadersLike

__all__ = [
    "ContentDisposition",
    "HeadersLike",
    "__version__",
    "parse_content_disposition",
    "sanitize_filename",
    "suggested_filename",
]

# Loading importlib.metadata takes most of the import time, so __version__ is
# read when it is first used. Type checkers see only its declaration: a module
# __getattr__ would make them take any misspelled name for a str.
if TYPE_CHECKING:
    __version__: str
else:

    def __getattr__(name: str) -> str:
        if name != "__version__":
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        global __version__
        from importlib.metadata import version

        __version__ = version("browser-download-filename")
        return __version__
