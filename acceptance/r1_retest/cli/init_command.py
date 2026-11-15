"""``r1-retest init``: create a uniquely named run and record what is under test."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from r1_retest.cli.utils import (
    EXIT_OK,
    EXIT_REFUSED,
    add_run_options,
    complain,
    environment_check,
    environment_facts,
    harness_identity,
    locate_previous_run,
    results_root,
    say,
)
from r1_retest.evidence.evidence_store import EvidenceStore
from r1_retest.procedure.retest_procedure import RetestProcedure
from r1_retest.utils import (
    DEFAULT_URL,
    EXPECTED_COMMIT,
    EXPECTED_SOURCE_DIGEST,
    MINIMUM_PYTHON,
    RUN_SCHEMA,
    format_time,
    read_git_commit,
    redact_url,
    tree_digest,
    utc_now,
)


class InitCommand:
    """Checks the source under test and the environment, then creates a new run directory."""

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        parser = commands.add_parser("init", help="start a new acceptance run")
        add_run_options(parser)
        parser.add_argument(
            "--url", help=f"bridge URL (default $ORBITAL_BRIDGE_URL or {DEFAULT_URL})"
        )
        parser.add_argument(
            "--orbital-src",
            help="the src directory of the repository copy (default $ORBITAL_SRC or ./src)",
        )
        parser.add_argument(
            "--previous-run", help="the earlier run's directory, to fingerprint it (read only)"
        )
        parser.add_argument(
            "--allow-source-mismatch",
            action="store_true",
            help="run although the source is not the fixed implementation (recorded)",
        )
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        if sys.version_info < MINIMUM_PYTHON:
            complain("Python 3.11 or newer is needed")
            return EXIT_REFUSED
        src = Path(args.orbital_src or environ.get("ORBITAL_SRC") or "src").expanduser().resolve()
        if not (src / "orbital" / "bridges" / "__init__.py").is_file():
            complain(f"no orbital.bridges under {src}; pass --orbital-src <repository copy>/src")
            return EXIT_REFUSED
        digest = tree_digest(src / "orbital")
        if digest != EXPECTED_SOURCE_DIGEST and not args.allow_source_mismatch:
            complain(
                f"the source under {src} is not the fixed implementation "
                f"(digest {digest}, expected {EXPECTED_SOURCE_DIGEST} "
                f"at commit {EXPECTED_COMMIT[:7]}). Update the repository copy, "
                "or pass --allow-source-mismatch to record a run anyway. Nothing was created."
            )
            return EXIT_REFUSED
        url = (args.url or environ.get("ORBITAL_BRIDGE_URL") or DEFAULT_URL).rstrip("/")
        facts = environment_facts(environ)
        info: dict[str, Any] = {
            "schema": RUN_SCHEMA,
            "created_at": format_time(utc_now()),
            "url": redact_url(url),
            "harness": harness_identity(),
            "orbital": {
                "src": str(src),
                "digest": digest,
                "commit": read_git_commit(src.parent),
                "expected_digest": EXPECTED_SOURCE_DIGEST,
                "expected_commit": EXPECTED_COMMIT,
                "mismatch_allowed": digest != EXPECTED_SOURCE_DIGEST,
            },
            "environment": facts,
            "previous_run": locate_previous_run(args.previous_run),
        }
        store = EvidenceStore.create(results_root(args, environ), info)
        with store.lock():
            check = environment_check(store, src, environ)
            store.append_event("environment-checked", check)
        say(f"Run {store.run_id} created at {store.run_dir}")
        commit = info["orbital"]["commit"] or "unknown"
        say(f"Source under test: {src} (digest {digest[:16]}…, commit {commit})")
        verdict = "passed" if check["passed"] else "FAILED"
        say(f"Environment check (public API and --help from that source): {verdict}")
        previous = info["previous_run"]
        say(
            f"Earlier run {previous['run_id']}: "
            + (
                "located and fingerprinted (read only)"
                if previous["found"]
                else "not found in this sandbox; referenced by id"
            )
        )
        if not facts["key_present"]:
            say(
                "Warning: ORBITAL_BRIDGE_KEY is not set in this shell; "
                "the stages refuse to run without it."
            )
        say("")
        say("Next, in the Claude sandbox (after updating it to the same commit):")
        for line in RetestProcedure.stage("a3").before:
            say("  " + RetestProcedure.render(line, None))
        say("Then here: r1-retest run a3")
        return EXIT_OK
