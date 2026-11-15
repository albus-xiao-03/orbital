"""One independently executable stage: a single automated operation between manual checkpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    """A stage runs exactly one operation, after an optional preflight ping.

    ``preflight`` is ``"reachable"`` (the server must answer a signed ping), ``"unreachable"``
    (it must not: it was stopped) or ``None``. ``needs_ready`` stages start a real Claude run and
    run only with ``--ready``. ``before`` and ``after`` are the operator's instructions; they may
    contain ``{task_id}`` and the placeholders of the procedure.
    """

    stage_id: str
    test_id: str
    title: str
    operation: str
    preflight: str | None
    needs_ready: bool
    before: tuple[str, ...]
    after: tuple[str, ...]

    def command(self, ready: bool = False) -> str:
        suffix = " --ready" if ready and self.needs_ready else ""
        return f"r1-retest run {self.stage_id}{suffix}"
