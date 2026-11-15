"""``r1-acceptance init``: start a new acceptance run."""

from __future__ import annotations

import argparse
import os
import platform
import socket
import sys
from pathlib import Path

from r1_acceptance.bridge.utils import URL_VARIABLE, ignored_variables, key_problem, proxy_settings
from r1_acceptance.cli.utils import (
    DEFAULT_CLAUDE_WORKDIR,
    DEFAULT_SERVE_LOG,
    DEFAULT_URL,
    complain,
    default_orbital_src,
    harness_dir,
    ledger_for,
    normalize_url,
    results_root,
    runner_for,
    say,
)
from r1_acceptance.evidence.evidence_store import EvidenceStore
from r1_acceptance.procedure.r1_procedure import R1Procedure
from r1_acceptance.procedure.utils import next_action_lines
from r1_acceptance.utils import (
    HARNESS_NAME,
    HARNESS_VERSION,
    RUN_SCHEMA,
    format_time,
    read_git_commit,
    tree_digest,
    utc_now,
)


class InitCommand:
    """Create a run directory, record the settings, and run the local preflight P-1.

    Nothing is sent to the bridge. The settings recorded here (URL, paths, the code under test)
    stay fixed for the whole run.
    """

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser(
            "init",
            help="start a new run and check this sandbox (no network traffic)",
            description="Start a new acceptance run in its own directory and run the local "
            "preflight P-1. Nothing is sent to the bridge.",
        )
        parser.add_argument(
            "--url",
            help=f"the bridge URL as seen from this sandbox (default ${URL_VARIABLE} or "
            f"{DEFAULT_URL})",
        )
        parser.add_argument(
            "--claude-workdir",
            default=DEFAULT_CLAUDE_WORKDIR,
            metavar="PATH",
            help="the server's --workdir in the Claude sandbox; D-5 checks that the same path "
            "holds no orbital-acceptance.txt in this sandbox (default %(default)s)",
        )
        parser.add_argument(
            "--serve-log",
            default=DEFAULT_SERVE_LOG,
            metavar="PATH",
            help="the server's log in the Claude sandbox, used in instructions (default "
            "%(default)s)",
        )
        parser.add_argument(
            "--orbital-src",
            metavar="DIR",
            help="the orbital source under test (default: src of this repository)",
        )
        parser.add_argument(
            "--new",
            action="store_true",
            help="start a new run although the latest one is not finished",
        )
        parser.add_argument("--results", metavar="DIR", help="where runs are kept")
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace) -> int:
        """Create the run and run P-1; return an exit code."""
        root = results_root(args.results)
        try:
            url = normalize_url(args.url or os.environ.get(URL_VARIABLE) or DEFAULT_URL)
        except ValueError as exc:
            return complain(str(exc))
        source = Path(args.orbital_src).expanduser() if args.orbital_src else default_orbital_src()
        orbital_src = source.resolve()
        if not (orbital_src / "orbital" / "bridges" / "__init__.py").is_file():
            return complain(f"no orbital source in {orbital_src}; pass --orbital-src")
        unfinished = self._unfinished(root)
        if unfinished is not None and not args.new:
            return complain(
                f"the latest run {unfinished} is not finished. Continue it (r1-acceptance "
                "status shows what is next), or start another run with: r1-acceptance init --new"
            )
        settings = {
            "url": url,
            "claude_workdir": args.claude_workdir,
            "serve_log": args.serve_log,
        }
        store = EvidenceStore.create(
            root,
            {
                "schema": RUN_SCHEMA,
                "created_at": format_time(utc_now()),
                "harness": {
                    "name": HARNESS_NAME,
                    "version": HARNESS_VERSION,
                    "path": str(harness_dir()),
                    "digest": tree_digest(harness_dir()),
                },
                "orbital": {
                    "src": str(orbital_src),
                    "digest": tree_digest(orbital_src / "orbital"),
                    "commit": read_git_commit(orbital_src.parent),
                },
                "settings": settings,
                "environment": {
                    "python": platform.python_version(),
                    "executable": sys.executable,
                    "platform": platform.platform(),
                    "hostname": socket.gethostname(),
                    "proxies": proxy_settings(os.environ),
                    "ignored_variables": ignored_variables(os.environ),
                },
                "results_root": str(root),
            },
        )
        store.lock()
        say(f"Created run {store.run_id} in {store.run_dir}")
        code = runner_for(store).run(R1Procedure.stage("p1"), invocation=sys.argv)
        problem = key_problem(os.environ, orbital_src)
        if problem is not None:
            say(f"Warning: {problem}. Every stage after P-1 needs it.")
        say("", *next_action_lines(ledger_for(store), settings))
        return code

    @staticmethod
    def _unfinished(root: Path) -> str | None:
        """The id of the latest run if some of its stages are not complete."""
        try:
            store = EvidenceStore.open(root)
        except LookupError:
            return None
        ledger = ledger_for(store)
        if all(ledger.stage_complete(stage.stage_id) for stage in R1Procedure.STAGES):
            return None
        return store.run_id
