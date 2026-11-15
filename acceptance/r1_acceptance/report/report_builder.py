"""ReportBuilder: the consolidated acceptance report, as a JSON-ready document."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from r1_acceptance.evidence.evidence_store import EvidenceStore
from r1_acceptance.evidence.run_ledger import RunLedger
from r1_acceptance.models.manual_check import ManualCheck
from r1_acceptance.models.step_status import StepStatus
from r1_acceptance.models.verdict import Verdict
from r1_acceptance.procedure.r1_procedure import R1Procedure
from r1_acceptance.procedure.utils import excerpt, placeholder_values, render
from r1_acceptance.report.utils import (
    LIMITATIONS,
    VERDICT_LEGEND,
    counts,
    criterion_verdict,
    overall_verdict,
)
from r1_acceptance.utils import (
    HARNESS_NAME,
    HARNESS_VERSION,
    REPORT_SCHEMA,
    format_time,
    parse_time,
    utc_now,
)


class ReportBuilder:
    """Builds the report of a run from its evidence: steps, criteria, manual checks, index.

    Every step lists the expected and observed status, error code and exit code of each phase,
    the commands with their timestamps, exit codes and raw output, and the manual checks with
    the operator's records. Nothing is inferred beyond the recorded evidence.
    """

    STDERR_EXCERPT_CHARS = 4000

    def __init__(self, store: EvidenceStore, ledger: RunLedger) -> None:
        self._store = store
        self._ledger = ledger
        self._settings: Mapping[str, Any] = store.info.get("settings", {})

    def build(self) -> dict[str, Any]:
        """The report document."""
        statuses = {
            step.step_id: self._ledger.step_status(step.step_id) for step in R1Procedure.STEPS
        }
        criteria: list[dict[str, Any]] = []
        for criterion_id, title in R1Procedure.CRITERIA:
            verdict, notes = criterion_verdict(criterion_id, statuses)
            criteria.append(
                {
                    "criterion_id": criterion_id,
                    "title": title,
                    "steps": list(R1Procedure.criterion_steps(criterion_id)),
                    "step_verdicts": {
                        step_id: statuses[step_id].verdict.value
                        for step_id in R1Procedure.criterion_steps(criterion_id)
                    },
                    "verdict": verdict.value,
                    "notes": notes,
                }
            )
        step_verdicts = [status.verdict for status in statuses.values()]
        criterion_verdicts = [Verdict(item["verdict"]) for item in criteria]
        overall = overall_verdict(step_verdicts, criterion_verdicts)
        manual = [check for status in statuses.values() for check in status.manual]
        return {
            "schema": REPORT_SCHEMA,
            "generated_at": format_time(utc_now()),
            "generator": {"name": HARNESS_NAME, "version": HARNESS_VERSION},
            "run": dict(self._store.info),
            "overall": {
                "verdict": overall.value,
                "summary": self._summary(overall, statuses),
            },
            "counts": {
                "steps": counts(step_verdicts),
                "criteria": counts(criterion_verdicts),
                "manual_checks": counts([check.verdict for check in manual]),
            },
            "criteria": criteria,
            "steps": [self._step(statuses[step.step_id]) for step in R1Procedure.STEPS],
            "preflights": self._ledger.preflights(),
            "stages": self._ledger.stage_events(),
            "previous_reports": self._ledger.reports(),
            "legend": [{"verdict": v.value, "meaning": text} for v, text in VERDICT_LEGEND],
            "limitations": list(LIMITATIONS),
            "unreadable_events": self._store.unreadable_events(),
            "evidence_index": self._store.evidence_index(),
        }

    def _summary(self, overall: Verdict, statuses: Mapping[str, StepStatus]) -> str:
        if overall is Verdict.PASSED:
            return "Every acceptance criterion passed on the recorded evidence."
        groups: dict[str, list[str]] = {}
        for step_id, status in statuses.items():
            if status.verdict is not Verdict.PASSED:
                groups.setdefault(status.verdict.value, []).append(step_id)
        details = "; ".join(f"{verdict}: {', '.join(ids)}" for verdict, ids in groups.items())
        return f"Not every criterion passed ({details})."

    def _step(self, status: StepStatus) -> dict[str, Any]:
        step = status.step
        phases = []
        for phase in self._ledger.phases_of(step.step_id):
            result = next((r for r in status.phases if r.phase_id == phase.phase_id), None)
            history = (
                self._ledger.evaluations(step.step_id, status.attempt, phase.phase_id)
                if status.attempt
                else []
            )
            phases.append(
                {
                    "phase_id": phase.phase_id,
                    "title": phase.title,
                    "stage": phase.stage_id,
                    "expected": {
                        "status": phase.expect_status,
                        "error_code": list(phase.expect_codes) or None,
                        "exit_code": phase.expect_exit,
                        "response_contains": phase.expect_response,
                    },
                    "state": result.state if result is not None else "not run",
                    "result": result.to_dict() if result is not None else None,
                    "commands": [self._command(i) for i in result.command_ids] if result else [],
                    "earlier_evaluations": [item.to_dict() for item in history[:-1]],
                }
            )
        return {
            "step_id": step.step_id,
            "title": step.title,
            "purpose": step.purpose,
            "expected": step.expected,
            "criteria": list(step.criteria),
            "stages": list(R1Procedure.stages_of(step.step_id)),
            "optional": step.optional,
            "claude_runs_per_attempt": step.claude_runs,
            "verdict": status.verdict.value,
            "automated_verdict": status.automated.value,
            "attempt": status.attempt,
            "task_id": status.task_id,
            "skipped_reason": status.skipped_reason,
            "notes": list(status.notes),
            "attempts": self._ledger.attempts(step.step_id),
            "skips": self._ledger.skips(step.step_id),
            "superseded_attempts": self._superseded(step.step_id, status.attempt),
            "phases": phases,
            "manual_checks": [
                self._manual(R1Procedure.manual_check(check.check_id), status, check.to_dict())
                for check in status.manual
            ],
        }

    def _command(self, command_id: int) -> dict[str, Any]:
        record = self._ledger.command(command_id)
        started = self._ledger.command_started(command_id) or {}
        entry: dict[str, Any] = {
            "command_id": command_id,
            "display": started.get("display"),
            "key": started.get("key"),
        }
        if record is None:
            return {**entry, "outcome": "no result recorded", "started_at": started.get("at")}
        stderr = ""
        if record.stderr_file is not None:
            stderr = self._store.read_artifact(record.stderr_file).decode("utf-8", "replace")
        return {
            **entry,
            **record.to_dict(),
            "stderr_excerpt": stderr[-self.STDERR_EXCERPT_CHARS :],
        }

    def _manual(
        self, check: ManualCheck, status: StepStatus, recorded: Mapping[str, Any]
    ) -> dict[str, Any]:
        values = placeholder_values(self._settings, status.task_id)
        entry: dict[str, Any] = {
            **recorded,
            "where": check.where,
            "when": check.when,
            "command": render(check.command, values),
            "expected": render(check.expectation, values),
            "history": self._ledger.manual_history(check.check_id),
            "timing_note": None,
        }
        started = self._ledger.stage_started_at(check.before_stage) if check.before_stage else None
        recorded_at = recorded.get("recorded_at")
        if (
            started
            and isinstance(recorded_at, str)
            and parse_time(recorded_at) > parse_time(started)
        ):
            entry["timing_note"] = (
                f"recorded after stage {check.before_stage} started; make sure the observation "
                "itself was made before that stage"
            )
        return entry

    def _superseded(self, step_id: str, latest: int) -> list[dict[str, Any]]:
        """A summary of the step's earlier attempts, which no longer count."""
        summaries = []
        for attempt in range(1, latest):
            verdict, results, notes = self._ledger.automated_verdict(step_id, attempt)
            summaries.append(
                {
                    "attempt": attempt,
                    "automated_verdict": verdict.value,
                    "task_id": self._ledger.task_id(step_id, attempt),
                    "phases": {r.phase_id: r.state for r in results},
                    "notes": list(notes),
                    "diagnostics": [excerpt(d) for r in results for d in r.diagnostics],
                }
            )
        return summaries
