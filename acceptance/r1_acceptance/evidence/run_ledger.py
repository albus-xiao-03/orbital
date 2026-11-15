"""RunLedger: the state of an acceptance run, derived only from its events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from r1_acceptance.models.check_result import CheckResult
from r1_acceptance.models.command_record import CommandRecord
from r1_acceptance.models.manual_check import ManualCheck
from r1_acceptance.models.phase_definition import PhaseDefinition
from r1_acceptance.models.phase_result import PhaseResult
from r1_acceptance.models.stage_definition import StageDefinition
from r1_acceptance.models.step_definition import StepDefinition
from r1_acceptance.models.step_status import StepStatus
from r1_acceptance.models.verdict import Verdict


class RunLedger:
    """What happened in a run: attempts, commands, phase results, manual records and skips.

    Everything is derived from the run's events, which are never changed. A later event
    supersedes an earlier one only in these ways:

    - a phase's latest evaluation in an attempt counts;
    - the latest manual record of a check for an attempt counts;
    - a skip counts while it is newer than the step's latest attempt;
    - a command that started after its phase's latest evaluation but was never evaluated
      (because the harness stopped) leaves the phase unresolved: an unknown submission, a wait
      to continue, or an interrupted observation.
    """

    STAGE_STARTED: ClassVar[str] = "stage-started"
    STAGE_FINISHED: ClassVar[str] = "stage-finished"
    ATTEMPT_STARTED: ClassVar[str] = "attempt-started"
    COMMAND_STARTED: ClassVar[str] = "command-started"
    COMMAND_FINISHED: ClassVar[str] = "command-finished"
    PHASE_EVALUATED: ClassVar[str] = "phase-evaluated"
    PREFLIGHT: ClassVar[str] = "preflight"
    MANUAL_RECORDED: ClassVar[str] = "manual-recorded"
    STEP_SKIPPED: ClassVar[str] = "step-skipped"
    REPORT_GENERATED: ClassVar[str] = "report-generated"

    def __init__(
        self,
        events: Sequence[Mapping[str, Any]],
        *,
        steps: Sequence[StepDefinition],
        phases: Sequence[PhaseDefinition],
        checks: Sequence[ManualCheck],
        stages: Sequence[StageDefinition],
    ) -> None:
        self._steps = {step.step_id: step for step in steps}
        self._phases = tuple(phases)
        self._checks = tuple(checks)
        self._stages = {stage.stage_id: stage for stage in stages}
        self._attempts: dict[str, list[tuple[int, int, str, str]]] = {}
        self._started: dict[int, dict[str, Any]] = {}
        self._finished: dict[int, CommandRecord] = {}
        self._evaluations: dict[tuple[str, int, str], list[tuple[int, PhaseResult]]] = {}
        self._skips: dict[str, list[tuple[int, str, str]]] = {}
        self._manual: dict[tuple[str, int], list[tuple[int, CheckResult]]] = {}
        self._stage_events: list[dict[str, Any]] = []
        self._preflights: list[dict[str, Any]] = []
        self._reports: list[dict[str, Any]] = []
        for event in events:
            try:
                self._index(event)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"event {event.get('seq')!r} ({event.get('kind')!r}) is malformed: {exc}"
                ) from exc

    def phases_of(self, step_id: str, stage_id: str | None = None) -> tuple[PhaseDefinition, ...]:
        """The phases of a step (only those of *stage_id*, if given), in procedure order."""
        return tuple(
            phase
            for phase in self._phases
            if phase.step_id == step_id and (stage_id is None or phase.stage_id == stage_id)
        )

    def checks_of(self, step_id: str) -> tuple[ManualCheck, ...]:
        """The manual checks of a step."""
        return tuple(check for check in self._checks if check.step_id == step_id)

    def latest_attempt(self, step_id: str) -> int:
        """The number of the step's latest attempt (0 if it never started)."""
        return max((entry[0] for entry in self._attempts.get(step_id, [])), default=0)

    def attempts(self, step_id: str) -> list[dict[str, Any]]:
        """Every attempt of a step: number, start time and reason."""
        return [
            {"attempt": attempt, "started_at": at, "reason": reason}
            for attempt, _, at, reason in self._attempts.get(step_id, [])
        ]

    def command(self, command_id: int) -> CommandRecord | None:
        """The record of a finished command."""
        return self._finished.get(command_id)

    def command_started(self, command_id: int) -> Mapping[str, Any] | None:
        """The ``command-started`` payload of a command (with its time as ``at``)."""
        return self._started.get(command_id)

    def evaluations(self, step_id: str, attempt: int, phase_id: str) -> list[PhaseResult]:
        """Every evaluation of a phase in an attempt, oldest first."""
        return [result for _, result in self._evaluations.get((step_id, attempt, phase_id), [])]

    def unevaluated_commands(self, phase: PhaseDefinition, attempt: int) -> list[int]:
        """The phase's commands that started after its latest evaluation, oldest first."""
        entries = self._evaluations.get((phase.step_id, attempt, phase.phase_id), [])
        after = entries[-1][0] if entries else 0
        return sorted(
            command_id
            for command_id, started in self._started.items()
            if command_id > after
            and started.get("step") == phase.step_id
            and started.get("attempt") == attempt
            and started.get("phase") == phase.phase_id
        )

    def effective_result(self, phase: PhaseDefinition, attempt: int) -> PhaseResult | None:
        """The phase's current result in an attempt, taking unevaluated commands into account."""
        entries = self._evaluations.get((phase.step_id, attempt, phase.phase_id), [])
        latest = entries[-1][1] if entries else None
        pending = self.unevaluated_commands(phase, attempt)
        if not pending:
            return latest
        command_id = pending[-1]
        if phase.kind == PhaseDefinition.SUBMIT:
            state = PhaseResult.UNKNOWN
        elif phase.kind == PhaseDefinition.WAIT_SETTLE:
            state = PhaseResult.AWAITING
        else:
            state = PhaseResult.INTERRUPTED
        diagnostic = (
            "the command finished, but the harness stopped before evaluating it"
            if command_id in self._finished
            else "the harness stopped while this command was running; no result was recorded"
        )
        return PhaseResult(
            phase_id=phase.phase_id,
            step_id=phase.step_id,
            attempt=attempt,
            state=state,
            task_id=None
            if phase.kind == PhaseDefinition.SUBMIT
            else self.task_id(phase.step_id, attempt),
            observed_status=None,
            observed_code=None,
            observed_exit=None,
            response=None,
            message=None,
            checks=(),
            command_ids=(command_id,),
            evaluated_at=str(self._started[command_id]["at"]),
            diagnostics=(diagnostic,),
        )

    def task_id(self, step_id: str, attempt: int) -> str | None:
        """The task id that the step's submission in an attempt obtained."""
        for phase in self.phases_of(step_id):
            if phase.kind != PhaseDefinition.SUBMIT:
                continue
            for result in reversed(self.evaluations(step_id, attempt, phase.phase_id)):
                if result.task_id is not None:
                    return result.task_id
        return None

    def phase_finished_at(self, step_id: str, attempt: int, phase_id: str) -> str | None:
        """When the command behind a phase's latest evaluation finished."""
        evaluations = self.evaluations(step_id, attempt, phase_id)
        if not evaluations:
            return None
        for command_id in reversed(evaluations[-1].command_ids):
            record = self._finished.get(command_id)
            if record is not None and record.finished_at is not None:
                return record.finished_at
        return None

    def skip_reason(self, step_id: str) -> str | None:
        """The reason of the step's skip, if a skip is newer than its latest attempt."""
        skips = self._skips.get(step_id, [])
        if not skips:
            return None
        sequence, _, reason = skips[-1]
        latest_start = max((entry[1] for entry in self._attempts.get(step_id, [])), default=0)
        return reason if sequence > latest_start else None

    def skips(self, step_id: str) -> list[dict[str, Any]]:
        """Every skip of a step: time and reason."""
        return [{"at": at, "reason": reason} for _, at, reason in self._skips.get(step_id, [])]

    def manual_record(self, check_id: str, attempt: int) -> CheckResult | None:
        """The latest record of a manual check for an attempt."""
        entries = self._manual.get((check_id, attempt), [])
        return entries[-1][1] if entries else None

    def manual_history(self, check_id: str) -> list[dict[str, Any]]:
        """Every record of a manual check, for every attempt, oldest first."""
        history = [
            (sequence, attempt, result)
            for (identifier, attempt), entries in self._manual.items()
            if identifier == check_id
            for sequence, result in entries
        ]
        return [{"attempt": attempt, **result.to_dict()} for _, attempt, result in sorted(history)]

    def stage_started_at(self, stage_id: str) -> str | None:
        """When a stage first started, or ``None`` if it never did."""
        for event in self._stage_events:
            if event["kind"] == self.STAGE_STARTED and event.get("stage") == stage_id:
                return str(event["at"])
        return None

    def stage_events(self) -> list[dict[str, Any]]:
        """Every start and finish of a stage, in order."""
        return list(self._stage_events)

    def preflights(self) -> list[dict[str, Any]]:
        """Every preflight check made before a stage, in order."""
        return list(self._preflights)

    def reports(self) -> list[dict[str, Any]]:
        """Every report generated so far, in order."""
        return list(self._reports)

    def automated_verdict(
        self, step_id: str, attempt: int
    ) -> tuple[Verdict, tuple[PhaseResult, ...], tuple[str, ...]]:
        """The verdict of a step's automated phases in an attempt, with their results."""
        if attempt == 0:
            return Verdict.PENDING, (), ()
        phases = self.phases_of(step_id)
        results = [self.effective_result(phase, attempt) for phase in phases]
        present = tuple(result for result in results if result is not None)
        if any(result.state == PhaseResult.UNKNOWN for result in present):
            return (
                Verdict.NEEDS_DECISION,
                present,
                ("a submission was interrupted, so the task may or may not have been accepted",),
            )
        refused = any(
            phase.kind == PhaseDefinition.SUBMIT
            and result is not None
            and result.state == PhaseResult.NOT_EXECUTED
            for phase, result in zip(phases, results, strict=True)
        )
        if refused:
            return (
                Verdict.PENDING,
                present,
                ("the last submission was refused or never sent, so nothing ran",),
            )
        if any(result is None or not result.settled for result in results):
            return (Verdict.IN_PROGRESS if present else Verdict.PENDING), present, ()
        if all(result.state == PhaseResult.PASSED for result in present):
            return Verdict.PASSED, present, ()
        return Verdict.FAILED, present, ()

    def step_status(self, step_id: str) -> StepStatus:
        """The derived state of a step: its latest attempt, phases, manual checks and verdict."""
        step = self._steps[step_id]
        attempt = self.latest_attempt(step_id)
        automated, phases, notes = self.automated_verdict(step_id, attempt)
        manual = tuple(self._manual_result(check, attempt) for check in self.checks_of(step_id))
        skipped = self.skip_reason(step_id)
        return StepStatus(
            step=step,
            verdict=self._combine(automated, manual, skipped),
            automated=automated,
            attempt=attempt,
            task_id=self.task_id(step_id, attempt) if attempt else None,
            phases=phases,
            manual=manual,
            skipped_reason=skipped,
            notes=notes,
        )

    def stage_complete(self, stage_id: str) -> bool:
        """Whether every phase of the stage has a definitive result (or its step is skipped)."""
        stage = self._stages[stage_id]
        for step_id in stage.steps:
            if self.skip_reason(step_id) is not None:
                continue
            attempt = self.latest_attempt(step_id)
            if attempt == 0:
                return False
            for phase in self.phases_of(step_id, stage_id):
                result = self.effective_result(phase, attempt)
                if result is None or not result.settled:
                    return False
        return True

    def _manual_result(self, check: ManualCheck, attempt: int) -> CheckResult:
        recorded = self.manual_record(check.check_id, attempt) if attempt else None
        if recorded is not None:
            return recorded
        return CheckResult(
            check_id=check.check_id,
            description=check.title,
            source=CheckResult.MANUAL,
            verdict=Verdict.PENDING,
            expected=check.expectation,
            observed="",
            diagnostic="not recorded yet",
        )

    @staticmethod
    def _combine(automated: Verdict, manual: Sequence[CheckResult], skipped: str | None) -> Verdict:
        if skipped is not None:
            return Verdict.SKIPPED
        if automated is Verdict.FAILED or any(m.verdict is Verdict.FAILED for m in manual):
            return Verdict.FAILED
        if automated is not Verdict.PASSED:
            return automated
        if any(m.verdict is Verdict.PENDING for m in manual):
            return Verdict.PENDING_MANUAL
        if any(m.verdict is Verdict.SKIPPED for m in manual):
            return Verdict.INCOMPLETE
        return Verdict.PASSED

    def _index(self, event: Mapping[str, Any]) -> None:
        sequence = int(event["seq"])
        kind = str(event["kind"])
        at = str(event["at"])
        payload = event["payload"]
        if not isinstance(payload, Mapping):
            raise ValueError("the payload must be an object")
        if kind == self.ATTEMPT_STARTED:
            self._attempts.setdefault(str(payload["step"]), []).append(
                (int(payload["attempt"]), sequence, at, str(payload.get("reason", "")))
            )
        elif kind == self.COMMAND_STARTED:
            self._started[sequence] = {**payload, "at": at}
        elif kind == self.COMMAND_FINISHED:
            record = CommandRecord.from_dict(payload)
            self._finished[record.command_id] = record
        elif kind == self.PHASE_EVALUATED:
            result = PhaseResult.from_dict(payload)
            key = (result.step_id, result.attempt, result.phase_id)
            self._evaluations.setdefault(key, []).append((sequence, result))
        elif kind == self.STEP_SKIPPED:
            self._skips.setdefault(str(payload["step"]), []).append(
                (sequence, at, str(payload["reason"]))
            )
        elif kind == self.MANUAL_RECORDED:
            check = CheckResult.from_dict(payload["result"])
            key_manual = (check.check_id, int(payload["attempt"]))
            self._manual.setdefault(key_manual, []).append((sequence, check))
        elif kind in (self.STAGE_STARTED, self.STAGE_FINISHED):
            self._stage_events.append({**payload, "kind": kind, "seq": sequence, "at": at})
        elif kind == self.PREFLIGHT:
            self._preflights.append({**payload, "seq": sequence, "at": at})
        elif kind == self.REPORT_GENERATED:
            self._reports.append({**payload, "seq": sequence, "at": at})
