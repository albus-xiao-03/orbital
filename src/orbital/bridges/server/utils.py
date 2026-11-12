"""Helpers of BridgeRequestHandler: request framing, target normalisation and response bodies."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from orbital.bridges.auth.utils import PROTOCOL_VERSION
from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.error_detail import ErrorDetail
from orbital.bridges.utils import SERVICE_NAME

CONTENT_LENGTH_PATTERN = re.compile(r"[0-9]{1,15}")


def normalize_target(target: str) -> str:
    """Origin-form path (and query) of a request target.

    Proxies may forward absolute-form targets (``http://host:port/v1/...``); only the path and
    query are kept, which is what the client signed.
    """
    if target.startswith(("http://", "https://")):
        parts = urlsplit(target)
        path = parts.path or "/"
        return f"{path}?{parts.query}" if parts.query else path
    return target


def parse_content_length(value: str | None) -> int | None:
    """The ``Content-Length`` as an integer, ``None`` if absent; ``ValueError`` if malformed."""
    if value is None:
        return None
    text = value.strip()
    if not CONTENT_LENGTH_PATTERN.fullmatch(text):
        raise ValueError(f"The Content-Length header {value!r} is not a valid length.")
    return int(text)


def format_peer(address: object) -> str:
    """``host:port`` of a client address, for logs."""
    if isinstance(address, tuple) and len(address) >= 2:
        return f"{address[0]}:{address[1]}"
    return str(address)


def error_document(code: ErrorCode, message: str, task_id: str | None) -> dict[str, object]:
    """The error body ``{"error": {...}, "task_id": ...}``."""
    return {"error": ErrorDetail(code, message).to_dict(), "task_id": task_id}


def health_document() -> dict[str, str]:
    """The body of ``GET /v1/health``."""
    return {"service": SERVICE_NAME, "protocol_version": PROTOCOL_VERSION}
