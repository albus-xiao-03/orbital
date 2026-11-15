"""``r1-acceptance status``: where a run stands and what to do next."""

from __future__ import annotations

import argparse

from r1_acceptance.cli.utils import EXIT_OK, add_run_options, complain, ledger_for, open_store, say
from r1_acceptance.procedure.r1_procedure import R1Procedure
from r1_acceptance.procedure.utils import (
    manual_check_lines,
    next_action_lines,
    pending_manual_checks,
    placeholder_values,
    rerun_hint_lines,
)


class StatusCommand:
    """Show every step's verdict, the manual checks still to record, and the next action.

    It only reads the evidence; nothing is sent to the bridge and nothing is written.
    """

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser(
            "status",
            help="show where the run stands and what to do next",
            description="Show the verdict of every step, the manual checks that are still to "
            "be recorded, and the next action. Nothing is sent and nothing is written.",
        )
        add_run_options(parser)
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace) -> int:
        """Print the status; return an exit code."""
        try:
            store = open_store(args)
            ledger = ledger_for(store)
        except LookupError as exc:
            return complain(str(exc))
        except ValueError as exc:
            return complain(f"the run could not be read ({exc}); if a stage is running, retry")
        info = store.info
        settings = info.get("settings", {})
        say(
            f"Run {store.run_id}, created {info.get('created_at')}, bridge {settings.get('url')}",
            f"Evidence: {store.run_dir}",
            *[
                f"Warning: unreadable event file {name} (skipped; a command was killed while "
                "writing it)"
                for name in store.unreadable_events()
            ],
            "",
            f"{'Step':<5} {'Verdict':<15} {'Stages':<16} {'Task id':<36}  Title",
        )
        for step in R1Procedure.STEPS:
            status = ledger.step_status(step.step_id)
            stages = ",".join(R1Procedure.stages_of(step.step_id))
            title = step.title + (" (optional)" if step.optional else "")
            say(
                f"{step.step_id:<5} {status.verdict.value:<15} {stages:<16} "
                f"{status.task_id or '-':<36}  {title}"
            )
        pending = pending_manual_checks(ledger)
        if pending:
            say("", "Manual checks to record:")
            for check, task_id in pending:
                say(*manual_check_lines(check, placeholder_values(settings, task_id)))
        hints = rerun_hint_lines(ledger)
        if hints:
            say("", *hints)
        say("", *next_action_lines(ledger, settings))
        return EXIT_OK
