"""ManualCheck: an observation of the Claude sandbox that only the operator can make."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ManualCheck:
    """A check of the Claude sandbox: where and when to make it, how, and what to expect.

    ``command``, ``expectation`` and ``expected_fragments`` may contain ``{serve_log}``,
    ``{claude_workdir}`` and ``{task_id}``. When the operator records the observed output,
    ``expected_text`` (exact match after trimming) or ``expected_fragments`` (all present) let
    the harness say whether the output matches the expectation; the verdict stays the
    operator's. ``before_stage`` names the stage that must not have started when the
    observation is made.
    """

    check_id: str
    step_id: str
    title: str
    where: str
    when: str
    command: str
    expectation: str
    expected_text: str | None = None
    expected_fragments: tuple[str, ...] = ()
    before_stage: str | None = None
