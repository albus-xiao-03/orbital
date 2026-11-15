"""The ``r1-retest`` command line."""

from __future__ import annotations

import argparse
import sys

from r1_retest.cli.info_command import InfoCommand
from r1_retest.cli.init_command import InitCommand
from r1_retest.cli.record_command import RecordCommand
from r1_retest.cli.report_command import ReportCommand
from r1_retest.cli.run_command import RunCommand
from r1_retest.cli.status_command import StatusCommand
from r1_retest.cli.utils import (
    EXIT_CODES_HELP,
    EXIT_INTERRUPTED,
    EXIT_REFUSED,
    complain,
    os_environ,
)
from r1_retest.utils import HARNESS_NAME, HARNESS_VERSION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=HARNESS_NAME,
        description="Temporary, semi-automated harness for the targeted R1 dual-sandbox re-test "
        "(A-3/D-2, A-2/D-7, A-1/D-9; optional A-4). It runs in the ChatGPT sandbox only.",
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"{HARNESS_NAME} {HARNESS_VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in (
        InitCommand(),
        RunCommand(),
        RecordCommand(),
        StatusCommand(),
        ReportCommand(),
        InfoCommand(),
    ):
        command.configure(commands)
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args, os_environ()))
    except KeyboardInterrupt:
        complain("interrupted; run the same command again to continue (no evidence is lost)")
        return EXIT_INTERRUPTED
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        complain(str(exc))
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
