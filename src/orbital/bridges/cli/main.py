"""Entry point of the ``orbital-bridge`` command."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from orbital.bridges.cli.ping_command import PingCommand
from orbital.bridges.cli.serve_command import ServeCommand
from orbital.bridges.cli.submit_command import SubmitCommand
from orbital.bridges.cli.utils import EXIT_CODES_HELP
from orbital.bridges.cli.wait_command import WaitCommand


def main(argv: Sequence[str] | None = None) -> int:
    """Parse *argv* (default: ``sys.argv``), run the chosen command, return its exit code."""
    parser = argparse.ArgumentParser(
        prog="orbital-bridge",
        description=(
            "Network bridge that delegates tasks from a ChatGPT agent to Claude Code. Results "
            "are printed as one JSON object on stdout; logs go to stderr."
        ),
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    ServeCommand().configure(commands)
    SubmitCommand().configure(commands)
    WaitCommand().configure(commands)
    PingCommand().configure(commands)
    args = parser.parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    return handler(args)
