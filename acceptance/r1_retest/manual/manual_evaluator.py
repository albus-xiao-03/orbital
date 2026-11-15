"""Judges the operator's Claude-side observations of one test attempt (QA-03 rules)."""

from __future__ import annotations

from typing import Any, ClassVar

from r1_retest.evidence.ledger import Ledger
from r1_retest.manual.utils import stop_signal, task_events
from r1_retest.procedure.manual_check import ManualCheck
from r1_retest.procedure.retest_procedure import RetestProcedure
from r1_retest.utils import parse_time, seconds_between


class ManualEvaluator:
    """Turns imported observations into checks: ``passed``, ``failed``, ``pending`` (evidence
    still missing) or ``inconclusive`` (evidence present but not sufficient).

    Timing uses only the Claude sandbox's clock: a process check's own ``date -u`` time against
    the serve.log record of the event (converted with the ``date +%z`` offset captured with
    it). When it was imported into the harness does not matter.
    """

    TIMELY_SECONDS: ClassVar[float] = 30.0
    CLOCK_RESOLUTION: ClassVar[float] = 1.0
    TRANSCRIPT_AFTER_SECONDS: ClassVar[float] = 10.0
    RESTART_WINDOW: ClassVar[tuple[float, float]] = (-1.0, 30.0)

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def evaluate(
        self,
        test_id: str,
        attempt: int,
        task_id: str | None,
        server_started_at: str | None,
        down_done: bool,
    ) -> list[dict[str, Any]]:
        checks = RetestProcedure.checks_of(test_id)
        if not checks:
            return []
        process = next(c for c in checks if c.kind == "process-check")
        evidence_check = next(c for c in checks if c.kind == "claude-evidence")
        label = process.check_id.split(".", 1)[0]
        evidence = self._latest_evidence(evidence_check, attempt, task_id)
        events = task_events(evidence["parsed"]["log"], task_id) if evidence and task_id else None
        found = self._imports(evidence_check, attempt)
        entries: list[dict[str, Any]] = []
        if evidence_check.expect_signal is None:
            serve_log, reference = self._timeout_record(
                label, evidence, events, evidence_check, found
            )
            entries.append(serve_log)
        else:
            shutdown, reference = self._shutdown_record(
                label, evidence, events, evidence_check, found, down_done
            )
            entries.append(shutdown)
            entries.append(
                self._restart_record(
                    label, evidence, events, evidence_check, found, server_started_at
                )
            )
        entries.insert(
            0, self._process_check(process, attempt, evidence, reference, evidence_check)
        )
        entries.append(self._transcript(label, evidence, events, reference, evidence_check, found))
        if task_id is None:
            for entry in entries:
                entry.update(verdict="not-applicable", diagnostics=["the attempt has no task id"])
        return entries

    # ------------------------------------------------------------------------------ evidence

    def _imports(self, check: ManualCheck, attempt: int) -> list[dict[str, Any]]:
        return self._ledger.manual(check.check_id, attempt)

    def _latest_evidence(
        self, check: ManualCheck, attempt: int, task_id: str | None
    ) -> dict[str, Any] | None:
        usable = [
            i
            for i in self._imports(check, attempt)
            if not i.get("unavailable")
            and i["parsed"].get("task_id") == task_id
            and "log" in i["parsed"]
        ]
        return usable[-1] if usable else None

    @staticmethod
    def _refs(imports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "path": i["file"],
                "sha256": i["sha256"],
                "imported_at": i["at"],
                "unavailable": i.get("unavailable"),
            }
            for i in imports
        ]

    def _entry(
        self,
        check_id: str,
        title: str,
        expected: str,
        check: ManualCheck,
        imports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "check_id": check_id,
            "title": title,
            "source": "manual",
            "verdict": "pending",
            "expected": expected,
            "observed": None,
            "diagnostics": [],
            "evidence": self._refs(imports),
            "command": check.command,
            "when": check.when,
            "timing": None,
        }

    def _missing(
        self, entry: dict[str, Any], check: ManualCheck, imports: list[dict[str, Any]]
    ) -> dict[str, Any]:
        unavailable = [i["unavailable"] for i in imports if i.get("unavailable")]
        if unavailable:
            entry.update(
                verdict="inconclusive", diagnostics=[f"recorded as unavailable: {unavailable[-1]}"]
            )
        elif imports:
            problems = [p for i in imports for p in i["parsed"].get("problems", [])]
            entry.update(
                verdict="inconclusive",
                diagnostics=["the imported evidence is unusable", *problems[:5]],
            )
        else:
            entry["diagnostics"] = [
                f"not recorded yet: run '{check.command}' in the Claude sandbox, then "
                f"'r1-retest record {check.check_id}'"
            ]
        return entry

    # ---------------------------------------------------------------------------- D-7 record

    def _timeout_record(
        self,
        label: str,
        evidence: dict[str, Any] | None,
        events: dict[str, Any] | None,
        check: ManualCheck,
        imports: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], str | None]:
        entry = self._entry(
            f"{label}.serve-log",
            "serve.log records the confirmed timeout",
            "the task accepted, 'Claude Code timed out after …' and "
            "'finished: timed_out (execution_timeout)'",
            check,
            imports,
        )
        if evidence is None or events is None:
            return self._missing(entry, check, imports), None
        if events["accepted"] is None:
            entry.update(
                verdict="inconclusive",
                diagnostics=["the task is not in the pasted serve.log lines"],
            )
            return entry, None
        timed_out = next((e for e in events["executor"] if "timed out after" in e["message"]), None)
        finished = next(
            (e for e in events["finished"] if "timed_out (execution_timeout)" in e["message"]), None
        )
        entry["observed"] = [e["message"] for e in (events["accepted"], timed_out, finished) if e]
        missing = [
            name
            for name, e in (("timed out", timed_out), ("finished: timed_out", finished))
            if e is None
        ]
        if missing:
            entry.update(verdict="failed", diagnostics=[f"missing: {', '.join(missing)}"])
            return entry, None
        entry["verdict"] = "passed"
        return entry, timed_out["utc"] if timed_out else None

    # -------------------------------------------------------------------- D-9 / A-4 records

    def _shutdown_record(
        self,
        label: str,
        evidence: dict[str, Any] | None,
        events: dict[str, Any] | None,
        check: ManualCheck,
        imports: list[dict[str, Any]],
        down_done: bool,
    ) -> tuple[dict[str, Any], str | None]:
        signal_name = check.expect_signal
        entry = self._entry(
            f"{label}.shutdown-record",
            f"serve.log records the graceful stop ({signal_name})",
            f"after the task was accepted: 'stopping ({signal_name}); …', "
            "'Claude Code exited with status 143', "
            "'finished: failed (execution_cancelled)', 'stopped'",
            check,
            imports,
        )
        if evidence is None or events is None:
            return self._missing(entry, check, imports), None
        if events["accepted"] is None:
            entry.update(
                verdict="inconclusive",
                diagnostics=["the task is not in the pasted serve.log lines"],
            )
            return entry, None
        stopping = events["stopping"]
        if stopping is None:
            ended = [e["message"] for e in events["finished"]]
            if ended:
                entry.update(
                    verdict="inconclusive",
                    observed=ended,
                    diagnostics=[
                        "the task ended before any stop; repeat the test and stop "
                        "the server within about 10 s"
                    ],
                )
            elif down_done:
                entry.update(
                    verdict="failed",
                    diagnostics=[
                        "the server was stopped, but serve.log has no "
                        "'stopping' record after the task"
                    ],
                )
            else:
                entry["diagnostics"] = ["no stop recorded yet: capture the evidence after the stop"]
            return entry, None
        name = stop_signal(stopping)
        executor = next((e for e in events["executor"] if e["order"] > stopping["order"]), None)
        finished = next((e for e in events["finished"] if e["order"] > stopping["order"]), None)
        stopped = events["stopped"]
        entry["observed"] = [e["message"] for e in (stopping, executor, finished, stopped) if e]
        if name is None:
            entry.update(
                verdict="inconclusive",
                diagnostics=[
                    "the stop line names no signal: the Claude "
                    "sandbox does not run the fixed code (plans/R1-fix.md)"
                ],
            )
            return entry, stopping["utc"]
        if name != signal_name:
            entry.update(
                verdict="inconclusive",
                diagnostics=[
                    f"the server was stopped with {name}; this test stops it with {signal_name}"
                ],
            )
            return entry, stopping["utc"]
        missing = []
        if executor is None:
            missing.append("the Claude Code exit")
        if finished is None or "failed (execution_cancelled)" not in finished["message"]:
            missing.append("'finished: failed (execution_cancelled)'")
        if stopped is None:
            missing.append("'stopped'")
        if missing:
            entry.update(
                verdict="failed", diagnostics=[f"the stop record lacks {', '.join(missing)}"]
            )
            return entry, stopping["utc"]
        entry["verdict"] = "passed"
        if executor is not None and "exited with status 143" not in executor["message"]:
            entry["diagnostics"].append(
                "Claude Code did not end with status 143 as in the plan; the bridge "
                "still terminated and recorded it"
            )
        return entry, stopping["utc"]

    def _restart_record(
        self,
        label: str,
        evidence: dict[str, Any] | None,
        events: dict[str, Any] | None,
        check: ManualCheck,
        imports: list[dict[str, Any]],
        server_started_at: str | None,
    ) -> dict[str, Any]:
        entry = self._entry(
            f"{label}.restart-record",
            "serve.log records the restart that the last poll reached",
            "a 'listening on …' line after 'stopped', at the start time "
            "named by the unknown_task message",
            check,
            imports,
        )
        if evidence is None or events is None:
            return self._missing(entry, check, imports)
        if events["stopped"] is None:
            entry["diagnostics"] = ["no complete stop record yet (see the shutdown record)"]
            return entry
        restart = events["restart"]
        if restart is None:
            if (
                server_started_at is not None
                and evidence["parsed"]["captured_at"] >= server_started_at
            ):
                entry.update(
                    verdict="inconclusive",
                    diagnostics=["no start after the stop in the pasted lines"],
                )
            else:
                entry["diagnostics"] = ["capture the evidence again after the restart"]
            return entry
        entry["observed"] = [f"{restart['utc']} {restart['message']}"]
        if server_started_at is None:
            entry["diagnostics"] = [
                "run the restart stage, whose poll names the server's start time"
            ]
            return entry
        delta = seconds_between(parse_time(restart["utc"]), parse_time(server_started_at))
        entry["timing"] = {
            "listening_at": restart["utc"],
            "server_started_at": server_started_at,
            "seconds": delta,
        }
        low, high = self.RESTART_WINDOW
        if low <= delta <= high:
            entry["verdict"] = "passed"
        else:
            entry.update(
                verdict="inconclusive",
                diagnostics=[
                    f"the start after the stop is {delta} s from the start time the poll reported"
                ],
            )
        return entry

    # ---------------------------------------------------------------------------- transcript

    def _transcript(
        self,
        label: str,
        evidence: dict[str, Any] | None,
        events: dict[str, Any] | None,
        reference: str | None,
        check: ManualCheck,
        imports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        what = "the timeout" if check.expect_signal is None else "the stop"
        entry = self._entry(
            f"{label}.transcript",
            f"The Claude Code transcript ends at {what}",
            f"last written within a few seconds of {what}; no SLEPT reply",
            check,
            imports,
        )
        if evidence is None or events is None:
            return self._missing(entry, check, imports)
        parsed = evidence["parsed"]
        transcript = parsed.get("transcript")
        counts = parsed.get("slept_counts") or []
        entry["observed"] = {"transcript": transcript, "slept_counts": counts}
        if counts and max(counts) > 0:
            entry.update(
                verdict="failed",
                diagnostics=[
                    "the transcript has a SLEPT reply: the run finished "
                    f"its work instead of ending at {what}"
                ],
            )
            return entry
        if transcript is None:
            entry.update(
                verdict="inconclusive",
                diagnostics=["the transcript was not found", *parsed.get("transcript_raw", [])[:2]],
            )
            return entry
        if not counts:
            entry.update(
                verdict="inconclusive", diagnostics=["no SLEPT count in the pasted output"]
            )
            return entry
        if reference is None or events["accepted"] is None:
            entry.update(
                verdict="inconclusive",
                diagnostics=[f"serve.log does not show {what}, so the transcript cannot be timed"],
            )
            return entry
        modified = parse_time(transcript["modified_at"])
        after = seconds_between(modified, parse_time(reference))
        since_accepted = seconds_between(modified, parse_time(events["accepted"]["utc"]))
        entry["timing"] = {
            "modified_at": transcript["modified_at"],
            "reference": reference,
            "seconds_after_reference": after,
        }
        if after > self.TRANSCRIPT_AFTER_SECONDS:
            entry.update(
                verdict="inconclusive",
                diagnostics=[f"the transcript was written {after} s after {what}"],
            )
        elif since_accepted < -2.0:
            entry.update(
                verdict="inconclusive", diagnostics=["the transcript is older than the task"]
            )
        else:
            entry["verdict"] = "passed"
        return entry

    # ------------------------------------------------------------------------ process check

    def _process_check(
        self,
        check: ManualCheck,
        attempt: int,
        evidence: dict[str, Any] | None,
        reference: str | None,
        evidence_check: ManualCheck,
    ) -> dict[str, Any]:
        imports = self._imports(check, attempt)
        what = "the timeout" if check.reference == "timeout" else "the stop"
        entry = self._entry(
            check.check_id,
            check.title,
            f"made within {self.TIMELY_SECONDS:g} s of {what}, by the Claude sandbox's own "
            "clock; 'none' twice",
            check,
            imports,
        )
        observations = [i for i in imports if not i.get("unavailable")]
        if not observations:
            return self._missing(entry, check, imports)
        if reference is None:
            if evidence is None:
                entry["diagnostics"] = [
                    f"record {evidence_check.check_id} too: its serve.log lines time "
                    "this observation"
                ]
            else:
                entry.update(
                    verdict="inconclusive",
                    diagnostics=[
                        f"serve.log does not show {what}, so the observation cannot be timed"
                    ],
                )
            entry["observed"] = [self._describe(o, None) for o in observations]
            return entry
        described = [self._describe(o, reference) for o in observations]
        entry["observed"] = described
        entry["timing"] = {"reference": reference, "window_seconds": self.TIMELY_SECONDS}
        running = [d for d in described if d["processes"] and d["class"] in ("timely", "late")]
        timely_clear = [
            d
            for d in described
            if d["class"] == "timely" and not d["processes"] and not d["problems"]
        ]
        if running:
            entry.update(
                verdict="failed",
                diagnostics=[
                    f"processes still running {d['seconds']} s after {what}: "
                    f"{'; '.join(d['processes'])}"
                    for d in running
                ],
            )
        elif timely_clear:
            entry["verdict"] = "passed"
        else:
            reasons = sorted({d["class"] for d in described})
            entry.update(
                verdict="inconclusive",
                diagnostics=[
                    f"no observation both timely and clear ({', '.join(reasons)}); "
                    "a late check does not count: repeat the test if the window has passed"
                ],
            )
        return entry

    def _describe(self, observation: dict[str, Any], reference: str | None) -> dict[str, Any]:
        parsed = observation["parsed"]
        result = {
            "file": observation["file"],
            "imported_at": observation["at"],
            "observed_at": parsed.get("observed_at"),
            "processes": parsed.get("processes", []),
            "problems": parsed.get("problems", []),
            "seconds": None,
            "class": "untimed",
        }
        if parsed.get("observed_at") is None or reference is None:
            return result
        seconds = seconds_between(parse_time(parsed["observed_at"]), parse_time(reference))
        result["seconds"] = seconds
        if seconds < -self.CLOCK_RESOLUTION:
            result["class"] = "before-event"
        elif seconds <= self.TIMELY_SECONDS:
            result["class"] = "timely"
        else:
            result["class"] = "late"
        return result
