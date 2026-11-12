"""Helpers of the CLI commands: exit codes, JSON output, logging and client construction."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, assert_never

from orbital.bridges.client.bridge_client import BridgeClient
from orbital.bridges.client.client_config import ClientConfig
from orbital.bridges.models.task_status import TaskStatus

EXIT_SUCCEEDED = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_TIMED_OUT = 3
EXIT_COMMUNICATION_ERROR = 4
EXIT_REJECTED = 5
EXIT_RUNNING = 6
EXIT_CODES_HELP = """exit codes (determined only by the printed status):
  0  succeeded (as reported by Claude Code), ping ok, or serve stopped cleanly
  1  failed
  2  usage or configuration error; no request is sent
  3  timed_out, confirmed by the Claude side
  4  communication_error: the outcome is unknown
  5  rejected
  6  running: not finished, or the wait budget ran out"""


def exit_code_for(status: TaskStatus) -> int:
    """The exit code that reports *status*."""
    match status:
        case TaskStatus.SUCCEEDED:
            return EXIT_SUCCEEDED
        case TaskStatus.FAILED:
            return EXIT_FAILED
        case TaskStatus.TIMED_OUT:
            return EXIT_TIMED_OUT
        case TaskStatus.COMMUNICATION_ERROR:
            return EXIT_COMMUNICATION_ERROR
        case TaskStatus.REJECTED:
            return EXIT_REJECTED
        case TaskStatus.RUNNING:
            return EXIT_RUNNING
        case _:
            assert_never(status)


def print_json(document: Mapping[str, Any]) -> None:
    """Print *document* as one line of JSON on stdout.

    Text is UTF-8; a lone surrogate (which UTF-8 cannot encode) is printed as its JSON
    ``\\uXXXX`` escape, so the output always stays valid JSON.
    """
    data = (json.dumps(document, ensure_ascii=False) + "\n").encode("utf-8", "backslashreplace")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(data.decode("utf-8"))
        sys.stdout.flush()
        return
    sys.stdout.flush()
    buffer.write(data)
    buffer.flush()


def usage_error(message: str) -> int:
    """Report a usage or configuration error on stderr and return its exit code."""
    print(f"orbital-bridge: error: {message}", file=sys.stderr)
    return EXIT_USAGE


def configure_logging(level: str) -> None:
    """Send log records at *level* and above to stderr."""
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def add_client_options(parser: argparse.ArgumentParser) -> None:
    """The options shared by the ChatGPT-side commands."""
    parser.add_argument(
        "--url", help="bridge server URL, http://host[:port] (default: $ORBITAL_BRIDGE_URL)"
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="connect directly instead of through $HTTP_PROXY (for loopback use)",
    )


def build_client(args: argparse.Namespace, env: Mapping[str, str]) -> BridgeClient:
    """A client from ``ORBITAL_BRIDGE_*`` variables and the command-line options.

    Raises ``ValueError`` for a missing or invalid setting, before any network traffic.
    """
    config = ClientConfig.from_env(env)
    changes: dict[str, Any] = {}
    if args.url is not None:
        changes["url"] = args.url
    if args.no_proxy:
        changes["use_env_proxy"] = False
    return BridgeClient(replace(config, **changes) if changes else config)
