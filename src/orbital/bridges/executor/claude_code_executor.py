"""Delegation of a task to Claude Code."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

from orbital.bridges.executor.process_runner import ProcessRunner
from orbital.bridges.executor.utils.claude_code_executor import (
    build_argv,
    child_environment,
    exit_description,
    interpret,
    permission_denials,
)
from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.task_request import TaskRequest
from orbital.bridges.models.task_result import TaskResult


class ClaudeCodeExecutor:
    """Runs ``claude -p --output-format json --session-id <task id>`` with the prompt on stdin.

    The prompt is passed to Claude Code unchanged and never interpreted; Claude Code performs
    the task. The outcome is reported as a :class:`TaskResult` only after the process has been
    reaped. The child environment excludes the bridge's own variables (including the key) and
    the session variables of any Claude Code session the server was started from.
    """

    def __init__(
        self,
        *,
        workdir: Path,
        claude_bin: str = "claude",
        claude_args: Sequence[str] = ("--permission-prompts", "none"),
        grace_seconds: float = 5.0,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._workdir = workdir
        self._claude_bin = claude_bin
        self._claude_args = tuple(claude_args)
        self._grace = grace_seconds
        self._environ = environ
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._current: ProcessRunner | None = None
        self._cancelled = False
        self._log = logging.getLogger("orbital.bridges.executor")

    def execute(self, request: TaskRequest) -> TaskResult:
        """Run Claude Code on *request* and return its outcome once the process is gone."""
        runner = ProcessRunner(grace_seconds=self._grace)
        with self._lock:
            if self._cancelled:
                return TaskResult.from_error(
                    request.task_id,
                    ErrorCode.EXECUTION_CANCELLED,
                    "The bridge server is shutting down; Claude Code was not started.",
                )
            self._current = runner
        try:
            output = runner.run(
                build_argv(self._claude_bin, self._claude_args, request.task_id),
                stdin=request.prompt.encode("utf-8"),
                cwd=self._workdir,
                env=child_environment(os.environ if self._environ is None else self._environ),
                timeout_seconds=request.execution_timeout_seconds,
            )
        finally:
            with self._lock:
                self._current = None
                self._idle.notify_all()
        self._log.info(
            "task %s: Claude Code %s after %.1f s; %d permission denial(s) reported",
            request.task_id,
            "timed out" if output.timed_out else exit_description(output.returncode),
            output.duration_seconds,
            permission_denials(output.stdout),
        )
        if output.pipes_held_open:
            self._log.warning(
                "task %s: a process started by Claude Code kept its output pipes open after it "
                "exited; the output captured until then is used",
                request.task_id,
            )
        return interpret(request.task_id, output, request.execution_timeout_seconds)

    def cancel(self) -> None:
        """Terminate the current run, if any, and refuse new ones (used at server shutdown)."""
        with self._lock:
            self._cancelled = True
            if self._current is not None:
                self._current.cancel()

    def terminate_running(self, timeout: float | None = None) -> bool:
        """Terminate the current run, if any, and wait until its process has been reaped.

        Returns ``True`` when no run is active any more.
        """
        with self._idle:
            if self._current is not None:
                self._current.cancel()
            return self._idle.wait_for(lambda: self._current is None, timeout)

    def version(self) -> str | None:
        """``claude --version`` (a local call that does not contact the API), or ``None``."""
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv from the server configuration
                [self._claude_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=child_environment(os.environ if self._environ is None else self._environ),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        lines = completed.stdout.strip().splitlines()
        return lines[0] if completed.returncode == 0 and lines else None
