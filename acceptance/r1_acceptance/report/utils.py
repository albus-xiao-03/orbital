"""Static helpers of the reports: criterion and overall verdicts, legend, Markdown text."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from r1_acceptance.models.step_status import StepStatus
from r1_acceptance.models.verdict import Verdict
from r1_acceptance.procedure.r1_procedure import R1Procedure

VERDICT_LEGEND = (
    (
        Verdict.PASSED,
        "every automated check passed and every manual check was recorded as passed",
    ),
    (Verdict.FAILED, "an automated check failed, or a manual check was recorded as failed"),
    (
        Verdict.PENDING_MANUAL,
        "every automated check passed; an observation of the Claude sandbox is not recorded yet",
    ),
    (Verdict.SKIPPED, "the operator skipped the step; the reason is recorded"),
    (Verdict.INCOMPLETE, "no failure, but a check was skipped, so it is not fully verified"),
    (Verdict.IN_PROGRESS, "started but not settled; running its stage again continues it"),
    (Verdict.NEEDS_DECISION, "interrupted while submitting; resubmit it or skip it"),
    (Verdict.PENDING, "not run yet"),
)
LIMITATIONS = (
    "Automated checks were made in the ChatGPT sandbox only, through the orbital-bridge command "
    "line and one unsigned HTTP request (D-3b).",
    "Manual checks are the operator's observations of the Claude sandbox, recorded with "
    "'r1-acceptance record'; the harness itself never observed the Claude sandbox.",
    "'succeeded' is Claude Code's own report of its run (plans/R1.md section 7); the harness "
    "checks the response text only where the procedure names an expected word.",
    "The local verification (static audit SA-01, packaging PKG-01 and the rest of the test "
    "matrix) is recorded in plans/R1.md section 20, not in this report.",
)
WAITING = frozenset({Verdict.PENDING, Verdict.IN_PROGRESS, Verdict.NEEDS_DECISION})


def criterion_verdict(
    criterion_id: str, statuses: Mapping[str, StepStatus]
) -> tuple[Verdict, list[str]]:
    """The verdict of an acceptance criterion from the steps that support it, with notes.

    A failed step fails the criterion. An unfinished required step leaves it pending, a pending
    manual check leaves it pending-manual, and a skipped or incomplete required step leaves it
    incomplete. An optional step (D-1) never blocks a criterion; when it did not pass, a note
    says so.
    """
    step_ids = R1Procedure.criterion_steps(criterion_id)
    failed = [s for s in step_ids if statuses[s].verdict is Verdict.FAILED]
    if failed:
        return Verdict.FAILED, [f"failed: {', '.join(failed)}"]
    required = [s for s in step_ids if not statuses[s].step.optional]
    waiting = [s for s in required if statuses[s].verdict in WAITING]
    if waiting:
        return Verdict.PENDING, [f"not finished: {', '.join(waiting)}"]
    manual = [s for s in required if statuses[s].verdict is Verdict.PENDING_MANUAL]
    if manual:
        return Verdict.PENDING_MANUAL, [f"manual checks pending: {', '.join(manual)}"]
    gaps = [s for s in required if statuses[s].verdict in (Verdict.SKIPPED, Verdict.INCOMPLETE)]
    if gaps:
        described = ", ".join(f"{s} {statuses[s].verdict.value}" for s in gaps)
        return Verdict.INCOMPLETE, [f"not fully verified: {described}"]
    notes = []
    for step_id in step_ids:
        status = statuses[step_id]
        if status.step.optional and status.verdict is not Verdict.PASSED:
            notes.append(
                f"optional {step_id} {status.verdict.value}: its observation is missing from "
                "this criterion's evidence"
            )
    return Verdict.PASSED, notes


def overall_verdict(steps: Sequence[Verdict], criteria: Sequence[Verdict]) -> Verdict:
    """The verdict of the whole run."""
    if Verdict.FAILED in steps or Verdict.FAILED in criteria:
        return Verdict.FAILED
    if all(verdict is Verdict.PASSED for verdict in criteria):
        return Verdict.PASSED
    if any(verdict is Verdict.PENDING for verdict in criteria):
        return Verdict.PENDING
    if any(verdict is Verdict.PENDING_MANUAL for verdict in criteria):
        return Verdict.PENDING_MANUAL
    return Verdict.INCOMPLETE


def counts(verdicts: Sequence[Verdict]) -> dict[str, int]:
    """How many of each verdict, in legend order (zeros omitted)."""
    result: dict[str, int] = {}
    for verdict, _ in VERDICT_LEGEND:
        number = sum(1 for item in verdicts if item is verdict)
        if number:
            result[verdict.value] = number
    return result


def md_cell(text: object) -> str:
    """*text* made safe for one Markdown table cell (``-`` when empty)."""
    value = "-" if text is None or text == "" else str(text)
    return " ".join(value.split()).replace("|", "\\|")


def md_code(text: object) -> str:
    """*text* as inline code, safe in a table cell (``-`` when empty)."""
    value = "" if text is None else " ".join(str(text).split())
    if not value:
        return "-"
    ticks = "``" if "`" in value else "`"
    escaped = value.replace("|", "\\|")
    return ticks + escaped + ticks


def fenced(text: str, language: str = "") -> list[str]:
    """*text* as a fenced code block (the fence is longer than any backtick run inside)."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return [f"{fence}{language}", text.rstrip("\n"), fence]
