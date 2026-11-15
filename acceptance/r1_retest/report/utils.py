"""Static helpers of the assessment and the reports: verdicts and text formatting."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

PASSED = "passed"
FAILED = "failed"
PENDING = "pending"
INCONCLUSIVE = "inconclusive"
NOT_APPLICABLE = "not-applicable"
SEVERITY = (FAILED, INCONCLUSIVE, PENDING, PASSED)

VERDICT_LEGEND = (
    (PASSED, "the evidence shows the expected result"),
    (FAILED, "the evidence shows a different result"),
    (PENDING, "evidence still to be produced or recorded"),
    (
        INCONCLUSIVE,
        "evidence is present but cannot establish the result (for example a late or "
        "untimed observation, or a procedure deviation); repeat or complete it",
    ),
    (NOT_APPLICABLE, "does not apply (an optional test not run, or a check without a task)"),
)
LIMITATIONS = (
    "Automated checks ran in the ChatGPT sandbox only, through the orbital-bridge command line.",
    "Claude-side results are the operator's pasted observations; the harness never observed the "
    "Claude sandbox itself. It times them only by the Claude sandbox's own clock, as captured in "
    "the pasted output.",
    "When an observation was imported into the harness does not affect its verdict; when it was "
    "made does.",
    "Evidence carried forward from the earlier run was not re-executed.",
)


def combine(verdicts: Iterable[str]) -> str:
    """The most severe verdict; ``not-applicable`` only when nothing else applies."""
    present = [v for v in verdicts if v != NOT_APPLICABLE]
    if not present:
        return NOT_APPLICABLE
    for verdict in SEVERITY:
        if verdict in present:
            return verdict
    return INCONCLUSIVE


def counts(verdicts: Iterable[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for verdict in verdicts:
        found[verdict] = found.get(verdict, 0) + 1
    return found


def md_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def md_code(value: Any) -> str:
    if value is None or value == "":
        return "-"
    text = str(value).replace("\n", " ").replace("|", "\\|").replace("`", "'")
    return f"`{text}`"


def bold(verdict: str) -> str:
    return f"**{verdict}**"
