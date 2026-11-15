"""``r1-retest status``: where the run stands and what to do next."""

from __future__ import annotations

import argparse
from collections.abc import Mapping

from r1_retest.cli.utils import EXIT_INCOMPLETE, EXIT_OK, add_run_options, open_store, say
from r1_retest.evidence.ledger import Ledger
from r1_retest.report.assessment import Assessment
from r1_retest.runner.utils import next_steps


class StatusCommand:
    """Shows every test's verdict, the manual checks still open, and the next step."""

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser("status", help="show the run's state and the next step")
        add_run_options(parser)
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        store = open_store(args, environ)
        ledger = Ledger(store.events())
        assessment = Assessment(store, ledger)
        tests = assessment.tests()
        source = assessment.source()
        overall = assessment.overall(tests, source)
        say(f"Run {store.run_id} ({store.run_dir})")
        chat = source["chatgpt_side"]
        say(
            f"Source: digest {'matches' if chat['matches'] else 'DIFFERS FROM'} "
            f"the fixed implementation; Claude side: {source['claude_side']['verdict']}"
        )
        for test in tests:
            say(
                f"{test['test_id']} ({test['step']}) {test['title']}: {test['verdict']}"
                + (
                    f" — attempt {test['attempt']}, task {test['task_id']}"
                    if test["attempt"]
                    else ""
                )
            )
            for op in test["operations"]:
                say(
                    f"    {op['op_id']}: {op['verdict']}"
                    + (
                        f" — {op['diagnostics'][0]}"
                        if op["diagnostics"] and op["verdict"] != "passed"
                        else ""
                    )
                )
            for check in test["manual"]:
                say(
                    f"    {check['check_id']}: {check['verdict']}"
                    + (f" — {check['diagnostics'][0]}" if check["diagnostics"] else "")
                )
        unreadable = store.unreadable_events()
        if unreadable:
            say(f"Unreadable event files (skipped): {', '.join(unreadable)}")
        say("")
        say(f"Overall: {overall['verdict']}. {overall['statement']}")
        say("")
        say("Next:")
        for line in next_steps(ledger, tests):
            say("  " + line)
        return EXIT_OK if overall["verdict"] == "passed" else EXIT_INCOMPLETE
