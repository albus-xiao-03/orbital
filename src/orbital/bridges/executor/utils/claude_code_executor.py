"""Helpers of ClaudeCodeExecutor: argv assembly, environment scrubbing, result interpretation."""

from __future__ import annotations

import json
import signal
from collections.abc import Mapping, Sequence
from typing import Any

from orbital.bridges.executor.process_output import ProcessOutput
from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.task_result import TaskResult

BRIDGE_PREFIX = "ORBITAL_BRIDGE_"
# Variables a Claude Code session exports to the processes it starts (observed in Phase F).
# They are removed so that every task runs as an independent Claude Code session, even when the
# bridge server itself was started from inside a Claude Code session.
SESSION_VARIABLES = frozenset(
    {
        "CLAUDECODE",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_EXECPATH",
        "CLAUDE_CODE_MESSAGING_SOCKET",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "CLAUDE_CODE_SESSION_ATTENDED",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_EFFORT",
        "CLAUDE_ENV_FILE",
        "CLAUDE_MODEL",
        "CLAUDE_PID",
        "CLAUDE_REASONING_EFFORT",
    }
)
EXCERPT_CHARS = 1000


def build_argv(claude_bin: str, claude_args: Sequence[str], session_id: str) -> list[str]:
    """``[claude_bin, *claude_args, -p, --output-format, json, --session-id, <id>]``.

    The fixed flags come last so that they take precedence over anything in *claude_args*.
    """
    return [claude_bin, *claude_args, "-p", "--output-format", "json", "--session-id", session_id]


def child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """*environ* without the bridge's own variables (including the key) and session variables."""
    return {
        name: value
        for name, value in environ.items()
        if not name.startswith(BRIDGE_PREFIX) and name not in SESSION_VARIABLES
    }


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """*text* with surrounding whitespace removed, cut to *limit* characters."""
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " ..."


def tail(raw: bytes, limit: int = EXCERPT_CHARS) -> str:
    """The last *limit* characters of *raw*, decoded leniently."""
    text = raw.decode("utf-8", errors="replace").strip()
    return text if len(text) <= limit else "... " + text[-limit:]


def exit_description(returncode: int | None) -> str:
    """How the process ended, for messages."""
    if returncode is None:
        return "did not start"
    if returncode < 0:
        try:
            return f"was killed by {signal.Signals(-returncode).name}"
        except ValueError:
            return f"was killed by signal {-returncode}"
    return f"exited with status {returncode}"


def result_object(stdout: bytes) -> dict[str, Any] | None:
    """The Claude Code result object printed on stdout, or ``None`` if stdout is not one."""
    try:
        document = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if isinstance(document, dict) and document.get("type") == "result":
        return document
    return None


def permission_denials(stdout: bytes) -> int:
    """How many permission denials Claude Code reported (for logging only)."""
    document = result_object(stdout)
    denials = None if document is None else document.get("permission_denials")
    return len(denials) if isinstance(denials, list) else 0


def describe_claude_error(document: Mapping[str, Any], returncode: int | None) -> str:
    """Message for a result object that does not report success."""
    details = [
        f"{key}={document[key]}"
        for key in ("terminal_reason", "api_error_status", "subtype")
        if document.get(key) is not None
    ]
    if document.get("is_error") is True:
        details.append("is_error=true")
    message = (
        f"Claude Code reported an error ({', '.join(details)}; it {exit_description(returncode)})"
    )
    text = document.get("result")
    if isinstance(text, str) and text.strip():
        message += f": {excerpt(text)}"
    errors = document.get("errors")
    if errors:
        message += f" Errors: {excerpt(json.dumps(errors, ensure_ascii=False))}"
    return message


def interpret(task_id: str, output: ProcessOutput, execution_timeout_seconds: int) -> TaskResult:
    """Turn a finished (and reaped) Claude Code run into a task result (plan section 10).

    Success requires exit status 0 **and** a result object with ``is_error: false``,
    ``subtype: "success"``, a string ``result`` and, when present, ``terminal_reason:
    "completed"``. Only ``result`` is relayed; every other field is ignored.
    """
    if output.start_error is not None:
        return TaskResult.from_error(
            task_id,
            ErrorCode.EXECUTOR_UNAVAILABLE,
            f"Claude Code could not be started: {output.start_error}",
        )
    unconfirmed = ""
    if output.unconfirmed_pids:
        pids = ", ".join(str(pid) for pid in output.unconfirmed_pids)
        unconfirmed = f" The termination of descendant process(es) {pids} could not be confirmed."
    if output.timed_out:
        return TaskResult.from_error(
            task_id,
            ErrorCode.EXECUTION_TIMEOUT,
            f"Claude Code did not finish within the execution timeout of "
            f"{execution_timeout_seconds} s; the bridge terminated its process tree and "
            f"confirmed that the process exited.{unconfirmed}",
        )
    if output.cancelled:
        return TaskResult.from_error(
            task_id,
            ErrorCode.EXECUTION_CANCELLED,
            f"Claude Code was stopped because the bridge server shut down; the process has "
            f"exited.{unconfirmed}",
        )
    returncode = output.returncode
    if output.stdout_truncated:
        return TaskResult.from_error(
            task_id,
            ErrorCode.INVALID_EXECUTOR_OUTPUT,
            f"Claude Code's output exceeded the capture limit, so its result cannot be "
            f"interpreted (it {exit_description(returncode)}).",
        )
    document = result_object(output.stdout)
    if document is None:
        if returncode != 0:
            return TaskResult.from_error(
                task_id,
                ErrorCode.EXECUTOR_FAILED,
                f"Claude Code {exit_description(returncode)} without a result object. "
                f"stderr: {tail(output.stderr_tail) or '(empty)'}",
            )
        return TaskResult.from_error(
            task_id,
            ErrorCode.INVALID_EXECUTOR_OUTPUT,
            f"Claude Code exited with status 0, but its output is not a Claude Code result "
            f"object: {excerpt(output.stdout.decode('utf-8', errors='replace')) or '(empty)'}",
        )
    is_error = document.get("is_error")
    subtype = document.get("subtype")
    text = document.get("result")
    terminal_reason = document.get("terminal_reason")
    if not isinstance(is_error, bool) or not isinstance(subtype, str):
        return TaskResult.from_error(
            task_id,
            ErrorCode.INVALID_EXECUTOR_OUTPUT,
            "Claude Code's result object lacks a boolean is_error or a string subtype.",
        )
    if (
        isinstance(text, str)
        and is_error is False
        and subtype == "success"
        and terminal_reason in (None, "completed")
    ):
        if returncode == 0:
            return TaskResult.succeeded(task_id, text)
        return TaskResult.from_error(
            task_id,
            ErrorCode.EXECUTOR_FAILED,
            f"Claude Code reported success but {exit_description(returncode)}; this is not "
            f"treated as success.",
        )
    return TaskResult.from_error(
        task_id, ErrorCode.CLAUDE_ERROR, describe_claude_error(document, returncode)
    )
