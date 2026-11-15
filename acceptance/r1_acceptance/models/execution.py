"""Execution: the raw outcome of one command that the harness ran."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class Execution:
    """What one command produced: an ``orbital-bridge`` process, or the unsigned HTTP probe.

    For a process, ``stdout`` and ``stderr`` are its raw output and ``document`` is the JSON
    object it printed. For the HTTP probe, ``stdout`` is the raw response (status line, headers
    and body) and ``document`` is its parsed form.
    """

    EXITED: ClassVar[str] = "exited"
    INTERRUPTED: ClassVar[str] = "interrupted"
    HARNESS_TIMEOUT: ClassVar[str] = "harness-timeout"
    START_FAILED: ClassVar[str] = "start-failed"
    HTTP_RESPONSE: ClassVar[str] = "http-response"
    NO_RESPONSE: ClassVar[str] = "no-response"

    started_at: str
    finished_at: str
    duration_seconds: float
    outcome: str
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    document: dict[str, Any] | None
    parse_error: str | None
