"""``r1-acceptance record``: record a manual check, or skip a step."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar

from r1_acceptance.cli.utils import (
    EXIT_OK,
    add_run_options,
    complain,
    consistency,
    ledger_for,
    open_store,
    say,
)
from r1_acceptance.evidence.evidence_store import EvidenceStore
from r1_acceptance.evidence.run_ledger import RunLedger
from r1_acceptance.models.check_result import CheckResult
from r1_acceptance.models.verdict import Verdict
from r1_acceptance.procedure.r1_procedure import R1Procedure
from r1_acceptance.procedure.utils import next_action_lines, placeholder_values, render
from r1_acceptance.utils import format_time, utc_now


class RecordCommand:
    """Record the operator's observation of the Claude sandbox, or a step's skip.

    A manual check is recorded for the latest attempt of its step, with the operator's verdict,
    the observed output, a note and attached files. The harness only says whether the observed
    output matches the expectation; the verdict is the operator's. Each record is a new event,
    so earlier records are kept.
    """

    VERDICTS: ClassVar[Mapping[str, Verdict]] = MappingProxyType(
        {"pass": Verdict.PASSED, "fail": Verdict.FAILED, "skip": Verdict.SKIPPED}
    )

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser(
            "record",
            help="record a manual check (pass, fail or skip), or skip a step",
            description="Record a manual check of the Claude sandbox, or skip a whole step "
            "(STEP skip --note REASON). The ids are listed by 'r1-acceptance status'.",
        )
        parser.add_argument("item", metavar="CHECK_OR_STEP")
        parser.add_argument("verdict", choices=tuple(self.VERDICTS))
        parser.add_argument("--note", default="", help="free text kept with the record")
        parser.add_argument(
            "--observed",
            metavar="TEXT",
            help="what the check printed; '-' reads it from stdin (paste, then Ctrl-D)",
        )
        parser.add_argument(
            "--attach",
            metavar="FILE",
            action="append",
            default=[],
            help="copy a file into the run as evidence (repeatable)",
        )
        add_run_options(parser)
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace) -> int:
        """Record the item; return an exit code."""
        try:
            store = open_store(args)
            store.lock()
        except (LookupError, RuntimeError) as exc:
            return complain(str(exc))
        if args.item in {step.step_id for step in R1Procedure.STEPS}:
            return self._skip(store, args)
        try:
            check = R1Procedure.manual_check(args.item)
        except KeyError:
            known = ", ".join(check.check_id for check in R1Procedure.MANUAL_CHECKS)
            return complain(f"unknown check or step {args.item!r}; manual checks: {known}")
        ledger = ledger_for(store)
        attempt = ledger.latest_attempt(check.step_id)
        if attempt == 0:
            return complain(
                f"{check.step_id} has not run yet; record {check.check_id} after its stage"
            )
        observed = sys.stdin.read() if args.observed == "-" else (args.observed or "")
        attachments = []
        for name in args.attach:
            try:
                attachments.append(store.store_attachment(Path(name).expanduser()))
            except (OSError, ValueError) as exc:
                return complain(f"cannot attach {name}: {exc}")
        task_id = ledger.task_id(check.step_id, attempt)
        values = placeholder_values(store.info.get("settings", {}), task_id)
        matches = consistency(check, observed, values)
        hint = {
            None: "",
            True: "the observed output matches the expectation",
            False: "the observed output does not match the expectation",
        }[matches]
        verdict = self.VERDICTS[args.verdict]
        result = CheckResult(
            check_id=check.check_id,
            description=check.title,
            source=CheckResult.MANUAL,
            verdict=verdict,
            expected=render(check.expectation, values),
            observed=observed,
            diagnostic=hint,
            recorded_at=format_time(utc_now()),
            note=args.note,
            attachments=tuple(attachments),
        )
        store.append_event(
            RunLedger.MANUAL_RECORDED,
            {"attempt": attempt, "task_id": task_id, "result": result.to_dict()},
        )
        say(f"Recorded {check.check_id}: {verdict.value} (attempt {attempt} of {check.step_id}).")
        if hint:
            say(f"Note: {hint}.")
        if (verdict is Verdict.PASSED and matches is False) or (
            verdict is Verdict.FAILED and matches is True
        ):
            say(
                "Warning: the verdict and the observed output disagree; record it again if "
                "that was a mistake (the latest record counts, earlier ones are kept)."
            )
        status = ledger_for(store).step_status(check.step_id)
        say(f"{check.step_id} is now {status.verdict.value}.")
        return EXIT_OK

    @staticmethod
    def _skip(store: EvidenceStore, args: argparse.Namespace) -> int:
        if args.verdict != "skip":
            return complain(
                f"{args.item} is a step: only 'skip' can be recorded for it (manual checks have "
                "their own ids; see r1-acceptance status)"
            )
        reason = args.note.strip()
        if not reason:
            return complain("give the reason for the skip with --note")
        store.append_event(RunLedger.STEP_SKIPPED, {"step": args.item, "reason": reason})
        say(f"Recorded: {args.item} skipped ({reason}).")
        say("", *next_action_lines(ledger_for(store), store.info.get("settings", {})))
        return EXIT_OK
