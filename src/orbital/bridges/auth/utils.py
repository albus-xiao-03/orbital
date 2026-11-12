"""Helpers of the authentication scheme: header names, protocol version, canonical strings."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping

SCHEME = "ORBITAL-HMAC-SHA256"
PROTOCOL_VERSION = "1"
PROTOCOL_HEADER = "X-Orbital-Protocol"
TIMESTAMP_HEADER = "X-Orbital-Timestamp"
NONCE_HEADER = "X-Orbital-Nonce"
SIGNATURE_HEADER = "X-Orbital-Signature"
NONCE_BYTES = 16
NONCE_PATTERN = re.compile(r"[0-9a-f]{32}")
SIGNATURE_PATTERN = re.compile(r"[0-9a-f]{64}")
TIMESTAMP_PATTERN = re.compile(r"[0-9]{1,12}")


def header_value(headers: Mapping[str, str], name: str) -> str | None:
    """Return the stripped value of header *name* (case-insensitive), or ``None``."""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value.strip()
    return None


def body_digest(body: bytes) -> str:
    """Lowercase hex SHA-256 of *body*."""
    return hashlib.sha256(body).hexdigest()


def request_string(method: str, target: str, timestamp: str, nonce: str, body: bytes) -> str:
    """Canonical string signed for a request (plan section 8)."""
    fields = (SCHEME, PROTOCOL_VERSION, "request", method, target, timestamp, nonce)
    return "\n".join((*fields, body_digest(body)))


def response_string(method: str, target: str, nonce: str, status: int, body: bytes) -> str:
    """Canonical string signed for a response, bound to the request's method, target and nonce."""
    fields = (SCHEME, PROTOCOL_VERSION, "response", method, target, nonce, str(status))
    return "\n".join((*fields, body_digest(body)))


def sign(secret: bytes, canonical: str) -> str:
    """Lowercase hex HMAC-SHA256 of *canonical* under *secret*."""
    return hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def signatures_match(expected: str, given: str) -> bool:
    """Constant-time comparison of two hex signatures."""
    return hmac.compare_digest(expected.encode("ascii"), given.encode("ascii"))
