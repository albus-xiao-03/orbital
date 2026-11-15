"""The state of a run, derived from its append-only events (nothing else is ever updated)."""

from __future__ import annotations

from typing import Any


class Ledger:
    """Read-only views over a run's events.

    A test runs in *attempts* (a new attempt is a new task, started only by the operator); an
    operation without side effects may run several *tries* within one attempt. The latest try
    counts; every earlier one stays in the evidence.
    """

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("kind") == kind]

    # ------------------------------------------------------------------------------ attempts

    def attempt(self, test_id: str) -> int:
        numbers = [
            e["attempt"] for e in self.of_kind("attempt-started") if e.get("test_id") == test_id
        ]
        return max(numbers, default=0)

    def attempt_events(self, test_id: str) -> list[dict[str, Any]]:
        return [e for e in self.of_kind("attempt-started") if e.get("test_id") == test_id]

    # ---------------------------------------------------------------------------- operations

    def tries(self, test_id: str, attempt: int, op_id: str) -> list[dict[str, Any]]:
        """Each try as ``{"try", "started", "finished", "evaluated"}`` (missing parts are None)."""
        found: dict[int, dict[str, Any]] = {}
        for event in self.events:
            if (event.get("test_id"), event.get("attempt"), event.get("op_id")) != (
                test_id,
                attempt,
                op_id,
            ):
                continue
            slot = {
                "command-started": "started",
                "command-finished": "finished",
                "operation-evaluated": "evaluated",
            }.get(event.get("kind", ""))
            if slot is None:
                continue
            entry = found.setdefault(
                event["try"],
                {"try": event["try"], "started": None, "finished": None, "evaluated": None},
            )
            entry[slot] = event
        return [found[number] for number in sorted(found)]

    def latest_try(self, test_id: str, attempt: int, op_id: str) -> dict[str, Any] | None:
        tries = self.tries(test_id, attempt, op_id)
        return tries[-1] if tries else None

    def op_state(self, test_id: str, attempt: int, op_id: str) -> str:
        """``not-run``, ``in-flight`` (started, not finished), ``lost`` or ``evaluated``."""
        latest = self.latest_try(test_id, attempt, op_id)
        if latest is None:
            return "not-run"
        if latest["evaluated"] is not None:
            return "evaluated"
        if latest["finished"] is None:
            return "in-flight"
        return "lost"

    def op_result(self, test_id: str, attempt: int, op_id: str) -> dict[str, Any] | None:
        latest = self.latest_try(test_id, attempt, op_id)
        return latest["evaluated"] if latest else None

    def op_passed(self, test_id: str, attempt: int, op_id: str) -> bool:
        result = self.op_result(test_id, attempt, op_id)
        return result is not None and result.get("verdict") == "passed"

    def task_id(self, test_id: str, attempt: int, submit_op: str) -> str | None:
        """The attempt's task id: from its submission, or adopted by the operator."""
        result = self.op_result(test_id, attempt, submit_op)
        if result is not None and result.get("task_id"):
            return str(result["task_id"])
        adopted = [
            e
            for e in self.of_kind("task-adopted")
            if e.get("test_id") == test_id and e.get("attempt") == attempt
        ]
        return str(adopted[-1]["task_id"]) if adopted else None

    def adopted(self, test_id: str, attempt: int) -> dict[str, Any] | None:
        adopted = [
            e
            for e in self.of_kind("task-adopted")
            if e.get("test_id") == test_id and e.get("attempt") == attempt
        ]
        return adopted[-1] if adopted else None

    # ------------------------------------------------------------------------- manual imports

    def manual(self, check_id: str, attempt: int | None) -> list[dict[str, Any]]:
        return [
            e
            for e in self.of_kind("manual-recorded")
            if e.get("check_id") == check_id and (attempt is None or e.get("attempt") == attempt)
        ]

    # ---------------------------------------------------------------------------------- other

    def preflights(self) -> list[dict[str, Any]]:
        return self.of_kind("preflight")

    def environment_check(self) -> dict[str, Any] | None:
        checks = self.of_kind("environment-checked")
        return checks[-1] if checks else None
