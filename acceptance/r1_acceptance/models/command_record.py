"""CommandRecord: a command as kept in the evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from r1_acceptance.models.utils import (
    read_int,
    read_optional_float,
    read_optional_int,
    read_optional_object,
    read_optional_str,
    read_str,
)


@dataclass(frozen=True, slots=True)
class CommandRecord:
    """What ran, when, how it ended, and where its raw output is.

    ``command_id`` is the sequence number of the command's ``command-started`` event.
    ``stdout_file`` and ``stderr_file`` are relative to the run directory. ``document`` is the
    JSON object the CLI printed, or the parsed response of the unsigned HTTP probe.
    """

    command_id: int
    step_id: str
    attempt: int
    phase_id: str
    display: str
    started_at: str
    finished_at: str | None
    duration_seconds: float | None
    outcome: str
    exit_code: int | None
    stdout_file: str | None
    stderr_file: str | None
    stdout_sha256: str | None
    document: dict[str, Any] | None
    parse_error: str | None

    def to_dict(self) -> dict[str, Any]:
        """The JSON form kept in the evidence."""
        return {
            "command_id": self.command_id,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "phase_id": self.phase_id,
            "display": self.display,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "stdout_file": self.stdout_file,
            "stderr_file": self.stderr_file,
            "stdout_sha256": self.stdout_sha256,
            "document": self.document,
            "parse_error": self.parse_error,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CommandRecord:
        """Read the JSON form back; ``ValueError`` if it is malformed."""
        return cls(
            command_id=read_int(data, "command_id"),
            step_id=read_str(data, "step_id"),
            attempt=read_int(data, "attempt"),
            phase_id=read_str(data, "phase_id"),
            display=read_str(data, "display"),
            started_at=read_str(data, "started_at"),
            finished_at=read_optional_str(data, "finished_at"),
            duration_seconds=read_optional_float(data, "duration_seconds"),
            outcome=read_str(data, "outcome"),
            exit_code=read_optional_int(data, "exit_code"),
            stdout_file=read_optional_str(data, "stdout_file"),
            stderr_file=read_optional_str(data, "stderr_file"),
            stdout_sha256=read_optional_str(data, "stdout_sha256"),
            document=read_optional_object(data, "document"),
            parse_error=read_optional_str(data, "parse_error"),
        )
