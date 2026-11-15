"""UnsignedProbe: an unauthenticated ``POST /v1/tasks`` through the sandbox's proxy path."""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from email.message import Message
from typing import Any
from urllib.parse import urlsplit

from r1_acceptance.models.execution import Execution
from r1_acceptance.utils import format_time, redact_url, utc_now


class UnsignedProbe:
    """Sends ``POST /v1/tasks`` with the body ``{}`` and no credentials, like ``curl -i``.

    It honours the environment's proxy settings (``HTTP_PROXY`` / ``NO_PROXY``) as the CLI
    does, never follows redirects, and keeps the raw response: status line, headers and body.
    """

    MAX_BODY_BYTES = 1024 * 1024

    def __init__(self, url: str, *, timeout_seconds: float = 30.0) -> None:
        self._url = url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def post_without_credentials(self) -> Execution:
        """Send the request and describe the response (or why there was none)."""
        opener = urllib.request.OpenerDirector()
        for handler in (
            urllib.request.ProxyHandler(),
            urllib.request.HTTPHandler(),
            urllib.request.HTTPDefaultErrorHandler(),
            urllib.request.HTTPErrorProcessor(),
        ):
            opener.add_handler(handler)
        request = urllib.request.Request(  # noqa: S310 - the run's http:// URL
            f"{self._url}/v1/tasks",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "r1-acceptance/1"},
        )
        started = utc_now()
        clock = time.monotonic()
        try:
            with opener.open(request, timeout=self._timeout_seconds) as response:
                status, reason = response.status, response.reason
                headers, version = response.headers, getattr(response, "version", None)
                body = response.read(self.MAX_BODY_BYTES)
        except urllib.error.HTTPError as exc:
            status, reason, headers = exc.code, str(exc.reason), exc.headers
            version = getattr(exc.fp, "version", None)
            body = exc.read(self.MAX_BODY_BYTES)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            return Execution(
                started_at=format_time(started),
                finished_at=format_time(utc_now()),
                duration_seconds=round(time.monotonic() - clock, 3),
                outcome=Execution.NO_RESPONSE,
                exit_code=None,
                stdout=b"",
                stderr=f"{type(exc).__name__}: {exc}".encode(),
                document=None,
                parse_error=None,
            )
        return Execution(
            started_at=format_time(started),
            finished_at=format_time(utc_now()),
            duration_seconds=round(time.monotonic() - clock, 3),
            outcome=Execution.HTTP_RESPONSE,
            exit_code=None,
            stdout=self._raw(status, reason, headers, version, body),
            stderr=b"",
            document=self._document(status, reason, headers, body),
            parse_error=None,
        )

    def via_proxy(self) -> str | None:
        """The proxy that the request goes through, or ``None`` for a direct connection."""
        host = urlsplit(self._url).hostname or ""
        proxy = urllib.request.getproxies().get("http")
        if proxy is None or urllib.request.proxy_bypass(host):
            return None
        return redact_url(proxy)

    def _document(self, status: int, reason: str, headers: Message, body: bytes) -> dict[str, Any]:
        text = body.decode("utf-8", errors="replace")
        error_code: str | None = None
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
            code = parsed["error"].get("code")
            error_code = code if isinstance(code, str) else None
        return {
            "http_status": status,
            "reason": reason,
            "headers": [[name, value] for name, value in headers.items()],
            "body": text,
            "error_code": error_code,
            "via_proxy": self.via_proxy(),
        }

    @staticmethod
    def _raw(status: int, reason: str, headers: Message, version: object, body: bytes) -> bytes:
        protocol = {10: "HTTP/1.0", 11: "HTTP/1.1"}.get(version if isinstance(version, int) else 0)
        lines = [f"{protocol or 'HTTP'} {status} {reason}"]
        lines += [f"{name}: {value}" for name, value in headers.items()]
        return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8", "replace") + body
