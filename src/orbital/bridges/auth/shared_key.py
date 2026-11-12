"""The pre-shared key both sides of the bridge sign with."""

from __future__ import annotations

import base64
import binascii
import re
from typing import ClassVar


class SharedKey:
    """Pre-shared HMAC key of at least 32 bytes. Its value never appears in ``repr`` or ``str``.

    Use :meth:`from_text` with base64url text, for example the output of
    ``python3 -c "import secrets; print(secrets.token_urlsafe(32))"``.
    """

    MIN_BYTES: ClassVar[int] = 32
    __slots__ = ("_secret",)

    def __init__(self, secret: bytes) -> None:
        if not isinstance(secret, bytes) or len(secret) < self.MIN_BYTES:
            raise ValueError(f"the shared key must be at least {self.MIN_BYTES} bytes")
        self._secret = secret

    @classmethod
    def from_text(cls, text: str) -> SharedKey:
        """Parse base64url text (padding optional) into a key; raise ``ValueError`` if invalid."""
        candidate = text.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", candidate):
            raise ValueError(
                "the shared key must be base64url text, such as the output of "
                "secrets.token_urlsafe(32)"
            )
        unpadded = candidate.rstrip("=")
        try:
            secret = base64.urlsafe_b64decode(unpadded + "=" * (-len(unpadded) % 4))
        except (binascii.Error, ValueError):
            raise ValueError("the shared key is not valid base64url text") from None
        return cls(secret)

    @property
    def secret(self) -> bytes:
        """The raw key bytes."""
        return self._secret

    def __repr__(self) -> str:
        return "SharedKey(<redacted>)"

    def __str__(self) -> str:
        return "SharedKey(<redacted>)"
