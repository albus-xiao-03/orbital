"""Verdict: the result of a check, a step, an acceptance criterion or a whole run."""

from __future__ import annotations

from enum import StrEnum


class Verdict(StrEnum):
    """Result categories used throughout the evidence and the reports.

    ``passed``, ``failed`` and ``skipped`` are final. ``pending`` has not run (or, for a manual
    check, has not been recorded). ``in-progress`` started but has not settled; running its stage
    again continues it. ``needs-decision`` was interrupted while submitting, so the operator
    chooses between resubmitting and skipping. ``pending-manual`` passed every automated check
    and waits for the operator's observations of the Claude sandbox. ``incomplete`` has no
    failure, but a check was skipped.
    """

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    NEEDS_DECISION = "needs-decision"
    PENDING_MANUAL = "pending-manual"
    INCOMPLETE = "incomplete"
