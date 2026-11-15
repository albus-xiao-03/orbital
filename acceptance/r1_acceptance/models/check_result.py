"""CheckResult: one automated or manual check, with its expectation and observation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from r1_acceptance.models.utils import read_optional_str, read_str
from r1_acceptance.models.verdict import Verdict


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One check: what was expected, what was observed, and the verdict.

    The harness evaluates *automated* checks from what it observes in the ChatGPT sandbox.
    *Manual* checks are observations of the Claude sandbox that the operator makes and records
    with ``r1-acceptance record``; their verdict is the operator's, never the harness's.
    """

    AUTOMATED: ClassVar[str] = "automated"
    MANUAL: ClassVar[str] = "manual"

    check_id: str
    description: str
    source: str
    verdict: Verdict
    expected: str
    observed: str
    diagnostic: str = ""
    recorded_at: str | None = None
    note: str = ""
    attachments: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """The JSON form kept in the evidence."""
        return {
            "check_id": self.check_id,
            "description": self.description,
            "source": self.source,
            "verdict": self.verdict.value,
            "expected": self.expected,
            "observed": self.observed,
            "diagnostic": self.diagnostic,
            "recorded_at": self.recorded_at,
            "note": self.note,
            "attachments": [dict(item) for item in self.attachments],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CheckResult:
        """Read the JSON form back; ``ValueError`` if it is malformed."""
        attachments = data.get("attachments", [])
        if not isinstance(attachments, list) or not all(isinstance(i, dict) for i in attachments):
            raise ValueError("'attachments' must be a list of objects")
        return cls(
            check_id=read_str(data, "check_id"),
            description=read_str(data, "description"),
            source=read_str(data, "source"),
            verdict=Verdict(read_str(data, "verdict")),
            expected=read_str(data, "expected"),
            observed=read_str(data, "observed"),
            diagnostic=read_optional_str(data, "diagnostic") or "",
            recorded_at=read_optional_str(data, "recorded_at"),
            note=read_optional_str(data, "note") or "",
            attachments=tuple(attachments),
        )
