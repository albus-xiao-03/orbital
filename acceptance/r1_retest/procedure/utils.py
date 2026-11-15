"""Static helpers that judge the result of an automated operation against plans/R1.md."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from r1_retest.bridge.utils import parse_json_output
from r1_retest.procedure.operation import Operation
from r1_retest.utils import TASK_ID, format_time, parse_time

EXIT_FOR_STATUS = {
    "succeeded": 0,
    "failed": 1,
    "timed_out": 3,
    "communication_error": 4,
    "rejected": 5,
    "running": 6,
}
UNREACHABLE_CODES = (
    "gateway_error",
    "connection_failed",
    "connection_interrupted",
    "request_timeout",
)
START_TIME = re.compile(r"started at (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)")
RESTART_TOLERANCE_SECONDS = 60


def error_fields(document: dict[str, Any]) -> tuple[str | None, str]:
    error = document.get("error")
    if isinstance(error, dict):
        return (
            str(error["code"]) if error.get("code") is not None else None,
            str(error.get("message") or ""),
        )
    return None, ""


def evaluate_operation(
    operation: Operation,
    execution: dict[str, Any],
    stdout: bytes,
    expected_task: str | None,
    submitted_at: datetime | None,
) -> dict[str, Any]:
    """Judge one operation; returns verdict, expected, observed, task id and diagnostics.

    ``expected_task`` is the attempt's task id (for ``wait``); ``submitted_at`` is when the
    attempt's task was submitted (for the restart check of D-9c).
    """
    diagnostics: list[str] = list(execution.get("notes") or [])
    expected: dict[str, Any] = {
        "text": operation.expected_text(),
        "status": operation.expect_status,
        "codes": list(operation.expect_codes),
        "exit": operation.expect_exit,
    }
    observed: dict[str, Any] = {"outcome": execution["outcome"], "exit": execution.get("exit_code")}
    result: dict[str, Any] = {
        "verdict": "failed",
        "expected": expected,
        "observed": observed,
        "task_id": None,
        "document": None,
        "diagnostics": diagnostics,
    }
    if execution["outcome"] != "exited":
        diagnostics.append(f"the command did not complete normally ({execution['outcome']})")
        return result
    document = parse_json_output(stdout)
    result["document"] = document
    if document is None:
        diagnostics.append("stdout holds no JSON object")
        return result
    failures: list[str] = []
    exit_code = execution.get("exit_code")
    if operation.expect_status is None:
        code, message = error_fields(document)
        observed.update(ok=document.get("ok"), code=code, message=message)
        if document.get("ok") is not True or document.get("error") is not None:
            failures.append(f"ping did not succeed: ok={document.get('ok')!r}, code={code}")
    else:
        status = document.get("status")
        code, message = error_fields(document)
        task = document.get("task_id")
        observed.update(
            status=status,
            code=code,
            message=message,
            task_id=task,
            response=document.get("response"),
        )
        result["task_id"] = task if isinstance(task, str) and TASK_ID.match(task) else None
        if status != operation.expect_status:
            failures.append(f"status {status!r}, expected {operation.expect_status!r}")
        if code not in operation.expect_codes:
            failures.append(f"error code {code!r}, expected {expected['codes']}")
        if result["task_id"] is None:
            failures.append(f"no valid task id in the result ({task!r})")
        if operation.uses_task and task != expected_task:
            failures.append(f"task id {task!r} differs from the attempt's task {expected_task!r}")
        if operation.checks_restart:
            match = START_TIME.search(message)
            if match is None:
                failures.append("the unknown_task message names no server start time")
            else:
                started = parse_time(match.group(1))
                observed["server_started_at"] = format_time(started)
                if submitted_at is not None and started < submitted_at - timedelta(
                    seconds=RESTART_TOLERANCE_SECONDS
                ):
                    failures.append(
                        f"the server start time {match.group(1)} is not after the task's "
                        f"submission ({format_time(submitted_at)}): no restart"
                    )
        if exit_code is None and isinstance(status, str):
            exit_code = EXIT_FOR_STATUS.get(status)
            diagnostics.append("exit code not observed; derived from the printed status")
            observed["exit_derived"] = exit_code
    if exit_code != operation.expect_exit:
        failures.append(f"exit code {exit_code}, expected {operation.expect_exit}")
    diagnostics.extend(failures)
    result["verdict"] = "failed" if failures else "passed"
    return result


def evaluate_preflight(
    expectation: str, execution: dict[str, Any], stdout: bytes
) -> dict[str, Any]:
    """A preflight ping: ``reachable`` needs ok; ``unreachable`` needs a connection-level error."""
    document = parse_json_output(stdout) if execution["outcome"] == "exited" else None
    if document is None:
        return {"passed": False, "observed": f"no ping result ({execution['outcome']})"}
    code, message = error_fields(document)
    if expectation == "reachable":
        passed = document.get("ok") is True
    else:
        passed = document.get("ok") is False and code in UNREACHABLE_CODES
    observed = "ok" if document.get("ok") is True else f"{code}: {message[:300]}"
    return {"passed": passed, "observed": observed, "code": code}
