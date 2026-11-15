"""Static helpers of the command line: paths, input, identity and environment facts."""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any

from r1_retest.bridge.utils import ignored_variables, key_present, proxy_settings
from r1_retest.evidence.evidence_store import EvidenceStore
from r1_retest.evidence.utils import MAX_IMPORT_BYTES
from r1_retest.utils import (
    DEFAULT_PREVIOUS_RESULTS,
    DEFAULT_RESULTS,
    HARNESS_NAME,
    HARNESS_VERSION,
    PREVIOUS_RUN_ID,
    RESULTS_ENV,
    sha256_file,
    tree_digest,
)

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_REFUSED = 2
EXIT_INCOMPLETE = 3
EXIT_INTERRUPTED = 130
EXIT_CODES_HELP = """exit codes:
  0    done; everything it ran or recorded passed
  1    it ran, and something failed (see the output and r1-retest status)
  2    refused or a usage error; nothing was sent
  3    incomplete: a confirmation (--ready), a decision or more evidence is needed
  130  interrupted (Ctrl-C); run the same command again to continue"""


def say(text: str = "") -> None:
    print(text, flush=True)


def complain(text: str) -> None:
    print(f"r1-retest: {text}", file=sys.stderr, flush=True)


def results_root(args: argparse.Namespace, environ: Mapping[str, str]) -> Path:
    chosen = args.results or environ.get(RESULTS_ENV) or DEFAULT_RESULTS
    return Path(chosen).expanduser().resolve()


def open_store(args: argparse.Namespace, environ: Mapping[str, str]) -> EvidenceStore:
    return EvidenceStore.open(results_root(args, environ), args.run)


def read_input(path: str | None) -> bytes:
    """The text to import: from *path*, or pasted on stdin (ended with Ctrl-D)."""
    if path is not None:
        data = Path(path).expanduser().read_bytes()
    else:
        if sys.stdin.isatty():
            say("Paste the output now, then press Ctrl-D on a new line:")
        data = sys.stdin.buffer.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise ValueError(f"more than {MAX_IMPORT_BYTES} bytes; attach a smaller excerpt")
    return data


def harness_identity() -> dict[str, Any]:
    """Which harness build runs: the .pyz archive's SHA-256, or the source tree's digest."""
    package = Path(__file__).resolve().parents[1]
    archive = next((p for p in package.parents if p.is_file()), None)  # inside a .pyz archive
    identity: dict[str, Any] = {"name": HARNESS_NAME, "version": HARNESS_VERSION}
    if archive is not None:
        identity.update(form="pyz", path=str(archive), sha256=sha256_file(archive))
    else:
        identity.update(form="source", path=str(package), sha256=tree_digest(package))
    try:
        identity["build"] = json.loads(
            resources.files("r1_retest").joinpath("BUILD.json").read_text()
        )
    except (FileNotFoundError, OSError, ValueError):
        identity["build"] = None
    return identity


def environment_facts(environ: Mapping[str, str]) -> dict[str, Any]:
    """Non-secret facts about this sandbox (never the key: only whether it is set)."""
    return {
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "proxies": proxy_settings(environ),
        "ignored_variables": ignored_variables(environ),
        "key_present": key_present(environ),
    }


def locate_previous_run(path: str | None) -> dict[str, Any]:
    """The earlier run's directory in this sandbox, fingerprinted read-only, if it is here."""
    chosen = (
        Path(path).expanduser()
        if path
        else Path(DEFAULT_PREVIOUS_RESULTS).expanduser() / PREVIOUS_RUN_ID
    )
    found: dict[str, Any] = {
        "run_id": PREVIOUS_RUN_ID,
        "path": str(chosen),
        "found": chosen.is_dir(),
    }
    if not chosen.is_dir():
        return found
    reports = (
        sorted((chosen / "reports").glob("*/report.json")) if (chosen / "reports").is_dir() else []
    )
    if reports:
        latest = reports[-1]
        found.update(report=str(latest), report_sha256=sha256_file(latest))
        markdown = latest.with_name("report.md")
        if markdown.is_file():
            found.update(report_md=str(markdown), report_md_sha256=sha256_file(markdown))
        try:
            document = json.loads(latest.read_text(encoding="utf-8"))
            found["step_verdicts"] = {
                s.get("step_id"): s.get("verdict") for s in document.get("steps", [])
            }
        except (OSError, ValueError, AttributeError):
            found["step_verdicts"] = None
    return found


def environment_check(
    store: EvidenceStore, orbital_src: Path, environ: Mapping[str, str]
) -> dict[str, Any]:
    """Import the public API and run ``--help`` from the source under test (no network)."""
    env = {k: v for k, v in environ.items() if not k.startswith("ORBITAL_BRIDGE_")}
    env["PYTHONPATH"] = str(orbital_src)
    code = (
        "import json, orbital.bridges as b; "
        "print(json.dumps({'file': b.__file__, 'names': sorted(b.__all__)}))"
    )
    imported = subprocess.run(  # noqa: S603 - fixed argv: this Python and a constant snippet
        [sys.executable, "-c", code], capture_output=True, env=env, timeout=60, check=False
    )
    helped = subprocess.run(
        [sys.executable, "-m", "orbital.bridges", "--help"],
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    files = {
        "import_stdout": store.write_file(
            "artifacts", "environment-import.stdout", imported.stdout
        ),
        "import_stderr": store.write_file(
            "artifacts", "environment-import.stderr", imported.stderr
        ),
        "help_stdout": store.write_file("artifacts", "environment-help.stdout", helped.stdout),
        "help_stderr": store.write_file("artifacts", "environment-help.stderr", helped.stderr),
    }
    try:
        names = json.loads(imported.stdout)["names"]
        module_file = json.loads(imported.stdout)["file"]
    except (ValueError, KeyError):
        names, module_file = [], None
    help_text = helped.stdout.decode("utf-8", "replace")
    commands_listed = all(c in help_text for c in ("serve", "submit", "wait", "ping"))
    from_src = module_file is not None and Path(module_file).resolve().is_relative_to(
        orbital_src.resolve()
    )
    passed = (
        imported.returncode == 0
        and len(names) == 11
        and helped.returncode == 0
        and commands_listed
        and from_src
    )
    return {
        "passed": passed,
        "public_names": names,
        "module_file": module_file,
        "from_source_under_test": from_src,
        "help_exit": helped.returncode,
        "commands_listed": commands_listed,
        "files": files,
    }


def guide_text() -> str:
    return resources.files("r1_retest").joinpath("GUIDE.md").read_text(encoding="utf-8")


def add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--results", help=f"results directory (default ${RESULTS_ENV} or {DEFAULT_RESULTS})"
    )
    parser.add_argument("--run", help="run id (default: the latest run)")


def os_environ() -> Mapping[str, str]:
    return os.environ
