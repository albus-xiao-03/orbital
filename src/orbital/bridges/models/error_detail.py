"""Error description carried by a task result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Self

from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.utils import read_str, require_exact_keys, require_object


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """A machine-readable error code with a human-readable message.

    The message must not be blank; messages longer than :attr:`MAX_MESSAGE_LENGTH`
    characters are truncated with a marker.
    """

    code: ErrorCode
    message: str

    MAX_MESSAGE_LENGTH: ClassVar[int] = 4000
    TRUNCATION_MARKER: ClassVar[str] = " [truncated]"
    KEYS: ClassVar[frozenset[str]] = frozenset({"code", "message"})

    def __post_init__(self) -> None:
        if not isinstance(self.code, ErrorCode):
            raise ValueError("code must be an ErrorCode")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be a non-blank string")
        if len(self.message) > self.MAX_MESSAGE_LENGTH:
            keep = self.MAX_MESSAGE_LENGTH - len(self.TRUNCATION_MARKER)
            object.__setattr__(self, "message", self.message[:keep] + self.TRUNCATION_MARKER)

    def to_dict(self) -> dict[str, str]:
        """Return the wire form ``{"code": ..., "message": ...}``."""
        return {"code": self.code.value, "message": self.message}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        """Strictly parse the wire form; raise ``ValueError`` if it is invalid."""
        document = require_object(value, "error")
        require_exact_keys(document, cls.KEYS, "error")
        code = read_str(document, "code", "error")
        try:
            parsed = ErrorCode(code)
        except ValueError:
            raise ValueError(f"error.code {code!r} is not a known error code") from None
        return cls(parsed, read_str(document, "message", "error"))
