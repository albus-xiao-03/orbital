"""``orbital-bridge serve``: the Claude-side server."""

from __future__ import annotations

import argparse
import logging
import shutil
import signal
from dataclasses import replace
from pathlib import Path
from typing import Any

from orbital.bridges.cli.utils import EXIT_SUCCEEDED, configure_logging, usage_error
from orbital.bridges.server.bridge_server import BridgeServer
from orbital.bridges.server.server_config import ServerConfig


class ServeCommand:
    """Run the bridge server until ``SIGINT`` or ``SIGTERM`` (a graceful stop)."""

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser(
            "serve",
            help="run the Claude-side bridge server",
            description=(
                "Run the bridge server that hands each authenticated task to Claude Code. "
                "Settings come from ORBITAL_BRIDGE_* variables (the key only from "
                "ORBITAL_BRIDGE_KEY); options override them. Stop it with Ctrl-C or SIGTERM: "
                "the running task, if any, is terminated and reaped."
            ),
        )
        parser.add_argument("--host", help="bind address (default 0.0.0.0)")
        parser.add_argument("--port", type=int, help="bind port (default 8765)")
        parser.add_argument("--workdir", type=Path, help="working directory for Claude Code")
        parser.add_argument("--claude-bin", help="Claude Code executable (default claude)")
        parser.add_argument(
            "--claude-arg",
            action="append",
            dest="claude_args",
            metavar="ARG",
            help="extra Claude Code argument; repeatable; replaces the default "
            "'--permission-prompts none' (write --claude-arg=--flag for values starting with -)",
        )
        parser.add_argument(
            "--max-execution-timeout",
            type=int,
            metavar="SECONDS",
            help="largest accepted execution timeout (default 14400)",
        )
        parser.add_argument(
            "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
        )
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace) -> int:
        configure_logging(args.log_level)
        log = logging.getLogger("orbital.bridges.cli")
        options = {
            "host": args.host,
            "port": args.port,
            "workdir": args.workdir,
            "claude_bin": args.claude_bin,
            "claude_args": None if args.claude_args is None else tuple(args.claude_args),
            "max_execution_timeout_seconds": args.max_execution_timeout,
        }
        try:
            config = ServerConfig.from_env()
            config = replace(config, **{k: v for k, v in options.items() if v is not None})
            config = replace(config, workdir=config.workdir.expanduser().resolve())
        except ValueError as exc:
            return usage_error(str(exc))
        if not config.workdir.is_dir():
            return usage_error(f"the workdir {config.workdir} does not exist or is not a directory")
        if shutil.which(config.claude_bin) is None:
            return usage_error(f"the Claude Code executable {config.claude_bin!r} was not found")
        try:
            server = BridgeServer(config)
        except OSError as exc:
            return usage_error(f"cannot listen on {config.host}:{config.port}: {exc}")
        log.info(
            "listening on %s:%d; workdir %s; Claude Code %s (%s)",
            config.host,
            server.port,
            config.workdir,
            config.claude_bin,
            server.executor.version() or "version unknown",
        )

        def interrupt(signum: int, frame: Any) -> None:
            raise KeyboardInterrupt

        previous = signal.signal(signal.SIGTERM, interrupt)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log.info("stopping; the running task, if any, is terminated and reaped")
        finally:
            # Do not let a second signal interrupt the graceful stop.
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            server.stop()
            signal.signal(signal.SIGTERM, previous)
            signal.signal(signal.SIGINT, signal.default_int_handler)
        log.info("stopped")
        return EXIT_SUCCEEDED
