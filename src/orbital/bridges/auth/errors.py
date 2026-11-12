"""Exception family of the authentication scheme."""

from __future__ import annotations

from enum import StrEnum


class AuthFailureReason(StrEnum):
    """Coarse, non-secret reason for an authentication failure, sent in ``401`` responses."""

    MISSING_CREDENTIALS = "missing_credentials"
    MALFORMED_CREDENTIALS = "malformed_credentials"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    TIMESTAMP_OUT_OF_WINDOW = "timestamp_out_of_window"
    INVALID_SIGNATURE = "invalid_signature"
    REPLAYED_NONCE = "replayed_nonce"
    NONCE_CACHE_FULL = "nonce_cache_full"


class AuthenticationError(Exception):
    """A request failed authentication; :attr:`reason` says why, :attr:`detail` explains."""

    def __init__(self, reason: AuthFailureReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
