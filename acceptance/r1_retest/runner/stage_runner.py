"""Runs one stage: its checks, its single operation, and the evidence it leaves."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, ClassVar

from r1_retest.bridge.bridge_command import BridgeCommand, Execution
from r1_retest.bridge.utils import key_present
from r1_retest.evidence.evidence_store import EvidenceStore
from r1_retest.evidence.ledger import Ledger
from r1_retest.procedure.operation import Operation
from r1_retest.procedure.retest_procedure import RetestProcedure
from r1_retest.procedure.stage import Stage
from r1_retest.procedure.utils import evaluate_operation, evaluate_preflight
from r1_retest.runner.utils import prerequisite_problem, submit_op
from r1_retest.utils import TASK_ID, parse_time, tree_digest


class StageRunner:
    """Executes stages, and the operator's ``repeat`` and ``adopt`` decisions.

    A submission (a real Claude run) never happens twice by itself: once a submission has
    started, running its stage again only collects or reports it. A new task needs
    ``repeat <test> --ready``. Operations without side effects (ping, wait) may run again.
    """

    OK: ClassVar[int] = 0
    FAILURES: ClassVar[int] = 1
    REFUSED: ClassVar[int] = 2
    INCOMPLETE: ClassVar[int] = 3
    INTERRUPTED: ClassVar[int] = 130

    def __init__(
        self, store: EvidenceStore, environ: Mapping[str, str], say: Callable[[str], None]
    ) -> None:
        self._store = store
        self._environ = environ
        self._say = say
        info = store.info()
        self._src = Path(info["orbital"]["src"])
        self._bridge = BridgeCommand(store, self._src, info["url"], environ, say)

    # ---------------------------------------------------------------------------------- run

    def run(self, stage_id: str, ready: bool, invocation: list[str]) -> int:
        stage = RetestProcedure.stage(stage_id)
        operation = RetestProcedure.operation(stage.operation)
        ledger = Ledger(self._store.events())
        problem = self._refusal(stage, ledger)
        if problem is not None:
            self._say(f"Refused: {problem}. Nothing was sent.")
            return self.REFUSED
        test_id = stage.test_id
        attempt = ledger.attempt(test_id)
        state = ledger.op_state(test_id, attempt, operation.op_id) if attempt else "not-run"
        if state == "in-flight":
            return self._collect(stage, operation, ledger, attempt)
        if state == "evaluated":
            result = ledger.op_result(test_id, attempt, operation.op_id) or {}
            if result.get("verdict") == "passed":
                self._say(
                    f"{operation.op_id} already passed in attempt {attempt}; nothing was sent. "
                    "See 'r1-retest status' for the next step."
                )
                return self.OK
            if operation.starts_claude:
                self._say(
                    f"{operation.op_id} already ran in attempt {attempt} (verdict "
                    f"{result.get('verdict')}); it is never resubmitted by itself. For a new task: "
                    f"r1-retest repeat {test_id} --ready"
                )
                return self.FAILURES
        if state == "lost" and operation.starts_claude:
            adopted = ledger.adopted(test_id, attempt)
            if adopted:
                self._say(
                    f"{operation.op_id}'s output was lost; the operator adopted task "
                    f"{adopted['task_id']}. Continue with the next stage (see 'r1-retest status')."
                )
                return self.INCOMPLETE
            self._say(
                f"{operation.op_id} was submitted, but its output was lost. "
                "Look for the task id in serve.log, "
                f"then either 'r1-retest adopt {test_id} <task_id>' or "
                f"'r1-retest repeat {test_id} --ready'."
            )
            return self.INCOMPLETE
        if operation.starts_claude and not ready:
            self._say(f"Stage {stage.stage_id}: {stage.title}")
            for line in stage.before:
                self._say("  " + RetestProcedure.render(line, None))
            self._say(f"Nothing was sent. When ready: {stage.command(ready=True)}")
            return self.INCOMPLETE
        return self._execute(stage, operation, ledger, attempt, invocation)

    def _refusal(self, stage: Stage, ledger: Ledger) -> str | None:
        info = self._store.info()
        digest = tree_digest(self._src / "orbital") if (self._src / "orbital").is_dir() else None
        if digest != info["orbital"]["digest"]:
            return f"the orbital source under {self._src} changed since init (digest {digest})"
        if not key_present(self._environ):
            return "ORBITAL_BRIDGE_KEY is not set in this shell"
        return prerequisite_problem(stage.stage_id, ledger)

    def _execute(
        self,
        stage: Stage,
        operation: Operation,
        ledger: Ledger,
        attempt: int,
        invocation: list[str],
    ) -> int:
        test_id = stage.test_id
        self._store.append_event(
            "stage-started",
            {"stage_id": stage.stage_id, "test_id": test_id, "invocation": invocation},
        )
        if stage.preflight is not None and not self._preflight(stage):
            self._store.append_event(
                "stage-finished", {"stage_id": stage.stage_id, "outcome": "refused"}
            )
            return self.REFUSED
        if attempt == 0:
            attempt = 1
            self._store.append_event(
                "attempt-started", {"test_id": test_id, "attempt": 1, "reason": "first"}
            )
        task_id = (
            ledger.task_id(test_id, attempt, submit_op(test_id)) if operation.uses_task else None
        )
        tries = ledger.tries(test_id, attempt, operation.op_id)
        number = len(tries) + 1
        arguments = operation.command(task_id)
        self._say(
            f"{stage.stage_id} / {operation.op_id} (attempt {attempt}, try {number}): "
            f"{operation.display(task_id)}"
        )
        started = self._bridge.start(f"{operation.op_id}-a{attempt}-t{number}", arguments)
        self._store.append_event(
            "command-started",
            {
                "op_id": operation.op_id,
                "test_id": test_id,
                "attempt": attempt,
                "try": number,
                "stage_id": stage.stage_id,
                "command": operation.display(task_id),
                "arguments": list(arguments),
                **started,
            },
        )
        execution = self._bridge.wait(started, operation.budget_seconds)
        if execution is None:
            return self.INTERRUPTED
        return self._finish(stage, operation, attempt, number, execution)

    def _collect(self, stage: Stage, operation: Operation, ledger: Ledger, attempt: int) -> int:
        latest = ledger.latest_try(stage.test_id, attempt, operation.op_id)
        if latest is None or latest["started"] is None:
            self._say("Nothing to collect.")
            return self.INCOMPLETE
        self._say(
            f"{operation.op_id} was started earlier (try {latest['try']}) and not collected; "
            "collecting it now. Nothing new is sent."
        )
        execution = self._bridge.recover(latest["started"], operation.budget_seconds)
        if execution is None:
            self._say("It is still running; run the stage again later.")
            return self.INCOMPLETE
        return self._finish(stage, operation, attempt, latest["try"], execution)

    def _finish(
        self, stage: Stage, operation: Operation, attempt: int, number: int, execution: Execution
    ) -> int:
        test_id = stage.test_id
        self._store.append_event(
            "command-finished",
            {
                "op_id": operation.op_id,
                "test_id": test_id,
                "attempt": attempt,
                "try": number,
                "execution": execution.to_dict(),
            },
        )
        ledger = Ledger(self._store.events())
        if execution.outcome == "lost":
            self._store.append_event(
                "stage-finished", {"stage_id": stage.stage_id, "outcome": "lost"}
            )
            self._say(
                f"{operation.op_id}: the command left no output and no exit status. "
                + (
                    "Run the stage again; it has no side effects."
                    if not operation.starts_claude
                    else "Adopt the task id from serve.log, or repeat the test."
                )
            )
            return self.INCOMPLETE
        task_id = (
            ledger.task_id(test_id, attempt, submit_op(test_id)) if operation.uses_task else None
        )
        stdout = self._store.read_bytes(execution.stdout)
        submitted = self._submitted_at(ledger, test_id, attempt)
        result = evaluate_operation(operation, execution.to_dict(), stdout, task_id, submitted)
        self._store.append_event(
            "operation-evaluated",
            {
                "op_id": operation.op_id,
                "test_id": test_id,
                "attempt": attempt,
                "try": number,
                **result,
            },
        )
        self._store.append_event(
            "stage-finished", {"stage_id": stage.stage_id, "outcome": result["verdict"]}
        )
        self._show(operation, execution, result)
        self._after(stage, Ledger(self._store.events()))
        return self.OK if result["verdict"] == "passed" else self.FAILURES

    def _submitted_at(self, ledger: Ledger, test_id: str, attempt: int) -> Any:
        latest = ledger.latest_try(test_id, attempt, submit_op(test_id))
        finished = (latest or {}).get("finished") or {}
        moment = (finished.get("execution") or {}).get("finished_at")
        return parse_time(moment) if moment else None

    def _preflight(self, stage: Stage) -> bool:
        expectation = stage.preflight or "reachable"
        started = self._bridge.start(f"preflight-{stage.stage_id}", ("ping",))
        execution = self._bridge.wait(started, 60.0)
        if execution is None:
            return False
        outcome = evaluate_preflight(
            expectation, execution.to_dict(), self._store.read_bytes(execution.stdout)
        )
        self._store.append_event(
            "preflight",
            {
                "stage_id": stage.stage_id,
                "test_id": stage.test_id,
                "expectation": expectation,
                "command": "orbital-bridge ping",
                **started,
                "execution": execution.to_dict(),
                **outcome,
            },
        )
        if outcome["passed"]:
            return True
        if expectation == "reachable":
            self._say(
                f"Refused: the bridge does not answer a signed ping ({outcome['observed']}). "
                "Start or restart the server in the Claude sandbox first. Nothing was submitted."
            )
        else:
            self._say(
                f"Refused: the bridge still answers ({outcome['observed']}). Stop the server "
                "in the Claude sandbox first (see the checkpoint). Nothing else was sent."
            )
        return False

    # ------------------------------------------------------------------------------ display

    def _show(self, operation: Operation, execution: Execution, result: dict[str, Any]) -> None:
        observed = result["observed"]
        self._say(f"  expected: {operation.expected_text()}")
        shown = ", ".join(
            f"{k}={observed[k]}"
            for k in ("status", "code", "ok", "exit", "task_id")
            if k in observed
        )
        self._say(f"  observed: {shown or observed}")
        self._say(f"  verdict:  {result['verdict']}")
        for line in result["diagnostics"]:
            self._say(f"  - {line}")
        self._say(f"  evidence: {execution.stdout}, {execution.stderr}, {execution.exit_file}")

    def _after(self, stage: Stage, ledger: Ledger) -> None:
        task_id = ledger.task_id(
            stage.test_id, ledger.attempt(stage.test_id), submit_op(stage.test_id)
        )
        self._say("")
        for line in stage.after:
            self._say(RetestProcedure.render(line, task_id))

    # ------------------------------------------------------------------- operator decisions

    def repeat(self, test_id: str, ready: bool) -> int:
        test = RetestProcedure.test(test_id)
        if not test.repeatable:
            self._say(f"{test_id} needs no repeat: run its stage again ({test.stages[0]}).")
            return self.REFUSED
        ledger = Ledger(self._store.events())
        attempt = ledger.attempt(test_id)
        if attempt == 0 or ledger.op_state(test_id, attempt, submit_op(test_id)) == "not-run":
            self._say(f"{test_id} has no submitted task to repeat: run {test.stages[0]}.")
            return self.REFUSED
        if not ready:
            self._say(
                f"Repeating {test_id} starts a new attempt with a new task (a new real Claude run "
                f"when you run {test.stages[0]}). Earlier evidence is kept. Confirm with --ready."
            )
            return self.INCOMPLETE
        self._store.append_event(
            "attempt-started", {"test_id": test_id, "attempt": attempt + 1, "reason": "repeat"}
        )
        first = RetestProcedure.stage(test.stages[0])
        self._say(f"{test_id} attempt {attempt + 1} opened. Next: {first.command(ready=True)}")
        return self.OK

    def adopt(self, test_id: str, task_id: str) -> int:
        ledger = Ledger(self._store.events())
        attempt = ledger.attempt(test_id)
        if attempt == 0 or ledger.op_state(test_id, attempt, submit_op(test_id)) != "lost":
            self._say("Only a submission whose output was lost can adopt a task id.")
            return self.REFUSED
        if not TASK_ID.match(task_id):
            self._say(f"{task_id!r} is not a task id.")
            return self.REFUSED
        self._store.append_event(
            "task-adopted",
            {
                "test_id": test_id,
                "attempt": attempt,
                "task_id": task_id,
                "reason": "operator: from the Claude-side serve.log",
            },
        )
        self._say(f"{test_id} attempt {attempt} continues with task {task_id}.")
        return self.OK
