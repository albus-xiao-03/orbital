"""``r1-retest claude-setup`` and ``guide``: text for the operator."""

from __future__ import annotations

import argparse
from collections.abc import Mapping

from r1_retest.cli.utils import EXIT_OK, guide_text, say
from r1_retest.procedure.retest_procedure import RetestProcedure


class InfoCommand:
    """Prints the Claude-side helper functions and the operator guide."""

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        setup = commands.add_parser(
            "claude-setup", help="print the helper functions for the Claude sandbox"
        )
        setup.set_defaults(handler=self.setup)
        guide = commands.add_parser("guide", help="print the operator guide")
        guide.set_defaults(handler=self.guide)

    def setup(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        say(RetestProcedure.CLAUDE_SETUP.rstrip())
        say("")
        say("# The server itself (server terminal), as in plans/R1.md §14 C:")
        say("# " + RetestProcedure.SERVER_COMMAND)
        return EXIT_OK

    def guide(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        say(guide_text().rstrip())
        return EXIT_OK
