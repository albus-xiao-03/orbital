"""One automated bridge operation of the re-test (an `orbital-bridge` command)."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

TASK_PLACEHOLDER = "{task_id}"


@dataclass(frozen=True)
class Operation:
    """An `orbital-bridge` command and the outcome plans/R1.md (revision 6) expects of it.

    ``expect_status`` is ``None`` for ``ping``, whose expected output is ``{"ok": true}``.
    ``expect_codes`` lists the accepted error codes; ``None`` in it means "no error".
    """

    op_id: str
    test_id: str
    stage_id: str
    description: str
    arguments: tuple[str, ...]
    expect_status: str | None
    expect_codes: tuple[str | None, ...]
    expect_exit: int
    budget_seconds: float
    starts_claude: bool = False
    uses_task: bool = False
    checks_restart: bool = False

    def command(self, task_id: str | None) -> tuple[str, ...]:
        if self.uses_task:
            if task_id is None:
                raise ValueError(f"{self.op_id} needs the task id of its test")
            return tuple(task_id if a == TASK_PLACEHOLDER else a for a in self.arguments)
        return self.arguments

    def display(self, task_id: str | None) -> str:
        shown = task_id if task_id is not None else "<task_id>"
        arguments = tuple(shown if a == TASK_PLACEHOLDER else a for a in self.arguments)
        return "orbital-bridge " + shlex.join(arguments)

    def expected_text(self) -> str:
        if self.expect_status is None:
            return f'{{"ok": true, "error": null}}, exit {self.expect_exit}'
        codes = " or ".join(c if c is not None else "no error" for c in self.expect_codes)
        return f"{self.expect_status} / {codes} / exit {self.expect_exit}"
