"""``r1-retest record``, ``attach`` and ``note``: the operator's Claude-side evidence."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from r1_retest.cli.utils import (
    EXIT_OK,
    EXIT_REFUSED,
    add_run_options,
    complain,
    open_store,
    read_input,
    say,
)
from r1_retest.evidence.ledger import Ledger
from r1_retest.evidence.utils import ATTACHMENTS_DIR, MANUAL_DIR
from r1_retest.manual.utils import parse_claude_evidence, parse_claude_source, parse_process_check
from r1_retest.procedure.retest_procedure import RetestProcedure
from r1_retest.report.assessment import Assessment
from r1_retest.runner.utils import submit_op
from r1_retest.utils import sha256_bytes


class RecordCommand:
    """Imports pasted Claude-side output as immutable evidence and shows how it is judged.

    The raw text is kept byte for byte; the parsed reading is stored next to it. What decides a
    verdict is when the observation was *made* (its own ``date -u`` line), never when it was
    imported.
    """

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        record = commands.add_parser(
            "record", help="import a Claude-side observation (paste, then Ctrl-D)"
        )
        add_run_options(record)
        record.add_argument("check", choices=[c.check_id for c in RetestProcedure.CHECKS])
        record.add_argument("--file", help="read the observation from a file instead of stdin")
        record.add_argument(
            "--attempt", type=int, help="the test attempt (default: the current one)"
        )
        record.add_argument(
            "--unavailable",
            metavar="REASON",
            help="record that the observation could not be made, and why",
        )
        record.set_defaults(handler=self.record)
        attach = commands.add_parser("attach", help="attach a file, such as the whole serve.log")
        add_run_options(attach)
        attach.add_argument("label", help="a short name, for example serve.log")
        attach.add_argument("--file", help="the file to attach (default: stdin)")
        attach.set_defaults(handler=self.attach)
        note = commands.add_parser("note", help="add a note to the run (for example a deviation)")
        add_run_options(note)
        note.add_argument("text")
        note.set_defaults(handler=self.note)

    def record(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        check = RetestProcedure.check(args.check)
        store = open_store(args, environ)
        with store.lock():
            ledger = Ledger(store.events())
            attempt: int | None = None
            task_id = None
            if check.test_id is not None:
                current = ledger.attempt(check.test_id)
                attempt = args.attempt or current
                if attempt < 1 or attempt > current:
                    complain(
                        f"{check.test_id} has no attempt {attempt} (current: {current}); "
                        "nothing recorded"
                    )
                    return EXIT_REFUSED
                task_id = ledger.task_id(check.test_id, attempt, submit_op(check.test_id))
            data = b"" if args.unavailable and args.file is None else read_input(args.file)
            text = data.decode("utf-8", "replace")
            parsed = self._parse(check.kind, text) if not args.unavailable else {"problems": []}
            refusal = self._refusal(check.kind, parsed, task_id, check.test_id)
            if refusal and not args.unavailable:
                complain(f"{refusal}; nothing recorded")
                return EXIT_REFUSED
            stored = (
                data
                if not args.unavailable
                else f"UNAVAILABLE: {args.unavailable}\n".encode() + data
            )
            relative = store.write_file(MANUAL_DIR, f"{check.check_id}-a{attempt or 0}.txt", stored)
            store.append_event(
                "manual-recorded",
                {
                    "check_id": check.check_id,
                    "test_id": check.test_id,
                    "attempt": attempt,
                    "file": relative,
                    "sha256": sha256_bytes(stored),
                    "bytes": len(stored),
                    "unavailable": args.unavailable,
                    "parsed": parsed,
                },
            )
            say(f"Recorded {check.check_id} (attempt {attempt}) as {relative}")
            for problem in parsed.get("problems", []):
                say(f"  warning: {problem}")
            self._show(store, check.test_id)
        return EXIT_OK

    @staticmethod
    def _parse(kind: str, text: str) -> dict[str, Any]:
        if kind == "process-check":
            return parse_process_check(text)
        if kind == "claude-evidence":
            return parse_claude_evidence(text)
        return parse_claude_source(text)

    @staticmethod
    def _refusal(
        kind: str, parsed: dict[str, Any], task_id: str | None, test_id: str | None
    ) -> str | None:
        if kind == "claude-evidence":
            if "log" not in parsed:
                return "; ".join(parsed.get("problems", [])) or "not the output of orbital_evidence"
            if task_id is None:
                return f"{test_id} has no task id yet"
            if parsed.get("task_id") != task_id:
                return (
                    f"this evidence is for task {parsed.get('task_id')}, "
                    f"but {test_id}'s current attempt is task {task_id}"
                )
        if kind == "claude-source" and parsed.get("captured_at") is None:
            return "not the output of orbital_source"
        return None

    @staticmethod
    def _show(store: Any, test_id: str | None) -> None:
        if test_id is None:
            source = Assessment(store, Ledger(store.events())).source()["claude_side"]
            say(f"  Claude-side source: {source['verdict']} ({source.get('note')})")
            return
        entry = Assessment(store, Ledger(store.events())).test(test_id)
        say(f"  {test_id} now: {entry['verdict']}")
        for check in entry["manual"]:
            detail = f" — {check['diagnostics'][0]}" if check["diagnostics"] else ""
            say(f"    {check['check_id']}: {check['verdict']}{detail}")

    def attach(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        store = open_store(args, environ)
        with store.lock():
            data = read_input(args.file)
            relative = store.write_file(ATTACHMENTS_DIR, args.label, data)
            store.append_event(
                "attachment-added",
                {
                    "label": args.label,
                    "file": relative,
                    "sha256": sha256_bytes(data),
                    "bytes": len(data),
                    "origin": args.file or "stdin",
                },
            )
        say(f"Attached {args.label} as {relative} ({len(data)} bytes)")
        return EXIT_OK

    def note(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        store = open_store(args, environ)
        with store.lock():
            store.append_event("note-added", {"text": args.text})
        say("Note added.")
        return EXIT_OK
