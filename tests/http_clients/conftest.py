"""Fixtures for the HTTP client tests, which run only with --with-http-clients."""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest

from .server import Handler, LocalServer, Server


@pytest.fixture(scope="session")
def server() -> Iterator[LocalServer]:
    with Server(("127.0.0.1", 0), Handler) as httpd:
        httpd.responses = {}
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        host, port = httpd.server_address[:2]
        assert isinstance(host, str)
        yield LocalServer(f"http://{host}:{port}", httpd)
        httpd.shutdown()
