"""Builds the structured (JSON) acceptance report of a run."""

from __future__ import annotations

from typing import Any

from r1_retest.evidence.evidence_store import EvidenceStore
from r1_retest.evidence.ledger import Ledger
from r1_retest.procedure.retest_procedure import RetestProcedure
from r1_retest.report.assessment import Assessment
from r1_retest.report.utils import LIMITATIONS, PASSED, VERDICT_LEGEND, counts
from r1_retest.utils import (
    HARNESS_NAME,
    HARNESS_VERSION,
    PREVIOUS_RUN_ID,
    REPORT_SCHEMA,
    format_time,
    utc_now,
)


class ReportBuilder:
    """The whole run as one JSON-serializable document; Markdown renders the same document."""

    def __init__(self, store: EvidenceStore, ledger: Ledger) -> None:
        self._store = store
        self._ledger = ledger

    def build(self) -> dict[str, Any]:
        assessment = Assessment(self._store, self._ledger)
        tests = assessment.tests()
        source = assessment.source()
        info = self._store.info()
        checks = [m["verdict"] for t in tests for m in t["manual"]]
        operations = [o["verdict"] for t in tests for o in t["operations"]]
        return {
            "schema": REPORT_SCHEMA,
            "generated_at": format_time(utc_now()),
            "generator": {
                "name": HARNESS_NAME,
                "version": HARNESS_VERSION,
                **info.get("harness", {}),
            },
            "run": {
                k: info.get(k) for k in ("run_id", "created_at", "url", "environment", "orbital")
            },
            "source": source,
            "overall": assessment.overall(tests, source),
            "counts": {
                "tests": counts(t["verdict"] for t in tests),
                "operations": counts(operations),
                "manual_checks": counts(checks),
            },
            "tests": tests,
            "criteria": assessment.criteria(tests),
            "carried_forward": {
                "run_id": PREVIOUS_RUN_ID,
                "located": info.get("previous_run"),
                "steps": [
                    {
                        "step": s,
                        "title": title,
                        "criteria": list(ac),
                        "verdict": PASSED,
                        "summary": text,
                    }
                    for s, title, ac, text in RetestProcedure.CARRIED_FORWARD
                ],
                "superseded": [{"step": s, "note": n} for s, n in RetestProcedure.SUPERSEDED],
            },
            "environment_check": self._ledger.environment_check(),
            "manual_records": [
                {
                    "check_id": e["check_id"],
                    "attempt": e.get("attempt"),
                    "file": e["file"],
                    "sha256": e["sha256"],
                    "imported_at": e["at"],
                    "observed_at": e["parsed"].get("observed_at") or e["parsed"].get("captured_at"),
                    "unavailable": e.get("unavailable"),
                    "problems": e["parsed"].get("problems", []),
                }
                for e in self._ledger.of_kind("manual-recorded")
            ],
            "attachments": [
                {k: e.get(k) for k in ("label", "file", "sha256", "bytes", "at", "origin")}
                for e in self._ledger.of_kind("attachment-added")
            ],
            "notes": [
                {"at": e["at"], "text": e["text"]} for e in self._ledger.of_kind("note-added")
            ],
            "preflights": [
                {
                    k: e.get(k)
                    for k in ("at", "stage_id", "expectation", "passed", "observed", "stdout")
                }
                for e in self._ledger.preflights()
            ],
            "previous_reports": [e.get("folder") for e in self._ledger.of_kind("report-generated")],
            "unreadable_events": self._store.unreadable_events(),
            "legend": [{"verdict": v, "meaning": m} for v, m in VERDICT_LEGEND],
            "limitations": list(LIMITATIONS),
            "evidence_index": self._store.evidence_index(),
        }
