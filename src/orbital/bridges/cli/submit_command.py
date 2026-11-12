"""``orbital-bridge submit``: delegate a prompt to Claude."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from orbital.bridges.cli.utils import (
    add_client_options,
    build_client,
    exit_code_for,
    print_json,
    usage_error,
)


class SubmitCommand:
    """Submit a prompt and wait for its result within the wait budget; print the result."""

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser(
            "submit",
            help="submit a prompt to Claude and wait for its result",
            description=(
                "Submit a prompt and print one JSON result. 'succeeded' means Claude Code "
                "reported that it finished; read the response to judge whether the task was "
                "really accomplished. 'running' means it has not finished (or the wait budget "
                "ran out): continue with 'orbital-bridge wait TASK_ID'."
            ),
        )
        parser.add_argument("prompt", nargs="?", metavar="PROMPT", help="the prompt; - reads stdin")
        parser.add_argument("--prompt-file", type=Path, metavar="PATH", help="read the prompt")
        parser.add_argument(
            "--execution-timeout",
            type=int,
            metavar="SECONDS",
            help="deadline the server enforces (default $ORBITAL_BRIDGE_EXECUTION_TIMEOUT or 1800)",
        )
        parser.add_argument(
            "--max-wait",
            type=float,
            metavar="SECONDS",
            help="how long this command waits; 0 returns straight after submitting "
            "(default: the execution timeout + 60)",
        )
        add_client_options(parser)
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace) -> int:
        if (args.prompt is None) == (args.prompt_file is None):
            return usage_error("give the prompt as PROMPT (- reads stdin) or with --prompt-file")
        try:
            if args.prompt_file is not None:
                prompt = args.prompt_file.read_text(encoding="utf-8")
            elif args.prompt == "-":
                prompt = sys.stdin.buffer.read().decode("utf-8")
            else:
                prompt = args.prompt
        except (OSError, UnicodeDecodeError) as exc:
            return usage_error(f"cannot read the prompt: {exc}")
        try:
            client = build_client(args, os.environ)
            result = client.run(
                prompt,
                execution_timeout_seconds=args.execution_timeout,
                max_wait_seconds=args.max_wait,
            )
        except ValueError as exc:
            return usage_error(str(exc))
        print_json(result.to_dict())
        return exit_code_for(result.status)
