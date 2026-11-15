"""Static helpers of the procedure: evaluation of observations and the operator's instructions."""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from r1_acceptance.evidence.run_ledger import RunLedger
from r1_acceptance.models.check_result import CheckResult
from r1_acceptance.models.command_record import CommandRecord
from r1_acceptance.models.execution import Execution
from r1_acceptance.models.manual_check import ManualCheck
from r1_acceptance.models.phase_definition import PhaseDefinition
from r1_acceptance.models.phase_result import PhaseResult
from r1_acceptance.models.stage_definition import StageDefinition
from r1_acceptance.models.verdict import Verdict
from r1_acceptance.procedure.r1_procedure import R1Procedure
from r1_acceptance.utils import MINIMUM_PYTHON, parse_time

EXIT_STATUSES = {
    0: "ok",
    1: "failed",
    2: "usage-error",
    3: "timed_out",
    4: "communication_error",
    5: "rejected",
    6: "running",
}
UNREACHABLE_CODES = frozenset(
    {"gateway_error", "connection_failed", "connection_interrupted", "request_timeout"}
)
TASK_ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
START_TIME_PATTERN = re.compile(r"started at ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}(?:\.[0-9]+)?Z)")
PLACEHOLDER_PATTERN = re.compile(r"\{([a-z_]+)\}")
RESTART_TOLERANCE_SECONDS = 60.0
EXCERPT_CHARS = 300


def render(template: str, values: Mapping[str, str]) -> str:
    """*template* with its ``{name}`` placeholders replaced; unknown placeholders are kept."""
    return PLACEHOLDER_PATTERN.sub(
        lambda match: values.get(match.group(1), match.group(0)), template
    )


def placeholder_values(settings: Mapping[str, Any], task_id: str | None) -> dict[str, str]:
    """The values of the instruction placeholders for a run (and a task)."""
    return {
        "serve_log": str(settings.get("serve_log", "~/orbital-acceptance/serve.log")),
        "claude_workdir": str(settings.get("claude_workdir", "~/orbital-acceptance/workdir")),
        "task_id": task_id or "<task id>",
    }


def excerpt(text: str | None, limit: int = EXCERPT_CHARS) -> str:
    """At most *limit* characters of *text*, whitespace collapsed (``none`` for ``None``)."""
    if text is None:
        return "none"
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit] + " ..."


def show(value: object) -> str:
    """A value as text in a check (``none`` for ``None``)."""
    return "none" if value is None else str(value)


def automated(
    check_id: str,
    description: str,
    passed: bool,
    expected: str,
    observed: str,
    diagnostic: str = "",
) -> CheckResult:
    """An automated check result."""
    return CheckResult(
        check_id=check_id,
        description=description,
        source=CheckResult.AUTOMATED,
        verdict=Verdict.PASSED if passed else Verdict.FAILED,
        expected=expected,
        observed=observed,
        diagnostic=diagnostic,
    )


def error_fields(document: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """The ``error.code`` and ``error.message`` of a printed result (``None`` if absent)."""
    error = document.get("error")
    if not isinstance(error, Mapping):
        return None, None
    code, message = error.get("code"), error.get("message")
    return (
        code if isinstance(code, str) else None,
        message if isinstance(message, str) else None,
    )


def text_field(document: Mapping[str, Any], key: str) -> str | None:
    """A string field of a printed result, or ``None``."""
    value = document.get(key)
    return value if isinstance(value, str) else None


def status_check(phase: PhaseDefinition, status: str | None) -> CheckResult:
    """The observed status against the phase's expected status."""
    return automated(
        f"{phase.phase_id}.status",
        "status",
        status == phase.expect_status,
        show(phase.expect_status),
        show(status),
    )


def code_check(phase: PhaseDefinition, code: str | None) -> CheckResult:
    """The observed error code against the accepted codes (or none)."""
    passed = code in phase.expect_codes if phase.expect_codes else code is None
    return automated(
        f"{phase.phase_id}.error-code", "error code", passed, phase.expected_code_text(), show(code)
    )


def exit_check(phase: PhaseDefinition, exit_code: int | None) -> CheckResult:
    """The observed exit code against the expected one."""
    return automated(
        f"{phase.phase_id}.exit-code",
        "exit code",
        exit_code == phase.expect_exit,
        show(phase.expect_exit),
        show(exit_code),
    )


def task_check(phase: PhaseDefinition, observed: str | None, expected: str | None) -> CheckResult:
    """The result names the task that was submitted."""
    return automated(
        f"{phase.phase_id}.task-id",
        "the result carries the submitted task id",
        observed is not None and observed == expected,
        show(expected),
        show(observed),
    )


def response_checks(phase: PhaseDefinition, response: str | None) -> list[CheckResult]:
    """The response contains the expected word, if the phase expects one."""
    if phase.expect_response is None:
        return []
    text = response or ""
    contained = phase.expect_response in text
    note = ""
    if contained and text.strip() != phase.expect_response:
        note = "the response contains the expected word but is not exactly it"
    return [
        automated(
            f"{phase.phase_id}.response",
            "response",
            contained,
            phase.expect_response,
            repr(text) if response is not None else "none",
            note,
        )
    ]


def fragment_checks(phase: PhaseDefinition, message: str | None) -> list[CheckResult]:
    """The error message mentions each expected fragment (ignoring case)."""
    return [
        automated(
            f"{phase.phase_id}.message",
            f"the message mentions {fragment!r}",
            message is not None and fragment.lower() in message.lower(),
            f"mentions {fragment!r}",
            excerpt(message),
        )
        for fragment in phase.expect_fragments
    ]


def restart_checks(
    phase: PhaseDefinition, message: str | None, reference: str | None
) -> list[CheckResult]:
    """The message names a server start time later than the reference submission."""
    if phase.expect_restart_after is None:
        return []
    match = START_TIME_PATTERN.search(message or "")
    expected = f"a server start time after {phase.expect_restart_after} ({show(reference)})"
    if match is None:
        return [
            automated(
                f"{phase.phase_id}.new-start-time",
                "the message names the new server start time",
                False,
                expected,
                "no start time in the message",
            )
        ]
    started = match.group(1)
    passed = False
    diagnostic = ""
    if reference is None:
        diagnostic = f"no recorded time for {phase.expect_restart_after} to compare with"
    else:
        lag = (parse_time(started) - parse_time(reference)).total_seconds()
        passed = lag >= -RESTART_TOLERANCE_SECONDS
        if not passed:
            diagnostic = (
                f"the server started {-lag:.0f} s before {phase.expect_restart_after} was "
                "submitted; was it restarted after the stop, and are the clocks in step?"
            )
    return [
        automated(
            f"{phase.phase_id}.new-start-time",
            "the message names the new server start time",
            passed,
            expected,
            started,
            diagnostic,
        )
    ]


def phase_result(
    phase: PhaseDefinition,
    attempt: int,
    record: CommandRecord | None,
    evaluated_at: str,
    *,
    state: str,
    checks: Sequence[CheckResult] = (),
    task_id: str | None = None,
    status: str | None = None,
    code: str | None = None,
    response: str | None = None,
    message: str | None = None,
    diagnostics: Sequence[str] = (),
) -> PhaseResult:
    """Assemble a phase result."""
    return PhaseResult(
        phase_id=phase.phase_id,
        step_id=phase.step_id,
        attempt=attempt,
        state=state,
        task_id=task_id,
        observed_status=status,
        observed_code=code,
        observed_exit=record.exit_code if record is not None else None,
        response=response,
        message=message,
        checks=tuple(checks),
        command_ids=(record.command_id,) if record is not None else (),
        evaluated_at=evaluated_at,
        diagnostics=tuple(diagnostics),
    )


def judged(checks: Sequence[CheckResult]) -> str:
    """``passed`` if every check passed, otherwise ``failed``."""
    passed = all(check.verdict is Verdict.PASSED for check in checks)
    return PhaseResult.PASSED if passed else PhaseResult.FAILED


def unreadable(phase: PhaseDefinition, record: CommandRecord) -> CheckResult:
    """The check that fails when the CLI printed no readable JSON object."""
    return automated(
        f"{phase.phase_id}.output",
        "orbital-bridge printed one JSON object",
        False,
        "one JSON object on stdout",
        record.parse_error or "nothing",
    )


def evaluate_ping(
    phase: PhaseDefinition, attempt: int, record: CommandRecord, evaluated_at: str
) -> PhaseResult:
    """Judge an ``orbital-bridge ping``."""
    if record.outcome != Execution.EXITED:
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            state=PhaseResult.INTERRUPTED,
            diagnostics=(f"the command did not finish ({record.outcome})",),
        )
    document = record.document
    if document is None:
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            state=PhaseResult.FAILED,
            checks=(unreadable(phase, record),),
        )
    ok = document.get("ok") is True
    code, message = error_fields(document)
    expected_ok = phase.expect_status == "ok"
    checks = [
        automated(
            f"{phase.phase_id}.ok",
            "ok",
            ok is expected_ok,
            str(expected_ok).lower(),
            str(ok).lower(),
        ),
        code_check(phase, code),
        exit_check(phase, record.exit_code),
        *fragment_checks(phase, message),
    ]
    status = "ok" if ok else EXIT_STATUSES.get(record.exit_code or 0, show(record.exit_code))
    return phase_result(
        phase,
        attempt,
        record,
        evaluated_at,
        state=judged(checks),
        checks=checks,
        status=status,
        code=code,
        message=message,
    )


def evaluate_unsigned_post(
    phase: PhaseDefinition,
    attempt: int,
    record: CommandRecord,
    error_text: str,
    evaluated_at: str,
) -> PhaseResult:
    """Judge the unauthenticated ``POST /v1/tasks``."""
    document = record.document
    if record.outcome != Execution.HTTP_RESPONSE or document is None:
        check = automated(
            f"{phase.phase_id}.http-status",
            "HTTP status",
            False,
            show(phase.expect_status),
            "no HTTP response",
            excerpt(error_text),
        )
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            state=PhaseResult.FAILED,
            checks=(check,),
            diagnostics=(f"no HTTP response: {excerpt(error_text)}",),
        )
    status = f"HTTP {document.get('http_status')}"
    checks = [
        automated(
            f"{phase.phase_id}.http-status",
            "HTTP status",
            status == phase.expect_status,
            show(phase.expect_status),
            status,
        )
    ]
    if phase.expect_header is not None:
        name, value = phase.expect_header
        headers = document.get("headers") or []
        values = [str(item[1]) for item in headers if str(item[0]).lower() == name.lower()]
        checks.append(
            automated(
                f"{phase.phase_id}.www-authenticate",
                f"{name} header",
                value in values,
                value,
                ", ".join(values) or "absent",
            )
        )
    code = document.get("error_code")
    return phase_result(
        phase,
        attempt,
        record,
        evaluated_at,
        state=judged(checks),
        checks=checks,
        status=status,
        code=code if isinstance(code, str) else None,
        message=excerpt(str(document.get("body", ""))),
    )


def evaluate_submit(
    phase: PhaseDefinition,
    attempt: int,
    record: CommandRecord,
    error_text: str,
    evaluated_at: str,
) -> PhaseResult:
    """Judge an ``orbital-bridge submit --max-wait 0``."""
    if record.outcome == Execution.START_FAILED:
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            state=PhaseResult.NOT_EXECUTED,
            diagnostics=(
                f"orbital-bridge could not be started, so nothing was sent: {excerpt(error_text)}",
            ),
        )
    if record.outcome != Execution.EXITED:
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            state=PhaseResult.UNKNOWN,
            diagnostics=(
                f"the submission did not finish ({record.outcome}); the task may or "
                "may not have been accepted",
            ),
        )
    if record.exit_code == 2:
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            state=PhaseResult.NOT_EXECUTED,
            diagnostics=(
                f"usage or configuration error, so no request was sent: {excerpt(error_text)}",
            ),
        )
    document = record.document
    if document is None:
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            state=PhaseResult.UNKNOWN,
            checks=(unreadable(phase, record),),
            diagnostics=(
                "the output could not be read; the task may or may not have been accepted",
            ),
        )
    task_id = text_field(document, "task_id")
    valid = task_id is not None and TASK_ID_PATTERN.fullmatch(task_id) is not None
    status = text_field(document, "status")
    code, message = error_fields(document)
    checks = [
        automated(
            f"{phase.phase_id}.task-id",
            "a task id (UUID version 4) was assigned",
            valid,
            "a UUID version 4",
            show(task_id),
        ),
        status_check(phase, status),
        code_check(phase, code),
        exit_check(phase, record.exit_code),
    ]
    if status == "rejected":
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            state=PhaseResult.NOT_EXECUTED,
            checks=checks,
            task_id=task_id if valid else None,
            status=status,
            code=code,
            message=message,
            diagnostics=(f"the server refused the submission ({code}), so nothing ran",),
        )
    if not valid:
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            state=PhaseResult.UNKNOWN,
            checks=checks,
            status=status,
            code=code,
            message=message,
            diagnostics=("no task id was printed; the task may or may not have been accepted",),
        )
    diagnostics: list[str] = []
    if status == "communication_error":
        diagnostics.append(
            "the submission was not confirmed; the task id is polled next, in case the task "
            "was accepted"
        )
    return phase_result(
        phase,
        attempt,
        record,
        evaluated_at,
        state=judged(checks),
        checks=checks,
        task_id=task_id,
        status=status,
        code=code,
        message=message,
        diagnostics=diagnostics,
    )


def evaluate_wait(
    phase: PhaseDefinition,
    attempt: int,
    record: CommandRecord,
    *,
    task_id: str | None,
    restart_reference: str | None,
    evaluated_at: str,
) -> PhaseResult:
    """Judge an ``orbital-bridge wait``.

    A wait that must settle the task stays ``awaiting`` while the task is running or its state
    is unknown because of a communication error (other than ``unknown_task``).
    """
    settle = phase.kind == PhaseDefinition.WAIT_SETTLE
    if record.outcome != Execution.EXITED:
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            task_id=task_id,
            state=PhaseResult.AWAITING if settle else PhaseResult.INTERRUPTED,
            diagnostics=(f"the command did not finish ({record.outcome})",),
        )
    document = record.document
    if document is None:
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            task_id=task_id,
            state=PhaseResult.AWAITING if settle else PhaseResult.FAILED,
            checks=(unreadable(phase, record),),
        )
    status = text_field(document, "status")
    code, message = error_fields(document)
    response = text_field(document, "response")
    observed_task = text_field(document, "task_id")
    if settle and (
        status == "running" or (status == "communication_error" and code != "unknown_task")
    ):
        reason = (
            "the task has not settled yet"
            if status == "running"
            else f"communication error ({code}): the task's state is not known yet"
        )
        return phase_result(
            phase,
            attempt,
            record,
            evaluated_at,
            state=PhaseResult.AWAITING,
            task_id=task_id,
            status=status,
            code=code,
            response=response,
            message=message,
            diagnostics=(reason,),
        )
    checks = [
        task_check(phase, observed_task, task_id),
        status_check(phase, status),
        code_check(phase, code),
        exit_check(phase, record.exit_code),
        *response_checks(phase, response),
        *fragment_checks(phase, message),
        *restart_checks(phase, message, restart_reference),
    ]
    diagnostics: list[str] = []
    if code == "unknown_task" and phase.expect_codes != ("unknown_task",):
        diagnostics.append("the server has no record of the task: was it restarted?")
    return phase_result(
        phase,
        attempt,
        record,
        evaluated_at,
        state=judged(checks),
        checks=checks,
        task_id=task_id,
        status=status,
        code=code,
        response=response,
        message=message,
        diagnostics=diagnostics,
    )


def evaluate_file_absent(
    phase: PhaseDefinition, attempt: int, path: Path, evaluated_at: str
) -> PhaseResult:
    """Judge that a file made by Claude in the Claude sandbox is not visible here."""
    exists = path.exists() or path.is_symlink()
    observed = "absent"
    if exists:
        observed = f"exists ({path.stat().st_size} bytes)" if path.is_file() else "exists"
    check = automated(
        f"{phase.phase_id}.absent",
        "the file Claude created is not visible in the ChatGPT sandbox",
        not exists,
        f"no file at {path}",
        observed,
        "the two sandboxes appear to share a filesystem" if exists else "",
    )
    return phase_result(
        phase,
        attempt,
        None,
        evaluated_at,
        state=judged([check]),
        checks=(check,),
        status="absent" if not exists else "present",
    )


def evaluate_local_package(
    phase: PhaseDefinition,
    attempt: int,
    record: CommandRecord,
    *,
    source: Path,
    api_problem: str | None,
    module_file: str | None,
    help_text: str,
    evaluated_at: str,
) -> PhaseResult:
    """Judge the local preflight P-1."""
    version = ".".join(str(part) for part in sys.version_info[:3])
    missing = [name for name in ("serve", "submit", "wait", "ping") if name not in help_text]
    checks = [
        automated(
            f"{phase.phase_id}.python",
            "Python runs the harness",
            sys.version_info >= MINIMUM_PYTHON,
            ">= " + ".".join(str(part) for part in MINIMUM_PYTHON),
            version,
        ),
        automated(
            f"{phase.phase_id}.source",
            "the orbital source under test is present",
            source.is_file(),
            str(source),
            "present" if source.is_file() else "missing",
        ),
        automated(
            f"{phase.phase_id}.public-api",
            "the public API imports from orbital.bridges",
            api_problem is None,
            "BridgeClient, BridgeServer, ... (11 names) from the source above",
            show(module_file) if api_problem is None else api_problem,
        ),
        automated(
            f"{phase.phase_id}.cli",
            "python -m orbital.bridges --help lists the commands",
            record.outcome == Execution.EXITED and record.exit_code == 0 and not missing,
            "exit 0; serve, submit, wait and ping",
            f"exit {show(record.exit_code)}"
            + (f"; missing {', '.join(missing)}" if missing else ""),
        ),
    ]
    state = judged(checks)
    return phase_result(
        phase,
        attempt,
        record,
        evaluated_at,
        state=state,
        checks=checks,
        status=state,
    )


def manual_check_lines(check: ManualCheck, values: Mapping[str, str]) -> list[str]:
    """How to make and record a manual check."""
    return [
        f"[{check.check_id}] {check.title} ({check.where}, {check.when}):",
        f"    {render(check.command, values)}",
        f"  Expect: {render(check.expectation, values)}",
        f"  Record: r1-acceptance record {check.check_id} pass|fail --observed '<what it printed>'",
    ]


def pending_manual_checks(
    ledger: RunLedger, steps: Sequence[str] | None = None
) -> list[tuple[ManualCheck, str | None]]:
    """Manual checks not yet recorded for the latest attempt of steps that ran (with task ids)."""
    pending: list[tuple[ManualCheck, str | None]] = []
    for check in R1Procedure.MANUAL_CHECKS:
        if steps is not None and check.step_id not in steps:
            continue
        attempt = ledger.latest_attempt(check.step_id)
        if attempt == 0 or ledger.skip_reason(check.step_id) is not None:
            continue
        if ledger.manual_record(check.check_id, attempt) is None:
            pending.append((check, ledger.task_id(check.step_id, attempt)))
    return pending


def decision_lines(
    ledger: RunLedger, stage: StageDefinition, settings: Mapping[str, Any]
) -> list[str]:
    """What to do about a step whose submission ended with an unknown outcome."""
    for step_id in stage.steps:
        if ledger.step_status(step_id).automated is not Verdict.NEEDS_DECISION:
            continue
        values = placeholder_values(settings, None)
        return [
            f"{step_id} needs your decision: the harness stopped while submitting its task, so "
            "the task may or may not have been accepted.",
            "Look at the Claude side first:",
            f"    grep 'accepted' {values['serve_log']} | tail -n 3",
            "Then either submit it again (this starts another real Claude run):",
            f"    {stage.command()} --resubmit {step_id}",
            "or skip the step:",
            f'    r1-acceptance record {step_id} skip --note "<why>"',
        ]
    return []


def rerun_hint_lines(ledger: RunLedger) -> list[str]:
    """How to repeat steps that failed in stages that already ran."""
    lines: list[str] = []
    for step in R1Procedure.STEPS:
        status = ledger.step_status(step.step_id)
        if status.automated is not Verdict.FAILED:
            continue
        stage_ids = R1Procedure.stages_of(step.step_id)
        if step.claude_runs:
            stage = R1Procedure.stage(stage_ids[0])
            lines.append(
                f"{step.step_id} failed. To try it again with a new task (another real Claude "
                f"run): {stage.command()} --resubmit {step.step_id}"
            )
        else:
            lines.append(
                f"{step.step_id} failed. After fixing the cause, r1-acceptance run "
                f"{stage_ids[0]} repeats only its failed checks."
            )
    return lines


def next_action_lines(ledger: RunLedger, settings: Mapping[str, Any]) -> list[str]:
    """What the operator does next, as exact instructions."""
    values = placeholder_values(settings, None)
    if ledger.step_status("P-1").automated is not Verdict.PASSED:
        return [
            "Next: the local preflight P-1 must pass first. Fix what it reports, then run:",
            "    r1-acceptance run p1",
        ]
    for stage in R1Procedure.STAGES:
        if ledger.stage_complete(stage.stage_id):
            continue
        decision = decision_lines(ledger, stage, settings)
        if decision:
            return decision
        unsettled = [
            step_id
            for step_id in stage.steps
            if ledger.step_status(step_id).automated is Verdict.IN_PROGRESS
        ]
        if unsettled and ledger.stage_started_at(stage.stage_id) is not None:
            return [
                f"{', '.join(unsettled)} has not settled yet. Continue the stage (nothing is "
                "submitted again):",
                f"    {stage.command()}",
            ]
        lines = [f"Next: stage {stage.stage_id} ({stage.title})."]
        if stage.before:
            lines.append("Before it:")
            lines += [f"  {render(line, values)}" for line in stage.before]
        lines += ["Then, in this sandbox:", f"    {stage.command()}"]
        return lines
    pending = pending_manual_checks(ledger)
    if not pending:
        return [
            "Every stage has run and every manual check is recorded. Build the report:",
            "    r1-acceptance report",
        ]
    lines = ["Every stage has run. Record the manual checks that are still pending:"]
    for check, task_id in pending:
        lines += manual_check_lines(check, placeholder_values(settings, task_id))
    return [*lines, "Then build the report:", "    r1-acceptance report"]
