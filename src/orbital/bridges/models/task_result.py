"""Structured result of a delegated task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Self

from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.error_detail import ErrorDetail
from orbital.bridges.models.task_status import TaskStatus
from orbital.bridges.models.utils import (
    is_task_id,
    read_optional_str,
    read_str,
    require_exact_keys,
    require_object,
)


@dataclass(frozen=True, slots=True)
class TaskResult:
    """The task id, its status, and either Claude's response or an error.

    Invariants (checked on construction):

    * ``running``: no response; no error, or an error whose code is ``wait_deadline_reached``.
    * ``succeeded``: a response (possibly empty) and no error.
    * any other status: no response, and an error whose code belongs to that status.
    """

    task_id: str
    status: TaskStatus
    response: str | None = None
    error: ErrorDetail | None = None

    KEYS: ClassVar[frozenset[str]] = frozenset({"task_id", "status", "response", "error"})

    def __post_init__(self) -> None:
        if not is_task_id(self.task_id):
            raise ValueError("task_id must be a canonical, lowercase UUID version 4")
        if not isinstance(self.status, TaskStatus):
            raise ValueError("status must be a TaskStatus")
        if self.response is not None and not isinstance(self.response, str):
            raise ValueError("response must be a string or None")
        if self.error is not None and not isinstance(self.error, ErrorDetail):
            raise ValueError("error must be an ErrorDetail or None")
        if self.status is TaskStatus.RUNNING:
            if self.response is not None:
                raise ValueError("a running result has no response")
            if self.error is not None and self.error.code is not ErrorCode.WAIT_DEADLINE_REACHED:
                raise ValueError("a running result can only carry wait_deadline_reached")
        elif self.status is TaskStatus.SUCCEEDED:
            if self.response is None or self.error is not None:
                raise ValueError("a succeeded result has a response and no error")
        else:
            if self.response is not None or self.error is None:
                raise ValueError(f"a {self.status} result has an error and no response")
            if self.error.code.category is not self.status:
                raise ValueError(f"error code {self.error.code} does not belong to {self.status}")

    @classmethod
    def running(cls, task_id: str) -> Self:
        """A ``running`` snapshot of *task_id*."""
        return cls(task_id, TaskStatus.RUNNING)

    @classmethod
    def succeeded(cls, task_id: str, response: str) -> Self:
        """A ``succeeded`` result carrying Claude Code's final result text."""
        return cls(task_id, TaskStatus.SUCCEEDED, response=response)

    @classmethod
    def from_error(cls, task_id: str, code: ErrorCode, message: str) -> Self:
        """A result whose status is the category of *code*."""
        return cls(task_id, code.category, error=ErrorDetail(code, message))

    def to_dict(self) -> dict[str, object]:
        """Return the wire form, which is also what the CLI prints."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "response": self.response,
            "error": None if self.error is None else self.error.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        """Strictly parse the wire form; raise ``ValueError`` if it is invalid."""
        document = require_object(value, "result")
        require_exact_keys(document, cls.KEYS, "result")
        status = read_str(document, "status", "result")
        try:
            parsed = TaskStatus(status)
        except ValueError:
            raise ValueError(f"result.status {status!r} is not a known status") from None
        error = document["error"]
        return cls(
            read_str(document, "task_id", "result"),
            parsed,
            read_optional_str(document, "response", "result"),
            None if error is None else ErrorDetail.from_dict(error),
        )
