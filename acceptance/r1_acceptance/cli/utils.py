"""Static helpers of the command line: defaults, run selection, settings and output."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from r1_acceptance.bridge.bridge_cli import BridgeCli
from r1_acceptance.bridge.unsigned_probe import UnsignedProbe
from r1_acceptance.evidence.evidence_store import EvidenceStore
from r1_acceptance.evidence.run_ledger import RunLedger
from r1_acceptance.models.manual_check import ManualCheck
from r1_acceptance.procedure.r1_procedure import R1Procedure
from r1_acceptance.procedure.stage_runner import StageRunner
from r1_acceptance.procedure.utils import render
from r1_acceptance.utils import tree_digest

RESULTS_VARIABLE = "R1_ACCEPTANCE_RESULTS"
DEFAULT_RESULTS = "~/orbital-acceptance/r1-acceptance"
DEFAULT_URL = "http://host.docker.internal:8765"
DEFAULT_CLAUDE_WORKDIR = "~/orbital-acceptance/workdir"
DEFAULT_SERVE_LOG = "~/orbital-acceptance/serve.log"
EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_USAGE = 2
EXIT_INCOMPLETE = 3
EXIT_INTERRUPTED = 130
EXIT_CODES_HELP = """exit codes:
  0    done: every check that ran passed (manual checks may still be pending)
  1    something failed: see the output and the evidence
  2    refused or a usage error: nothing was sent to the bridge
  3    incomplete: run the same command again to continue (nothing is resubmitted)
  130  interrupted (Ctrl-C): run the same command again to resume"""


def harness_dir() -> Path:
    """The directory of the harness package (``acceptance/r1_acceptance``)."""
    return Path(__file__).resolve().parents[1]


def default_orbital_src() -> Path:
    """``src`` of the repository that contains the harness."""
    return harness_dir().parents[1] / "src"


def results_root(value: str | None) -> Path:
    """Where runs are kept: *value*, ``$R1_ACCEPTANCE_RESULTS`` or the default."""
    text = value or os.environ.get(RESULTS_VARIABLE) or DEFAULT_RESULTS
    return Path(text).expanduser().resolve()


def normalize_url(text: str) -> str:
    """*text* as ``http://host[:port]``; ``ValueError`` if it is not such a URL."""
    parts = urlsplit(text.strip())
    problem = (
        parts.scheme != "http"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    )
    if problem:
        raise ValueError(f"the bridge URL must look like http://host[:port], not {text!r}")
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    return f"http://{host}" + (f":{port}" if port is not None else "")


def add_run_options(parser: argparse.ArgumentParser) -> None:
    """``--results`` and ``--run``, which select the run a command works on."""
    parser.add_argument(
        "--results",
        metavar="DIR",
        help=f"where runs are kept (default ${RESULTS_VARIABLE} or {DEFAULT_RESULTS})",
    )
    parser.add_argument("--run", metavar="RUN_ID", help="the run to use (default: the latest)")


def open_store(args: argparse.Namespace) -> EvidenceStore:
    """The run selected by ``--results`` and ``--run``; ``LookupError`` if there is none."""
    return EvidenceStore.open(results_root(args.results), args.run)


def ledger_for(store: EvidenceStore) -> RunLedger:
    """The current state of *store*'s run."""
    return RunLedger(
        store.events(),
        steps=R1Procedure.STEPS,
        phases=R1Procedure.PHASES,
        checks=R1Procedure.MANUAL_CHECKS,
        stages=R1Procedure.STAGES,
    )


def runner_for(store: EvidenceStore) -> StageRunner:
    """A stage runner for *store*'s run, with the run's URL and orbital source."""
    orbital_src = Path(str(store.info["orbital"]["src"]))
    url = str(store.info["settings"]["url"])
    cli = BridgeCli(python=sys.executable, orbital_src=orbital_src, url=url, environ=os.environ)
    return StageRunner(
        store=store,
        cli=cli,
        probe=UnsignedProbe(url),
        orbital_src=orbital_src,
        harness_digest=tree_digest(harness_dir()),
        out=sys.stdout,
    )


def consistency(check: ManualCheck, observed: str, values: Mapping[str, str]) -> bool | None:
    """Whether *observed* matches the check's expectation (``None`` if that cannot be said)."""
    if not observed.strip():
        return None
    if check.expected_text is not None:
        return observed.strip() == check.expected_text
    if check.expected_fragments:
        return all(render(fragment, values) in observed for fragment in check.expected_fragments)
    return None


def say(*lines: str) -> None:
    """Print *lines* on stdout."""
    for line in lines:
        print(line, flush=True)


def complain(message: str) -> int:
    """Print *message* on stderr and return the usage exit code."""
    print(f"r1-acceptance: {message}", file=sys.stderr, flush=True)
    return EXIT_USAGE
