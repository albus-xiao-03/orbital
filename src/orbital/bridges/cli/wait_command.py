"""``orbital-bridge wait``: retrieve a task's result."""

from __future__ import annotations

import argparse
import os

from orbital.bridges.cli.utils import (
    add_client_options,
    build_client,
    exit_code_for,
    print_json,
    usage_error,
)


class WaitCommand:
    """Retrieve a task, waiting up to the wait budget (``0`` means a single poll)."""

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser(
            "wait",
            help="retrieve a task's result, waiting up to --max-wait",
            description="Print the task's current result, waiting until it settles or the "
            "wait budget runs out. Stopping waiting never cancels the task.",
        )
        parser.add_argument("task_id", metavar="TASK_ID", help="the task id printed by submit")
        parser.add_argument(
            "--max-wait",
            type=float,
            metavar="SECONDS",
            help="how long to wait; 0 polls once (default $ORBITAL_BRIDGE_MAX_WAIT or 1860)",
        )
        add_client_options(parser)
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace) -> int:
        try:
            client = build_client(args, os.environ)
            result = client.wait(args.task_id, max_wait_seconds=args.max_wait)
        except ValueError as exc:
            return usage_error(str(exc))
        print_json(result.to_dict())
        return exit_code_for(result.status)
