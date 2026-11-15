"""Static helpers of the stage runner: prerequisites and the operator's next step."""

from __future__ import annotations

from typing import Any

from r1_retest.evidence.ledger import Ledger
from r1_retest.procedure.retest_procedure import RetestProcedure

REQUIRED_ORDER = ("a3", "a2", "a1-submit", "a1-down", "a1-up")
OPTIONAL_ORDER = ("a4-submit", "a4-down", "a4-up")


def submit_op(test_id: str) -> str:
    return RetestProcedure.stages_of(test_id)[0].operation


def task_known(ledger: Ledger, test_id: str) -> str | None:
    attempt = ledger.attempt(test_id)
    return ledger.task_id(test_id, attempt, submit_op(test_id)) if attempt else None


def in_progress(ledger: Ledger, test_id: str) -> bool:
    """A multi-stage test whose task was submitted but whose last stage has not run."""
    attempt = ledger.attempt(test_id)
    if attempt == 0:
        return False
    stages = RetestProcedure.stages_of(test_id)
    submitted = ledger.op_state(test_id, attempt, stages[0].operation) in (
        "evaluated",
        "lost",
        "in-flight",
    )
    finished = ledger.op_state(test_id, attempt, stages[-1].operation) == "evaluated"
    return submitted and not finished and len(stages) > 1


def prerequisite_problem(stage_id: str, ledger: Ledger) -> str | None:
    """Why *stage_id* may not run yet, or ``None``."""
    if stage_id == "a3":
        return None
    if not ledger.op_passed("A-3", ledger.attempt("A-3"), "D-2"):
        return "A-3 (stage a3, D-2) must pass first: the signed ping proves the path and the key"
    if stage_id == "a2":
        return None
    if stage_id == "a1-submit":
        state = (
            ledger.op_state("A-2", ledger.attempt("A-2"), "D-7")
            if ledger.attempt("A-2")
            else "not-run"
        )
        if state not in ("evaluated", "lost"):
            return "run A-2 (stage a2) first; the targeted re-test runs A-3, A-2, then A-1"
        if in_progress(ledger, "A-4"):
            return "the optional A-4 is in progress; finish it (a4-down, a4-up) first"
        return None
    if stage_id == "a4-submit":
        if in_progress(ledger, "A-1"):
            return "A-1 is in progress; finish it (a1-down, a1-up) first"
        return None
    test_id = RetestProcedure.stage(stage_id).test_id
    attempt = ledger.attempt(test_id)
    stages = RetestProcedure.stages_of(test_id)
    position = [s.stage_id for s in stages].index(stage_id)
    if attempt == 0:
        return f"run {stages[0].stage_id} first"
    if position == 1 and ledger.task_id(test_id, attempt, stages[0].operation) is None:
        return (
            f"{stages[0].operation} has no task id: its submission failed or was lost; "
            f"repeat the test (r1-retest repeat {test_id} --ready) "
            "or adopt the task id (r1-retest adopt)"
        )
    previous = stages[position - 1]
    if position == 2 and ledger.op_state(test_id, attempt, previous.operation) != "evaluated":
        return f"run {previous.stage_id} first"
    return None


def next_steps(ledger: Ledger, tests: list[dict[str, Any]]) -> list[str]:
    """What the operator does next, as display lines."""
    for stage_id in REQUIRED_ORDER:
        stage = RetestProcedure.stage(stage_id)
        operation = RetestProcedure.operation(stage.operation)
        attempt = ledger.attempt(stage.test_id)
        state = ledger.op_state(stage.test_id, attempt, stage.operation) if attempt else "not-run"
        task_id = task_known(ledger, stage.test_id)
        if state == "evaluated":
            result = ledger.op_result(stage.test_id, attempt, stage.operation) or {}
            if result.get("verdict") == "passed":
                continue
            if operation.starts_claude:
                if len(RetestProcedure.test(stage.test_id).stages) > 1:
                    return [
                        f"{stage.operation} failed: repeat {stage.test_id} with a new task "
                        f"(r1-retest repeat {stage.test_id} --ready), "
                        "after reviewing r1-retest status."
                    ]
                continue
            return [
                f"{stage.operation} failed; it has no side effects, so you may run it again once "
                f"the cause is fixed: {stage.command()}"
            ]
        if state == "in-flight":
            return [f"Collect the command started earlier: {stage.command()}"]
        if state == "lost":
            if operation.starts_claude and ledger.adopted(stage.test_id, attempt):
                continue
            return [
                f"{stage.operation}'s output was lost. Find the task id in serve.log and adopt it "
                f"(r1-retest adopt {stage.test_id} <task_id>), or repeat the test "
                f"(r1-retest repeat {stage.test_id} --ready)."
            ]
        lines = [RetestProcedure.render(line, task_id) for line in stage.before]
        lines.append(f"Then: {stage.command(ready=True)}")
        return lines
    pending = [m for t in tests if t["required"] for m in t["manual"] if m["verdict"] == "pending"]
    if pending:
        lines = ["Record the remaining Claude-side evidence:"]
        for text in dict.fromkeys(m["diagnostics"][0] for m in pending if m["diagnostics"]):
            lines.append(f"  - {text}")
        return lines
    return [
        "Generate the report: r1-retest report  (optional: the A-4 SIGHUP check, stage a4-submit)"
    ]
