"""StageRunner: runs one stage of the procedure and records every observation."""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar, TextIO

from r1_acceptance.bridge.bridge_cli import BridgeCli
from r1_acceptance.bridge.unsigned_probe import UnsignedProbe
from r1_acceptance.bridge.utils import KEY_VARIABLE, PUBLIC_API, display_command, import_bridges
from r1_acceptance.evidence.evidence_store import EvidenceStore
from r1_acceptance.evidence.run_ledger import RunLedger
from r1_acceptance.models.command_record import CommandRecord
from r1_acceptance.models.execution import Execution
from r1_acceptance.models.phase_definition import PhaseDefinition
from r1_acceptance.models.phase_result import PhaseResult
from r1_acceptance.models.stage_definition import StageDefinition
from r1_acceptance.models.verdict import Verdict
from r1_acceptance.procedure.errors import StageRefusedError
from r1_acceptance.procedure.r1_procedure import R1Procedure
from r1_acceptance.procedure.utils import (
    UNREACHABLE_CODES,
    decision_lines,
    error_fields,
    evaluate_file_absent,
    evaluate_local_package,
    evaluate_ping,
    evaluate_submit,
    evaluate_unsigned_post,
    evaluate_wait,
    excerpt,
    placeholder_values,
    render,
)
from r1_acceptance.utils import HARNESS_VERSION, format_time, sha256_bytes, utc_now


class StageRunner:
    """Runs one stage: works out what is left, runs it, and records every observation.

    The plan of a stage comes from the evidence alone. A phase with a definitive result is not
    repeated; an unsettled task is polled again, never resubmitted; a submission whose outcome is
    unknown stops the stage until the operator decides (``--resubmit`` or a skip). Before a stage
    contacts the bridge, a signed ping checks the expected server state, so that nothing is
    submitted to an unreachable or wrongly keyed server.
    """

    EXIT_OK: ClassVar[int] = 0
    EXIT_FAILURES: ClassVar[int] = 1
    EXIT_REFUSED: ClassVar[int] = 2
    EXIT_INCOMPLETE: ClassVar[int] = 3
    EXIT_INTERRUPTED: ClassVar[int] = 130
    CONTACTS_BRIDGE: ClassVar[frozenset[str]] = frozenset(
        {
            PhaseDefinition.PING,
            PhaseDefinition.WRONG_KEY_PING,
            PhaseDefinition.UNSIGNED_POST,
            PhaseDefinition.SUBMIT,
            PhaseDefinition.WAIT_SETTLE,
            PhaseDefinition.WAIT_OBSERVE,
        }
    )

    def __init__(
        self,
        *,
        store: EvidenceStore,
        cli: BridgeCli,
        probe: UnsignedProbe,
        orbital_src: Path,
        harness_digest: str,
        out: TextIO,
    ) -> None:
        self._store = store
        self._cli = cli
        self._probe = probe
        self._orbital_src = orbital_src
        self._harness_digest = harness_digest
        self._out = out
        self._settings: Mapping[str, Any] = store.info.get("settings", {})

    def ledger(self) -> RunLedger:
        """The run's current state."""
        return RunLedger(
            self._store.events(),
            steps=R1Procedure.STEPS,
            phases=R1Procedure.PHASES,
            checks=R1Procedure.MANUAL_CHECKS,
            stages=R1Procedure.STAGES,
        )

    def run(
        self,
        stage: StageDefinition,
        *,
        resubmit: frozenset[str] = frozenset(),
        confirmation: str | None = None,
        invocation: Sequence[str] = (),
    ) -> int:
        """Run *stage*; return an exit code. ``StageRefusedError`` if it cannot run now."""
        self.recover()
        plan = self._plan(stage, self.ledger(), resubmit)
        self._store.append_event(
            RunLedger.STAGE_STARTED,
            {
                "stage": stage.stage_id,
                "confirmation": confirmation,
                "resubmit": sorted(resubmit),
                "invocation": list(invocation),
                "harness_version": HARNESS_VERSION,
                "harness_digest": self._harness_digest,
            },
        )
        code = self.EXIT_INTERRUPTED
        try:
            code = self._execute(stage, plan)
        finally:
            self._store.append_event(
                RunLedger.STAGE_FINISHED, {"stage": stage.stage_id, "exit_code": code}
            )
        return code

    def recover(self) -> None:
        """Evaluate commands that finished but were never evaluated (the harness stopped)."""
        ledger = self.ledger()
        for step in R1Procedure.STEPS:
            attempt = ledger.latest_attempt(step.step_id)
            if attempt == 0:
                continue
            for phase in ledger.phases_of(step.step_id):
                if phase.kind not in self.CONTACTS_BRIDGE:
                    continue
                pending = ledger.unevaluated_commands(phase, attempt)
                record = ledger.command(pending[-1]) if pending else None
                if record is None:
                    continue
                result = self._evaluate(phase, attempt, record, ledger)
                notes = (*result.diagnostics, "evaluated when the harness resumed")
                payload = {**result.to_dict(), "diagnostics": list(notes)}
                self._store.append_event(RunLedger.PHASE_EVALUATED, payload)
                ledger = self.ledger()

    def _plan(
        self, stage: StageDefinition, ledger: RunLedger, resubmit: frozenset[str]
    ) -> list[tuple[str, int | None, str | None]]:
        unknown = sorted(resubmit - set(stage.steps))
        if unknown:
            raise StageRefusedError(
                f"--resubmit {', '.join(unknown)}: not a step of stage {stage.stage_id} "
                f"(its steps: {', '.join(stage.steps)})"
            )
        plan: list[tuple[str, int | None, str | None]] = []
        for step_id in stage.steps:
            status = ledger.step_status(step_id)
            submit_here = next(
                (
                    phase
                    for phase in ledger.phases_of(step_id, stage.stage_id)
                    if phase.kind == PhaseDefinition.SUBMIT
                ),
                None,
            )
            if step_id in resubmit:
                if submit_here is None:
                    first = R1Procedure.stages_of(step_id)[0]
                    raise StageRefusedError(f"{step_id} is resubmitted with stage {first}")
                if any(result.state == PhaseResult.AWAITING for result in status.phases):
                    raise StageRefusedError(
                        f"{step_id}'s task {status.task_id} has not settled; run "
                        f"'{stage.command()}' without --resubmit to let it settle first"
                    )
                reason = "resubmission requested with --resubmit"
                plan.append((step_id, status.attempt + 1, reason))
                continue
            if status.skipped_reason is not None:
                plan.append((step_id, None, f"skipped: {status.skipped_reason}"))
                continue
            if status.automated is Verdict.NEEDS_DECISION:
                raise StageRefusedError("\n".join(decision_lines(ledger, stage, self._settings)))
            if status.attempt == 0:
                if R1Procedure.stages_of(step_id)[0] != stage.stage_id:
                    raise StageRefusedError(
                        f"{step_id} starts in stage {R1Procedure.stages_of(step_id)[0]}"
                    )
                plan.append((step_id, 1, "first attempt"))
                continue
            current = ledger.effective_result(submit_here, status.attempt) if submit_here else None
            if current is not None and current.state == PhaseResult.NOT_EXECUTED:
                reason = "the previous submission was refused or never sent, so nothing ran"
                plan.append((step_id, status.attempt + 1, reason))
                continue
            plan.append((step_id, status.attempt, None))
        return plan

    def _execute(
        self, stage: StageDefinition, plan: list[tuple[str, int | None, str | None]]
    ) -> int:
        self._say(
            f"r1-acceptance {HARNESS_VERSION}: run {self._store.run_id}, stage {stage.stage_id} "
            f"({stage.title})"
        )
        ledger = self.ledger()
        work = [
            phase
            for step_id, attempt, reason in plan
            if attempt is not None
            for phase in ledger.phases_of(step_id, stage.stage_id)
            if reason is not None or self._needs_run(phase, ledger.effective_result(phase, attempt))
        ]
        if not work:
            self._say("Nothing is left to do in this stage: every phase has a definitive result.")
            return self._stage_code(stage)
        if stage.claude_runs and any(phase.kind == PhaseDefinition.SUBMIT for phase in work):
            self._say(f"This stage can start up to {stage.claude_runs} real Claude run(s).")
        if stage.preflight != StageDefinition.NO_PREFLIGHT and any(
            phase.kind in self.CONTACTS_BRIDGE for phase in work
        ):
            passed, interrupted = self._preflight(stage)
            if interrupted:
                return self.EXIT_INTERRUPTED
            if not passed:
                return self.EXIT_REFUSED
        code = self.EXIT_OK
        for index, (step_id, attempt, reason) in enumerate(plan):
            if attempt is None:
                self._say(f"[{step_id}] {reason}")
                continue
            if reason is not None:
                self._store.append_event(
                    RunLedger.ATTEMPT_STARTED,
                    {"step": step_id, "attempt": attempt, "reason": reason},
                )
                self._say(f"[{step_id}] attempt {attempt}: {reason}")
            else:
                self._say(f"[{step_id}] attempt {attempt}")
            stop = self._run_step(stage, step_id, attempt)
            if stop is not None:
                return stop
            status = self.ledger().step_status(step_id)
            self._say(f"  => {step_id}: {status.verdict.value}" + self._pending_note(status.manual))
            if status.automated is Verdict.FAILED:
                code = self.EXIT_FAILURES
                if stage.stop_on_failure and index < len(plan) - 1:
                    self._say(
                        f"Stopping the stage after the failure of {step_id}, so that no further "
                        "Claude run is spent. Look at the diagnostics; running the stage again "
                        "continues with the next step."
                    )
                    return code
        return code

    def _run_step(self, stage: StageDefinition, step_id: str, attempt: int) -> int | None:
        """Run the step's phases of this stage; return an exit code if the stage must stop."""
        for phase in R1Procedure.PHASES:
            if phase.step_id != step_id or phase.stage_id != stage.stage_id:
                continue
            ledger = self.ledger()
            current = ledger.effective_result(phase, attempt)
            if not self._needs_run(phase, current):
                state = current.state if current is not None else "done"
                self._say(f"  {phase.phase_id}: {state} before, not repeated")
                continue
            result, outcome = self._run_phase(phase, attempt, ledger)
            self._show(phase, result)
            if outcome == Execution.INTERRUPTED:
                self._say(
                    f"Interrupted. Run '{stage.command()}' again to resume; nothing that was "
                    "already submitted is submitted again."
                )
                return self.EXIT_INTERRUPTED
            if result.state == PhaseResult.AWAITING:
                self._say(
                    f"  {step_id} has not settled. Run '{stage.command()}' again to continue "
                    "waiting; the task is not submitted again."
                )
                return self.EXIT_INCOMPLETE
            if result.state == PhaseResult.UNKNOWN:
                self._say("\n".join(decision_lines(self.ledger(), stage, self._settings)))
                return self.EXIT_INCOMPLETE
            if result.state == PhaseResult.INTERRUPTED:
                self._say(f"  {phase.phase_id} was cut short; run the stage again to repeat it.")
                return self.EXIT_INCOMPLETE
            if result.state == PhaseResult.NOT_EXECUTED:
                self._say(
                    f"  Nothing ran for {step_id}. After fixing the cause, run "
                    f"'{stage.command()}' again to submit it anew."
                )
                return self.EXIT_FAILURES
        return None

    @staticmethod
    def _needs_run(phase: PhaseDefinition, current: PhaseResult | None) -> bool:
        if current is None:
            return True
        if phase.kind == PhaseDefinition.SUBMIT:
            return False
        if phase.rerun == PhaseDefinition.ON_FAILURE:
            return current.state != PhaseResult.PASSED
        if phase.rerun == PhaseDefinition.UNTIL_SETTLED:
            return not current.settled
        if phase.rerun == PhaseDefinition.IF_UNOBSERVED:
            return current.state == PhaseResult.INTERRUPTED
        return False

    def _run_phase(
        self, phase: PhaseDefinition, attempt: int, ledger: RunLedger
    ) -> tuple[PhaseResult, str | None]:
        now = format_time(utc_now())
        if phase.kind == PhaseDefinition.LOCAL_PACKAGE:
            return self._local_package(phase, attempt)
        if phase.kind == PhaseDefinition.FILE_ABSENT:
            values = placeholder_values(self._settings, None)
            path = Path(render(phase.local_path or "", values)).expanduser()
            result = evaluate_file_absent(phase, attempt, path, now)
            self._store.append_event(RunLedger.PHASE_EVALUATED, result.to_dict())
            return result, None
        if phase.kind == PhaseDefinition.UNSIGNED_POST:
            display = f"POST {self._settings.get('url')}/v1/tasks with body {{}}, no credentials"
            command_id = self._start(phase.step_id, attempt, phase.phase_id, display, "none")
            execution = self._probe.post_without_credentials()
        else:
            task_id = ledger.task_id(phase.step_id, attempt)
            arguments = phase.cli_arguments(task_id)
            wrong_key = self._wrong_key() if phase.kind == PhaseDefinition.WRONG_KEY_PING else None
            display = display_command(arguments)
            key = "a random wrong key" if wrong_key else KEY_VARIABLE
            command_id = self._start(phase.step_id, attempt, phase.phase_id, display, key)
            execution = self._cli.run(
                arguments, budget_seconds=phase.max_wait or 0.0, wrong_key=wrong_key
            )
        record = self._finish(
            command_id, phase.step_id, attempt, phase.phase_id, display, execution
        )
        result = self._evaluate(phase, attempt, record, self.ledger())
        self._store.append_event(RunLedger.PHASE_EVALUATED, result.to_dict())
        return result, execution.outcome

    def _evaluate(
        self, phase: PhaseDefinition, attempt: int, record: CommandRecord, ledger: RunLedger
    ) -> PhaseResult:
        now = format_time(utc_now())
        if phase.kind in (PhaseDefinition.PING, PhaseDefinition.WRONG_KEY_PING):
            return evaluate_ping(phase, attempt, record, now)
        if phase.kind == PhaseDefinition.UNSIGNED_POST:
            return evaluate_unsigned_post(phase, attempt, record, self._error_text(record), now)
        if phase.kind == PhaseDefinition.SUBMIT:
            return evaluate_submit(phase, attempt, record, self._error_text(record), now)
        reference = (
            ledger.phase_finished_at(phase.step_id, attempt, phase.expect_restart_after)
            if phase.expect_restart_after
            else None
        )
        return evaluate_wait(
            phase,
            attempt,
            record,
            task_id=ledger.task_id(phase.step_id, attempt),
            restart_reference=reference,
            evaluated_at=now,
        )

    def _local_package(self, phase: PhaseDefinition, attempt: int) -> tuple[PhaseResult, str]:
        source = self._orbital_src / "orbital" / "bridges" / "__init__.py"
        api_problem: str | None = None
        module_file: str | None = None
        try:
            module = import_bridges(self._orbital_src)
            module_file = str(Path(str(module.__file__)).resolve())
            missing = [name for name in PUBLIC_API if not hasattr(module, name)]
            if missing:
                api_problem = f"missing from orbital.bridges: {', '.join(missing)}"
            elif not Path(module_file).is_relative_to(self._orbital_src.resolve()):
                api_problem = f"imported from {module_file}, not from {self._orbital_src}"
        except Exception as exc:  # any import failure is the observation
            api_problem = f"{type(exc).__name__}: {exc}"
        display = display_command(("--help",))
        command_id = self._start(phase.step_id, attempt, phase.phase_id, display, "none")
        execution = self._cli.run(("--help",), budget_seconds=30.0, expect_json=False)
        record = self._finish(
            command_id, phase.step_id, attempt, phase.phase_id, display, execution
        )
        result = evaluate_local_package(
            phase,
            attempt,
            record,
            source=source,
            api_problem=api_problem,
            module_file=module_file,
            help_text=execution.stdout.decode("utf-8", "replace"),
            evaluated_at=format_time(utc_now()),
        )
        self._store.append_event(RunLedger.PHASE_EVALUATED, result.to_dict())
        return result, execution.outcome

    def _preflight(self, stage: StageDefinition) -> tuple[bool, bool]:
        """Check the server state the stage needs; return (passed, interrupted)."""
        phase_id = f"preflight-{stage.stage_id}"
        display = display_command(("ping",))
        command_id = self._start("preflight", 0, phase_id, display, KEY_VARIABLE)
        execution = self._cli.run(("ping",), budget_seconds=60.0)
        record = self._finish(command_id, "preflight", 0, phase_id, display, execution)
        if execution.outcome == Execution.INTERRUPTED:
            self._say("Interrupted during the preflight ping; nothing was submitted.")
            return False, True
        document = record.document or {}
        ok = document.get("ok") is True
        code, message = error_fields(document)
        if stage.preflight == StageDefinition.REACHABLE:
            passed = ok
            expectation = "the bridge answers a signed ping"
        else:
            passed = execution.outcome == Execution.EXITED and not ok and code in UNREACHABLE_CODES
            expectation = "the bridge does not answer: " + ", ".join(sorted(UNREACHABLE_CODES))
        observed = (
            "ok" if ok else f"{code or record.parse_error or record.outcome}: {excerpt(message)}"
        )
        self._store.append_event(
            RunLedger.PREFLIGHT,
            {
                "stage": stage.stage_id,
                "expectation": expectation,
                "passed": passed,
                "observed": observed,
                "command_id": command_id,
            },
        )
        self._say(
            f"[preflight] {display}: {observed} ({'as expected' if passed else 'NOT as expected'})"
        )
        if passed:
            return True, False
        if stage.preflight == StageDefinition.REACHABLE:
            self._say(
                "Nothing was submitted: the bridge must answer a signed ping first. Check that "
                "the Claude-side server is running, that both sides use the same "
                "ORBITAL_BRIDGE_KEY, and that the network policy allows the bridge; then run the "
                "stage again."
            )
        else:
            self._say(
                "The bridge still answers (or the failure is not a lost connection), so this "
                "stage would not observe an interrupted connection. Stop the Claude-side server "
                "(Ctrl-C) and run the stage again."
            )
        return False, False

    def _start(self, step_id: str, attempt: int, phase_id: str, display: str, key: str) -> int:
        return self._store.append_event(
            RunLedger.COMMAND_STARTED,
            {
                "step": step_id,
                "attempt": attempt,
                "phase": phase_id,
                "display": display,
                "key": key,
            },
        )

    def _finish(
        self,
        command_id: int,
        step_id: str,
        attempt: int,
        phase_id: str,
        display: str,
        execution: Execution,
    ) -> CommandRecord:
        stem = f"{command_id:06d}-{phase_id}"
        record = CommandRecord(
            command_id=command_id,
            step_id=step_id,
            attempt=attempt,
            phase_id=phase_id,
            display=display,
            started_at=execution.started_at,
            finished_at=execution.finished_at,
            duration_seconds=execution.duration_seconds,
            outcome=execution.outcome,
            exit_code=execution.exit_code,
            stdout_file=self._store.write_artifact(f"{stem}.stdout", execution.stdout),
            stderr_file=self._store.write_artifact(f"{stem}.stderr", execution.stderr),
            stdout_sha256=sha256_bytes(execution.stdout),
            document=execution.document,
            parse_error=execution.parse_error,
        )
        self._store.append_event(RunLedger.COMMAND_FINISHED, record.to_dict())
        return record

    def _error_text(self, record: CommandRecord) -> str:
        if record.stderr_file is None:
            return ""
        return self._store.read_artifact(record.stderr_file).decode("utf-8", "replace")

    def _wrong_key(self) -> str:
        real = os.environ.get(KEY_VARIABLE, "")
        while True:
            candidate = secrets.token_urlsafe(32)
            if candidate != real:
                return candidate

    def _stage_code(self, stage: StageDefinition) -> int:
        ledger = self.ledger()
        failed = any(ledger.step_status(s).automated is Verdict.FAILED for s in stage.steps)
        return self.EXIT_FAILURES if failed else self.EXIT_OK

    def _show(self, phase: PhaseDefinition, result: PhaseResult) -> None:
        parts = [f"status {result.observed_status}"] if result.observed_status else []
        if result.observed_code:
            parts.append(f"code {result.observed_code}")
        if result.observed_exit is not None:
            parts.append(f"exit {result.observed_exit}")
        if result.task_id and phase.kind == PhaseDefinition.SUBMIT:
            parts.append(f"task {result.task_id}")
        if result.response is not None:
            parts.append(f"response {excerpt(result.response, 80)!r}")
        self._say(
            f"  {phase.phase_id} ({phase.title}): {', '.join(parts) or '-'} -> {result.state}"
        )
        for check in result.checks:
            if check.verdict is not Verdict.PASSED:
                self._say(
                    f"      FAILED {check.description}: expected {check.expected}, observed "
                    f"{check.observed}" + (f" ({check.diagnostic})" if check.diagnostic else "")
                )
        for diagnostic in result.diagnostics:
            self._say(f"      note: {diagnostic}")

    @staticmethod
    def _pending_note(manual: Sequence[Any]) -> str:
        pending = [check.check_id for check in manual if check.verdict is Verdict.PENDING]
        return f" (manual checks to record: {', '.join(pending)})" if pending else ""

    def _say(self, text: str) -> None:
        print(text, file=self._out, flush=True)
