"""Bounded retries and diagnostics for read-only Gitiles source checks."""

from __future__ import annotations

import base64
import binascii
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead

ATTEMPTS = 4
TIMEOUT = 60
MAX_RETRY_DELAY = 30
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class SourceFetchError(Exception):
    """A source could not be read; this is not evidence of source drift."""

    def __init__(self, url: str, attempts: int, reason: str, *, temporary: bool) -> None:
        self.url = url
        self.attempts = attempts
        self.temporary = temporary
        super().__init__(f"{url}: {reason} (after {attempts} attempt(s))")


def retry_after_seconds(value: str | None) -> float:
    if value is None:
        return 0
    try:
        return min(MAX_RETRY_DELAY, int(value))
    except ValueError:
        try:
            return (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0


def fetch(url: str, *, user_agent: str) -> bytes:
    """Read a Gitiles TEXT response, retrying only transient fetch failures."""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    for attempt in range(1, ATTEMPTS + 1):
        retry_after = 0.0
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            temporary = error.code in RETRYABLE_STATUS
            reason = f"HTTP {error.code}: {error.reason}"
            retry_after = retry_after_seconds(error.headers.get("Retry-After"))
            error.close()
        except (urllib.error.URLError, TimeoutError, ConnectionError, IncompleteRead) as error:
            temporary = True
            reason = str(error)
        else:
            try:
                return base64.b64decode(payload, validate=True)
            except binascii.Error as error:
                raise SourceFetchError(
                    url, attempt, f"invalid Gitiles base64 response: {error}", temporary=False
                ) from error
        if not temporary or attempt == ATTEMPTS:
            raise SourceFetchError(url, attempt, reason, temporary=temporary)
        delay = min(MAX_RETRY_DELAY, max(2 ** (attempt - 1), retry_after))
        print(
            f"{url}: {reason}; attempt {attempt}/{ATTEMPTS} failed, retrying in {delay:g}s",
            file=sys.stderr,
        )
        time.sleep(delay)
    raise AssertionError("unreachable")


def report_failure(error: SourceFetchError, *, check: str) -> int:
    """Keep an incomplete check red, with its own exit code and Actions summary."""
    status = "source temporarily unavailable" if error.temporary else "source fetch failed"
    message = f"{check} incomplete: {status}\n{error}\nNo drift conclusion can be drawn."
    print(message, file=sys.stderr)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write(f"## {check} incomplete: {status}\n\n{error}\n\n")
            file.write("No drift conclusion can be drawn. Rerun the check after fixing access.\n\n")
    return 2
