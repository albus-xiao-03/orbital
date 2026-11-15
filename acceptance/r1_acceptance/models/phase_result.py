"""PhaseResult: the evaluation of one execution of a phase."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from r1_acceptance.models.check_result import CheckResult
from r1_acceptance.models.utils import (
    read_int,
    read_int_tuple,
    read_optional_int,
    read_optional_str,
    read_str,
    read_str_tuple,
    require_object,
)


@dataclass(frozen=True, slots=True)
class PhaseResult:
    """How one execution of a phase was judged (kept as a ``phase-evaluated`` event).

    ``state`` is one of:

    - ``passed`` / ``failed``: a definitive observation;
    - ``awaiting``: the task has not settled yet; running the stage again continues waiting;
    - ``unknown``: a submission was interrupted, so the task may or may not have been accepted;
    - ``not-executed``: the submission was refused or never sent, so nothing ran;
    - ``interrupted``: an observation was cut short; running the stage again repeats it.
    """

    PASSED: ClassVar[str] = "passed"
    FAILED: ClassVar[str] = "failed"
    AWAITING: ClassVar[str] = "awaiting"
    UNKNOWN: ClassVar[str] = "unknown"
    NOT_EXECUTED: ClassVar[str] = "not-executed"
    INTERRUPTED: ClassVar[str] = "interrupted"

    phase_id: str
    step_id: str
    attempt: int
    state: str
    task_id: str | None
    observed_status: str | None
    observed_code: str | None
    observed_exit: int | None
    response: str | None
    message: str | None
    checks: tuple[CheckResult, ...]
    command_ids: tuple[int, ...]
    evaluated_at: str
    diagnostics: tuple[str, ...] = ()

    @property
    def settled(self) -> bool:
        """Whether the observation is definitive (passed or failed)."""
        return self.state in (self.PASSED, self.FAILED)

    def to_dict(self) -> dict[str, Any]:
        """The JSON form kept in the evidence."""
        return {
            "phase_id": self.phase_id,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "state": self.state,
            "task_id": self.task_id,
            "observed_status": self.observed_status,
            "observed_code": self.observed_code,
            "observed_exit": self.observed_exit,
            "response": self.response,
            "message": self.message,
            "checks": [check.to_dict() for check in self.checks],
            "command_ids": list(self.command_ids),
            "evaluated_at": self.evaluated_at,
            "diagnostics": list(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PhaseResult:
        """Read the JSON form back; ``ValueError`` if it is malformed."""
        checks = data.get("checks", [])
        if not isinstance(checks, list):
            raise ValueError("'checks' must be a list")
        return cls(
            phase_id=read_str(data, "phase_id"),
            step_id=read_str(data, "step_id"),
            attempt=read_int(data, "attempt"),
            state=read_str(data, "state"),
            task_id=read_optional_str(data, "task_id"),
            observed_status=read_optional_str(data, "observed_status"),
            observed_code=read_optional_str(data, "observed_code"),
            observed_exit=read_optional_int(data, "observed_exit"),
            response=read_optional_str(data, "response"),
            message=read_optional_str(data, "message"),
            checks=tuple(CheckResult.from_dict(require_object(item, "check")) for item in checks),
            command_ids=read_int_tuple(data, "command_ids"),
            evaluated_at=read_str(data, "evaluated_at"),
            diagnostics=read_str_tuple(data, "diagnostics"),
        )
