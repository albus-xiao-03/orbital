"""``r1-retest report``: write a new Markdown and JSON report (earlier reports are kept)."""

from __future__ import annotations

import argparse
from collections.abc import Mapping

from r1_retest.cli.utils import (
    EXIT_FAILURES,
    EXIT_INCOMPLETE,
    EXIT_OK,
    add_run_options,
    open_store,
    say,
)
from r1_retest.evidence.ledger import Ledger
from r1_retest.report.markdown_report import MarkdownReport
from r1_retest.report.report_builder import ReportBuilder
from r1_retest.utils import json_bytes


class ReportCommand:
    """Each report is a new directory under ``reports/``; the run's evidence is unchanged."""

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser(
            "report", help="write the acceptance report (report.md, report.json)"
        )
        add_run_options(parser)
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        store = open_store(args, environ)
        with store.lock():
            document = ReportBuilder(store, Ledger(store.events())).build()
            markdown = MarkdownReport(document).render()
            folder = store.save_report(
                {"report.json": json_bytes(document), "report.md": markdown.encode("utf-8")}
            )
            relative = folder.relative_to(store.run_dir).as_posix()
            store.append_event(
                "report-generated", {"folder": relative, "verdict": document["overall"]["verdict"]}
            )
        overall = document["overall"]
        say(f"Report written to {folder}/report.md and report.json")
        say(f"Overall: {overall['verdict']}. {overall['statement']}")
        for item in document["criteria"]:
            say(f"  {item['criterion']}: {item['verdict']} ({item['basis']})")
        if overall["verdict"] == "passed":
            return EXIT_OK
        return EXIT_FAILURES if overall["verdict"] == "failed" else EXIT_INCOMPLETE
