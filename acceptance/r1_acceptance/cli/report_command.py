"""``r1-acceptance report``: write the consolidated acceptance report."""

from __future__ import annotations

import argparse

from r1_acceptance.cli.utils import EXIT_OK, add_run_options, complain, ledger_for, open_store, say
from r1_acceptance.evidence.run_ledger import RunLedger
from r1_acceptance.evidence.utils import json_bytes
from r1_acceptance.report.markdown_report import MarkdownReport
from r1_acceptance.report.report_builder import ReportBuilder
from r1_acceptance.utils import sha256_file


class ReportCommand:
    """Write the run's report (``report.json`` and ``report.md``) into a new directory.

    Every report goes into its own new directory below the run's ``reports/``, so earlier
    reports are kept. The report can be written at any time; unfinished steps are reported as
    pending.
    """

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser(
            "report",
            help="write the consolidated report (JSON and Markdown)",
            description="Write the run's report, in JSON for machines and Markdown for "
            "people, into a new directory below the run's reports/.",
        )
        add_run_options(parser)
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace) -> int:
        """Build and save the report; return an exit code."""
        try:
            store = open_store(args)
            store.lock()
        except (LookupError, RuntimeError) as exc:
            return complain(str(exc))
        document = ReportBuilder(store, ledger_for(store)).build()
        markdown = MarkdownReport(document).render()
        directory = store.save_report(
            {
                "report.json": json_bytes(document),
                "report.md": markdown.encode("utf-8", "backslashreplace"),
            }
        )
        files = sorted(directory.iterdir())
        store.append_event(
            RunLedger.REPORT_GENERATED,
            {
                "directory": directory.relative_to(store.run_dir).as_posix(),
                "overall": document["overall"]["verdict"],
                "files": [
                    {"name": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
                    for path in files
                ],
            },
        )
        overall = document["overall"]
        say(
            f"Report written to {directory}:",
            *[f"    {path}" for path in files],
            f"Overall: {overall['verdict']}. {overall['summary']}",
        )
        return EXIT_OK
