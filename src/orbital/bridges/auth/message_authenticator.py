"""HMAC-SHA256 signing and verification of bridge requests and responses."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Mapping

from orbital.bridges.auth.errors import AuthenticationError, AuthFailureReason
from orbital.bridges.auth.nonce_cache import NonceCache
from orbital.bridges.auth.shared_key import SharedKey
from orbital.bridges.auth.utils import (
    NONCE_BYTES,
    NONCE_HEADER,
    NONCE_PATTERN,
    PROTOCOL_HEADER,
    PROTOCOL_VERSION,
    SIGNATURE_HEADER,
    SIGNATURE_PATTERN,
    TIMESTAMP_HEADER,
    TIMESTAMP_PATTERN,
    header_value,
    request_string,
    response_string,
    sign,
    signatures_match,
)


class MessageAuthenticator:
    """Signs and verifies bridge messages under a :class:`SharedKey` (plan sections 8 and 9).

    The client signs requests and verifies responses; the server verifies requests (with a
    :class:`NonceCache` for replay protection) and signs responses, binding each response to the
    request's method, target and nonce.
    """

    def __init__(
        self,
        key: SharedKey,
        *,
        clock_skew_seconds: int = 300,
        nonce_cache: NonceCache | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if clock_skew_seconds < 1:
            raise ValueError("clock_skew_seconds must be at least 1")
        self._key = key
        self._skew = clock_skew_seconds
        self._nonces = nonce_cache
        self._clock = clock

    def sign_request(self, method: str, target: str, body: bytes) -> dict[str, str]:
        """Return the authentication headers for a request, including a fresh nonce."""
        timestamp = str(int(self._clock()))
        nonce = secrets.token_hex(NONCE_BYTES)
        canonical = request_string(method, target, timestamp, nonce, body)
        return {
            PROTOCOL_HEADER: PROTOCOL_VERSION,
            TIMESTAMP_HEADER: timestamp,
            NONCE_HEADER: nonce,
            SIGNATURE_HEADER: sign(self._key.secret, canonical),
        }

    def verify_response(
        self,
        method: str,
        target: str,
        nonce: str,
        status: int,
        body: bytes,
        headers: Mapping[str, str],
    ) -> bool:
        """``True`` only if the response's signature verifies for this request and status."""
        given = header_value(headers, SIGNATURE_HEADER)
        if given is None or SIGNATURE_PATTERN.fullmatch(given) is None:
            return False
        expected = sign(self._key.secret, response_string(method, target, nonce, status, body))
        return signatures_match(expected, given)

    def request_nonce(self, headers: Mapping[str, str]) -> str | None:
        """The request's nonce if it is well-formed (used to sign every response), else ``None``."""
        nonce = header_value(headers, NONCE_HEADER)
        return nonce if nonce is not None and NONCE_PATTERN.fullmatch(nonce) else None

    def verify_request(
        self, method: str, target: str, headers: Mapping[str, str], body: bytes
    ) -> str:
        """Verify a request and return its nonce.

        Raises ``AuthenticationError`` on the first failed check. The checks run in the order of
        plan section 9: presence and form of the credentials, protocol version, timestamp window,
        signature, then replay (the nonce is recorded only after the signature has verified).
        """
        if self._nonces is None:
            raise RuntimeError("verifying requests requires a NonceCache")
        names = (PROTOCOL_HEADER, TIMESTAMP_HEADER, NONCE_HEADER, SIGNATURE_HEADER)
        values = {name: header_value(headers, name) or "" for name in names}
        missing = [name for name in names if not values[name]]
        if missing:
            raise AuthenticationError(
                AuthFailureReason.MISSING_CREDENTIALS, f"missing {', '.join(missing)}"
            )
        protocol = values[PROTOCOL_HEADER]
        timestamp = values[TIMESTAMP_HEADER]
        nonce = values[NONCE_HEADER]
        signature = values[SIGNATURE_HEADER]
        if not (
            TIMESTAMP_PATTERN.fullmatch(timestamp)
            and NONCE_PATTERN.fullmatch(nonce)
            and SIGNATURE_PATTERN.fullmatch(signature)
        ):
            raise AuthenticationError(
                AuthFailureReason.MALFORMED_CREDENTIALS,
                "the timestamp, nonce or signature header is malformed",
            )
        if protocol != PROTOCOL_VERSION:
            raise AuthenticationError(
                AuthFailureReason.UNSUPPORTED_PROTOCOL,
                f"protocol version {protocol!r} is not supported (expected {PROTOCOL_VERSION})",
            )
        skew = abs(int(timestamp) - int(self._clock()))
        if skew > self._skew:
            raise AuthenticationError(
                AuthFailureReason.TIMESTAMP_OUT_OF_WINDOW,
                f"the request timestamp differs from the server clock by {skew} s "
                f"(limit {self._skew} s)",
            )
        expected = sign(self._key.secret, request_string(method, target, timestamp, nonce, body))
        if not signatures_match(expected, signature):
            raise AuthenticationError(
                AuthFailureReason.INVALID_SIGNATURE, "the request signature does not match"
            )
        self._nonces.remember(nonce)
        return nonce

    def sign_response(
        self, method: str, target: str, nonce: str, status: int, body: bytes
    ) -> dict[str, str]:
        """Return the authentication headers for a response to a request with *nonce*."""
        canonical = response_string(method, target, nonce, status, body)
        return {
            PROTOCOL_HEADER: PROTOCOL_VERSION,
            SIGNATURE_HEADER: sign(self._key.secret, canonical),
        }
