"""StepDefinition: a step of the acceptance procedure."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StepDefinition:
    """A step (P-1, D-1 ... D-9), what it demonstrates, and the criteria it supports.

    ``expected`` is the plan's expected result in words. ``claude_runs`` is the number of real
    Claude runs that one attempt of the step starts.
    """

    step_id: str
    title: str
    purpose: str
    expected: str
    criteria: tuple[str, ...]
    optional: bool = False
    claude_runs: int = 0
