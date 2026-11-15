"""Entry point of the ``r1-acceptance`` command."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from r1_acceptance.cli.init_command import InitCommand
from r1_acceptance.cli.record_command import RecordCommand
from r1_acceptance.cli.report_command import ReportCommand
from r1_acceptance.cli.run_command import RunCommand
from r1_acceptance.cli.status_command import StatusCommand
from r1_acceptance.cli.utils import EXIT_CODES_HELP, EXIT_INTERRUPTED, complain


def main(argv: Sequence[str] | None = None) -> int:
    """Parse *argv* (default: ``sys.argv``), run the chosen command, return its exit code."""
    parser = argparse.ArgumentParser(
        prog="r1-acceptance",
        description=(
            "Dual-sandbox acceptance harness for R1 (plans/R1.md section 16), run in the "
            "ChatGPT sandbox. Typical order: init; run p1 ... d9c (the output says which stage "
            "is next and what to do in the Claude sandbox and on the host first); record the "
            "manual checks; report. It never runs Docker or sbx, never changes network "
            "policies, and never starts or stops the Claude-side server."
        ),
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    InitCommand().configure(commands)
    RunCommand().configure(commands)
    RecordCommand().configure(commands)
    StatusCommand().configure(commands)
    ReportCommand().configure(commands)
    args = parser.parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except KeyboardInterrupt:
        complain("interrupted; run the same command again to resume")
        return EXIT_INTERRUPTED
