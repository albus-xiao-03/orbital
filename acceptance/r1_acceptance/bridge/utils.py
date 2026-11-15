"""Static helpers of the bridge runners: child environment, output parsing, the code under test."""

from __future__ import annotations

import importlib
import json
import shlex
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

from r1_acceptance.utils import redact_url

PROGRAM = "orbital-bridge"
CLI_MODULE = "orbital.bridges"
BRIDGE_PREFIX = "ORBITAL_BRIDGE_"
KEY_VARIABLE = "ORBITAL_BRIDGE_KEY"
URL_VARIABLE = "ORBITAL_BRIDGE_URL"
ALLOWED_COMMANDS = frozenset({"ping", "submit", "wait", "--help"})
PROXY_VARIABLES = (
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
)
PUBLIC_API = (
    "BridgeClient",
    "BridgeServer",
    "ClaudeCodeExecutor",
    "ClientConfig",
    "ErrorCode",
    "ErrorDetail",
    "ServerConfig",
    "SharedKey",
    "TaskRequest",
    "TaskResult",
    "TaskStatus",
)
CLI_COMMANDS = ("serve", "submit", "wait", "ping")


def child_environment(
    environ: Mapping[str, str], *, orbital_src: Path, url: str, key: str | None
) -> dict[str, str]:
    """The environment of an ``orbital-bridge`` child process.

    Every ``ORBITAL_BRIDGE_*`` setting of the operator's shell is dropped, so that each command
    runs with the procedure's own options and the client's defaults. Only the operator's key
    (or the deliberately wrong *key*) and the run's URL are set. ``PYTHONPATH`` points at the
    ``orbital`` source under test. Proxy settings pass through unchanged.
    """
    env = {name: value for name, value in environ.items() if not name.startswith(BRIDGE_PREFIX)}
    secret = key if key is not None else environ.get(KEY_VARIABLE)
    if secret is not None:
        env[KEY_VARIABLE] = secret
    env[URL_VARIABLE] = url
    env["PYTHONPATH"] = str(orbital_src)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def ignored_variables(environ: Mapping[str, str]) -> list[str]:
    """The ``ORBITAL_BRIDGE_*`` variables that the harness does not pass on (names only)."""
    return sorted(
        name
        for name in environ
        if name.startswith(BRIDGE_PREFIX) and name not in (KEY_VARIABLE, URL_VARIABLE)
    )


def proxy_settings(environ: Mapping[str, str]) -> dict[str, str]:
    """The proxy variables of *environ*, with any user information removed from proxy URLs."""
    settings: dict[str, str] = {}
    for name in PROXY_VARIABLES:
        if name in environ:
            value = environ[name]
            settings[name] = value if name.lower() == "no_proxy" else redact_url(value)
    return settings


def parse_json_object(data: bytes) -> tuple[dict[str, Any] | None, str | None]:
    """The JSON object printed on stdout, or ``None`` and why it could not be read."""
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return None, "nothing was printed on stdout"
    try:
        document = json.loads(text)
    except ValueError as exc:
        return None, f"stdout is not JSON ({exc})"
    if not isinstance(document, dict):
        return None, "stdout is not a JSON object"
    return document, None


def display_command(arguments: Sequence[str]) -> str:
    """The command line as the operator would type it."""
    return shlex.join([PROGRAM, *arguments])


def import_bridges(orbital_src: Path) -> ModuleType:
    """Import ``orbital.bridges`` from *orbital_src* (placed first on ``sys.path``)."""
    source = str(orbital_src)
    if source not in sys.path:
        sys.path.insert(0, source)
    return importlib.import_module(CLI_MODULE)


def key_problem(environ: Mapping[str, str], orbital_src: Path) -> str | None:
    """Why ``ORBITAL_BRIDGE_KEY`` is unusable, or ``None`` if the package accepts it.

    The key is checked with ``orbital.bridges.SharedKey``; its value is never shown or kept.
    """
    text = environ.get(KEY_VARIABLE)
    if not text:
        return f"{KEY_VARIABLE} is not set in this shell (export the same key as the Claude side)"
    try:
        import_bridges(orbital_src).SharedKey.from_text(text)
    except ValueError as exc:
        return f"{KEY_VARIABLE} is not a valid key: {exc}"
    except Exception as exc:  # any import failure is reported, not raised
        return f"orbital.bridges could not be imported from {orbital_src}: {exc}"
    return None
