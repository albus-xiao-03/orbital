"""StepStatus: the derived state of a step."""

from __future__ import annotations

from dataclasses import dataclass

from r1_acceptance.models.check_result import CheckResult
from r1_acceptance.models.phase_result import PhaseResult
from r1_acceptance.models.step_definition import StepDefinition
from r1_acceptance.models.verdict import Verdict


@dataclass(frozen=True, slots=True)
class StepStatus:
    """A step's verdict and the evidence behind it, derived from the run's events.

    ``automated`` judges the automated phases alone; ``verdict`` also takes the manual checks
    and a skip into account. ``phases`` holds the latest evaluation of each phase of the latest
    attempt, and ``manual`` one entry per manual check of the step (``pending`` when the
    operator has not recorded it for that attempt).
    """

    step: StepDefinition
    verdict: Verdict
    automated: Verdict
    attempt: int
    task_id: str | None
    phases: tuple[PhaseResult, ...]
    manual: tuple[CheckResult, ...]
    skipped_reason: str | None
    notes: tuple[str, ...]
