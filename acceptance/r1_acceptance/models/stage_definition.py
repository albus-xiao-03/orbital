"""StageDefinition: the automated work between two manual checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class StageDefinition:
    """A stage of the procedure and the checkpoint that precedes it.

    ``before`` lists what the operator does at the checkpoint before the stage (it may contain
    ``{serve_log}`` and ``{claude_workdir}``). ``confirm`` is the token the operator passes
    with ``--confirm`` to state that the checkpoint was done; ``None`` means no confirmation is
    needed. ``preflight`` is ``reachable`` (a signed ping must succeed before anything is
    submitted), ``unreachable`` (the server must be down) or ``none``.
    """

    REACHABLE: ClassVar[str] = "reachable"
    UNREACHABLE: ClassVar[str] = "unreachable"
    NO_PREFLIGHT: ClassVar[str] = "none"

    stage_id: str
    title: str
    steps: tuple[str, ...]
    before: tuple[str, ...]
    confirm: str | None
    preflight: str
    claude_runs: int
    stop_on_failure: bool

    def command(self) -> str:
        """The command that runs this stage."""
        suffix = f" --confirm {self.confirm}" if self.confirm else ""
        return f"r1-acceptance run {self.stage_id}{suffix}"
