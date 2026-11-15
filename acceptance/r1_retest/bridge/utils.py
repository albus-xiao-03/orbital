"""Static helpers for running `orbital-bridge` commands: environment, parsing, process checks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from r1_retest.utils import redact_url

KEY_VARIABLE = "ORBITAL_BRIDGE_KEY"
URL_VARIABLE = "ORBITAL_BRIDGE_URL"
PROXY_VARIABLES = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy")
CLI_MODULE = "orbital.bridges"
PUBLIC_API = (
    "BridgeClient",
    "BridgeServer",
    "ClientConfig",
    "ServerConfig",
    "TaskRequest",
    "TaskResult",
    "TaskStatus",
    "ErrorCode",
    "ErrorDetail",
    "SharedKey",
    "ClaudeCodeExecutor",
)


def child_environment(environ: Mapping[str, str], orbital_src: Path, url: str) -> dict[str, str]:
    """The environment of a bridge command: the caller's, with the run's URL and source.

    Other ``ORBITAL_BRIDGE_*`` settings (for example a different wait budget) are dropped, so
    that only the plan's command-line options shape the command. The key is passed through,
    never recorded.
    """
    env = {
        k: v for k, v in environ.items() if not k.startswith("ORBITAL_BRIDGE_") or k == KEY_VARIABLE
    }
    env[URL_VARIABLE] = url
    env["PYTHONPATH"] = str(orbital_src)
    env.pop("PYTHONHOME", None)
    return env


def ignored_variables(environ: Mapping[str, str]) -> list[str]:
    """Names (never values) of the ``ORBITAL_BRIDGE_*`` variables the harness drops."""
    return sorted(
        k
        for k in environ
        if k.startswith("ORBITAL_BRIDGE_") and k not in (KEY_VARIABLE, URL_VARIABLE)
    )


def proxy_settings(environ: Mapping[str, str]) -> dict[str, str]:
    return {k: redact_url(environ[k]) for k in PROXY_VARIABLES if k in environ}


def parse_json_output(data: bytes) -> dict[str, Any] | None:
    """The JSON object a bridge command printed on stdout, or ``None``."""
    text = data.decode("utf-8", "replace").strip()
    if not text:
        return None
    try:
        document = json.loads(text)
    except ValueError:
        start = text.rfind("\n{")
        if start < 0:
            return None
        try:
            document = json.loads(text[start + 1 :])
        except ValueError:
            return None
    return document if isinstance(document, dict) else None


def process_running(pid: int, marker: str) -> bool:
    """Whether *pid* is alive and is the process whose command line contains *marker*."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        cmdline = (
            Path(f"/proc/{pid}/cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode("utf-8", "replace")
        )
    except (OSError, IndexError):
        return False
    return state not in ("Z", "X") and marker in cmdline


def key_present(environ: Mapping[str, str]) -> bool:
    return bool(environ.get(KEY_VARIABLE, "").strip())


def wrapper_argv(exit_file: Path, python: str, arguments: tuple[str, ...]) -> list[str]:
    """``sh`` runs the bridge command, then writes its exit status to *exit_file*.

    The status therefore survives even if the harness itself is interrupted or killed while the
    command runs (the command is started in its own session and keeps running).
    """
    script = '"$@"; status=$?; printf "%s\\n" "$status" > "$0"'
    return ["/bin/sh", "-c", script, str(exit_file), python, "-m", CLI_MODULE, *arguments]
