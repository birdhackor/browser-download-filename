"""A local HTTP server that sends header lines byte for byte.

It answers /case/<n>/<name> with the header lines added as response n, and
/redirect/<n>/download with a redirect to /case/<n>/<name>. The redirect
changes the last segment of the URL, so that a name taken from the URL
requested instead of the final one comes out different.
"""

from __future__ import annotations

import socketserver
from dataclasses import dataclass

Lines = tuple[tuple[bytes, bytes], ...]

#: The last segment of every URL that redirects.
REDIRECT_SEGMENT = "download"


def sent_lines(lines: Lines) -> list[tuple[bytes, bytes]]:
    """Every header line the server sends for a response with these lines."""
    return [*lines, (b"Content-Length", b"1"), (b"Connection", b"close")]


class Handler(socketserver.StreamRequestHandler):
    server: Server

    def handle(self) -> None:
        request_line = self.rfile.readline(65536)
        while self.rfile.readline(65536) not in (b"", b"\r\n", b"\n"):
            pass
        parts = request_line.split(b" ")
        target = parts[1] if len(parts) > 2 else b"/"
        _, kind, number, _ = [*target.split(b"/", 3), b"", b"", b""][:4]
        if kind == b"redirect":
            name = self.server.names[int(number)]
            self.wfile.write(
                b"HTTP/1.1 302 Found\r\nLocation: /case/" + number + b"/" + name + b"\r\n"
                b"Content-Length: 0\r\nConnection: close\r\n\r\n"
            )
            return
        head = b"HTTP/1.1 200 OK\r\n"
        for line_name, value in sent_lines(self.server.responses[int(number)]):
            head += line_name + b": " + value + b"\r\n"
        self.wfile.write(head + b"\r\nx")


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    responses: dict[int, Lines]
    #: The last segment of the final URL of each response.
    names: dict[int, bytes]


@dataclass
class LocalServer:
    base_url: str
    server: Server
    count: int = 0

    def add(self, lines: Lines, name: str, *, redirect: bool = False) -> tuple[str, str]:
        """Serve a response with these header lines.

        Returns the URL to request and the final URL of the response, which
        differ, in their last segment too, when the first one redirects to the
        second.
        """
        assert name != REDIRECT_SEGMENT, "a redirect must change the last segment"
        self.count += 1
        self.server.responses[self.count] = lines
        self.server.names[self.count] = name.encode("ascii")
        final = f"{self.base_url}/case/{self.count}/{name}"
        start = f"{self.base_url}/redirect/{self.count}/{REDIRECT_SEGMENT}" if redirect else final
        return start, final
