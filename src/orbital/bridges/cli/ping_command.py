"""``orbital-bridge ping``: authenticated round trip to the server."""

from __future__ import annotations

import argparse
import os

from orbital.bridges.cli.utils import (
    EXIT_SUCCEEDED,
    add_client_options,
    build_client,
    exit_code_for,
    print_json,
    usage_error,
)


class PingCommand:
    """Check the network path and the shared key in both directions, without running a task."""

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser(
            "ping",
            help="authenticated round trip to the bridge server",
            description="Send one signed request and verify the signed reply. It does not run "
            'Claude. Prints {"ok": ..., "error": ...}.',
        )
        add_client_options(parser)
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace) -> int:
        try:
            error = build_client(args, os.environ).ping()
        except ValueError as exc:
            return usage_error(str(exc))
        print_json({"ok": error is None, "error": None if error is None else error.to_dict()})
        return EXIT_SUCCEEDED if error is None else exit_code_for(error.code.category)
