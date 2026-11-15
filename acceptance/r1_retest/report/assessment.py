"""The judgement of a run: every test, the source identity, the overall result and AC1 to AC7."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from r1_retest.evidence.evidence_store import EvidenceStore
from r1_retest.evidence.ledger import Ledger
from r1_retest.manual.manual_evaluator import ManualEvaluator
from r1_retest.procedure.retest_procedure import RetestProcedure
from r1_retest.report.utils import (
    FAILED,
    INCONCLUSIVE,
    NOT_APPLICABLE,
    PASSED,
    PENDING,
    combine,
)
from r1_retest.utils import EXPECTED_SOURCE_DIGEST, PREVIOUS_RUN_ID, tree_digest


class Assessment:
    """Judges the evidence of one run as it stands; it never changes the evidence."""

    def __init__(self, store: EvidenceStore, ledger: Ledger) -> None:
        self._store = store
        self._ledger = ledger
        self._manual = ManualEvaluator(ledger)

    # ---------------------------------------------------------------------------------- tests

    def tests(self) -> list[dict[str, Any]]:
        return [self.test(t.test_id) for t in RetestProcedure.TESTS]

    def test(self, test_id: str) -> dict[str, Any]:
        definition = RetestProcedure.test(test_id)
        attempt = self._ledger.attempt(test_id)
        stages = RetestProcedure.stages_of(test_id)
        submit_op = stages[0].operation
        task_id = self._ledger.task_id(test_id, attempt, submit_op) if attempt else None
        entry: dict[str, Any] = {
            "test_id": test_id,
            "step": definition.step,
            "title": definition.title,
            "required": definition.required,
            "criteria": list(definition.criteria),
            "expected": definition.expected,
            "attempt": attempt,
            "task_id": task_id,
            "task_adopted": self._ledger.adopted(test_id, attempt) is not None
            if attempt
            else False,
            "operations": [],
            "manual": [],
            "earlier_attempts": [],
        }
        if attempt == 0:
            entry["verdict"] = PENDING if definition.required else NOT_APPLICABLE
            entry["note"] = "not started" if definition.required else "optional; not run"
            return entry
        for stage in stages:
            entry["operations"].append(self.operation(test_id, attempt, stage.operation, task_id))
        restart = next(
            (
                o["observed"]["server_started_at"]
                for o in entry["operations"]
                if o.get("observed", {}).get("server_started_at")
            ),
            None,
        )
        down_op = stages[1].operation if len(stages) > 1 else None
        down_done = (
            down_op is not None and self._ledger.op_state(test_id, attempt, down_op) == "evaluated"
        )
        entry["manual"] = self._manual.evaluate(test_id, attempt, task_id, restart, down_done)
        entry["verdict"] = combine(
            [o["verdict"] for o in entry["operations"]] + [m["verdict"] for m in entry["manual"]]
        )
        for earlier in range(1, attempt):
            ops = [
                self.operation(
                    test_id, earlier, s.operation, self._ledger.task_id(test_id, earlier, submit_op)
                )
                for s in stages
            ]
            entry["earlier_attempts"].append(
                {
                    "attempt": earlier,
                    "task_id": self._ledger.task_id(test_id, earlier, submit_op),
                    "operations": {o["op_id"]: o["verdict"] for o in ops},
                    "note": "superseded by a later attempt; its evidence is kept",
                }
            )
        return entry

    def operation(
        self, test_id: str, attempt: int, op_id: str, task_id: str | None
    ) -> dict[str, Any]:
        operation = RetestProcedure.operation(op_id)
        state = self._ledger.op_state(test_id, attempt, op_id)
        tries = self._ledger.tries(test_id, attempt, op_id)
        entry: dict[str, Any] = {
            "op_id": op_id,
            "stage_id": operation.stage_id,
            "description": operation.description,
            "command": operation.display(task_id if operation.uses_task else None),
            "expected": operation.expected_text(),
            "state": state,
            "observed": {},
            "diagnostics": [],
            "tries": [self._try(t) for t in tries],
        }
        if state == "evaluated":
            result = self._ledger.op_result(test_id, attempt, op_id) or {}
            entry.update(
                verdict=result.get("verdict", FAILED),
                observed=result.get("observed") or {},
                diagnostics=list(result.get("diagnostics") or []),
                document=result.get("document"),
                task_id=result.get("task_id"),
            )
        elif state == "not-run":
            entry.update(
                verdict=PENDING, diagnostics=[f"not run yet: r1-retest run {operation.stage_id}"]
            )
        elif state == "in-flight":
            entry.update(
                verdict=PENDING, diagnostics=["started but not collected: run the stage again"]
            )
        else:
            adopted = self._ledger.adopted(test_id, attempt)
            lost = "the command's output was lost"
            note = (
                f"{lost}; task id {adopted['task_id']} adopted by the operator"
                if adopted and operation.starts_claude
                else f"{lost}: adopt the task id (r1-retest adopt) or repeat the test"
            )
            entry.update(verdict=INCONCLUSIVE, diagnostics=[note])
        return entry

    def _try(self, record: dict[str, Any]) -> dict[str, Any]:
        started = record["started"] or {}
        finished = (record["finished"] or {}).get("execution") or {}
        files = {
            name: self._store.describe(started[name])
            for name in ("stdout", "stderr", "exit_file")
            if started.get(name)
        }
        return {
            "try": record["try"],
            "command": started.get("command"),
            "started_at": started.get("started_at"),
            "finished_at": finished.get("finished_at"),
            "duration_seconds": finished.get("duration_seconds"),
            "outcome": finished.get("outcome", "not finished"),
            "exit_code": finished.get("exit_code"),
            "recovered": finished.get("recovered", False),
            "files": files,
        }

    # --------------------------------------------------------------------------------- source

    def source(self) -> dict[str, Any]:
        info = self._store.info()
        orbital = info.get("orbital", {})
        src = Path(orbital.get("src", ""))
        current = tree_digest(src / "orbital") if (src / "orbital").is_dir() else None
        chatgpt = {
            "src": orbital.get("src"),
            "commit": orbital.get("commit"),
            "digest": orbital.get("digest"),
            "expected_digest": EXPECTED_SOURCE_DIGEST,
            "matches": orbital.get("digest") == EXPECTED_SOURCE_DIGEST,
            "unchanged_since_init": current == orbital.get("digest") if current else None,
            "mismatch_allowed": orbital.get("mismatch_allowed", False),
        }
        imports = [
            i for i in self._ledger.manual("claude-source", None) if not i.get("unavailable")
        ]
        claude: dict[str, Any] = {
            "verdict": NOT_APPLICABLE,
            "note": "not recorded (optional): see the stop "
            "line, which names its signal only with the fixed code",
        }
        if imports:
            parsed = imports[-1]["parsed"]
            ok = parsed.get("digest") == EXPECTED_SOURCE_DIGEST
            claude = {
                "verdict": PASSED if ok else FAILED,
                "digest": parsed.get("digest"),
                "commit": parsed.get("commit"),
                "captured_at": parsed.get("captured_at"),
                "evidence": imports[-1]["file"],
                "note": "matches the fixed implementation"
                if ok
                else "differs from the fixed implementation",
            }
        return {"chatgpt_side": chatgpt, "claude_side": claude}

    # -------------------------------------------------------------------------------- overall

    def overall(self, tests: list[dict[str, Any]], source: dict[str, Any]) -> dict[str, Any]:
        required = [t for t in tests if t["required"]]
        verdicts = {t["test_id"]: t["verdict"] for t in required}
        problems = []
        chatgpt = source["chatgpt_side"]
        if not chatgpt["matches"]:
            problems.append("the ChatGPT-side source is not the fixed implementation")
        if chatgpt["unchanged_since_init"] is False:
            problems.append("the ChatGPT-side source changed after init")
        if source["claude_side"]["verdict"] == FAILED:
            problems.append("the Claude sandbox does not run the fixed implementation")
        verdict = combine(verdicts.values())
        if problems and verdict == PASSED:
            verdict = INCONCLUSIVE
        if source["claude_side"]["verdict"] == FAILED:
            verdict = FAILED
        names = {
            v: [t for t, tv in verdicts.items() if tv == v] for v in (FAILED, INCONCLUSIVE, PENDING)
        }
        if verdict == PASSED:
            statement = (
                f"Every required re-test (A-3, A-2, A-1) passed. With the evidence carried forward "
                f"from {PREVIOUS_RUN_ID}, the evidence supports AC1 to AC7. "
                "The acceptance decision is yours."
            )
        elif verdict == FAILED:
            statement = f"R1 is not accepted: failed {', '.join(names[FAILED]) or 'source check'}."
        else:
            parts = [f"{k} {', '.join(v)}" for k, v in names.items() if v]
            statement = (
                "R1 acceptance is not established yet: "
                + ("; ".join(parts + problems) or "see below")
                + "."
            )
        optional = next((t for t in tests if t["test_id"] == "A-4"), None)
        return {
            "verdict": verdict,
            "statement": statement,
            "required": verdicts,
            "problems": problems,
            "optional_a4": optional["verdict"] if optional else NOT_APPLICABLE,
        }

    def criteria(self, tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {t["test_id"]: t for t in tests}
        found = []
        for ac, text, new, carried in RetestProcedure.CRITERIA:
            new_parts = [
                {"test_id": t, "step": by_id[t]["step"], "verdict": by_id[t]["verdict"]}
                for t in new
            ]
            verdict = combine([p["verdict"] for p in new_parts]) if new_parts else PASSED
            basis = (
                "newly verified and carried forward"
                if new_parts and carried
                else "newly verified"
                if new_parts
                else "carried forward only"
            )
            found.append(
                {
                    "criterion": ac,
                    "text": text,
                    "verdict": verdict,
                    "basis": basis,
                    "newly_verified": new_parts,
                    "carried_forward": [
                        {"step": s, "verdict": PASSED, "run": PREVIOUS_RUN_ID} for s in carried
                    ],
                }
            )
        return found
