"""PhaseDefinition: one automated action of a step, and what it must observe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class PhaseDefinition:
    """An automated action of a step, the stage it runs in, and its expected observation.

    ``rerun`` says when running the stage again repeats the phase:

    - ``never``: a submission is never repeated automatically;
    - ``on-failure``: side-effect-free checks are repeated until they pass;
    - ``until-settled``: a wait is repeated until the task settles;
    - ``if-unobserved``: a one-off observation is repeated only if it was interrupted.

    ``expect_codes`` lists the accepted error codes; empty means the error must be null.
    """

    PING: ClassVar[str] = "ping"
    WRONG_KEY_PING: ClassVar[str] = "wrong-key-ping"
    UNSIGNED_POST: ClassVar[str] = "unsigned-post"
    SUBMIT: ClassVar[str] = "submit"
    WAIT_SETTLE: ClassVar[str] = "wait-settle"
    WAIT_OBSERVE: ClassVar[str] = "wait-observe"
    FILE_ABSENT: ClassVar[str] = "file-absent"
    LOCAL_PACKAGE: ClassVar[str] = "local-package"

    NEVER: ClassVar[str] = "never"
    ON_FAILURE: ClassVar[str] = "on-failure"
    UNTIL_SETTLED: ClassVar[str] = "until-settled"
    IF_UNOBSERVED: ClassVar[str] = "if-unobserved"

    phase_id: str
    step_id: str
    stage_id: str
    kind: str
    title: str
    rerun: str
    prompt: str | None = None
    execution_timeout: int | None = None
    max_wait: float | None = None
    expect_status: str | None = None
    expect_codes: tuple[str, ...] = ()
    expect_exit: int | None = None
    expect_response: str | None = None
    expect_fragments: tuple[str, ...] = ()
    expect_header: tuple[str, str] | None = None
    expect_restart_after: str | None = None
    local_path: str | None = None

    def cli_arguments(self, task_id: str | None) -> tuple[str, ...]:
        """The ``orbital-bridge`` arguments of this phase, without the program name."""
        if self.kind in (self.PING, self.WRONG_KEY_PING):
            return ("ping",)
        if self.kind == self.SUBMIT and self.prompt is not None:
            arguments: list[str] = ["submit"]
            if self.execution_timeout is not None:
                arguments += ["--execution-timeout", str(self.execution_timeout)]
            return (*arguments, "--max-wait", "0", self.prompt)
        if self.kind in (self.WAIT_SETTLE, self.WAIT_OBSERVE) and task_id is not None:
            return ("wait", task_id, "--max-wait", f"{self.max_wait or 0:g}")
        raise ValueError(f"phase {self.phase_id} does not run orbital-bridge with these inputs")

    def expected_code_text(self) -> str:
        """The accepted error codes in words (``none`` when the error must be null)."""
        return " or ".join(self.expect_codes) if self.expect_codes else "none"
