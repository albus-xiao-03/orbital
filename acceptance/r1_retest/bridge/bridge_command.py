"""Runs one `orbital-bridge` command so that its evidence survives any interruption."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from r1_retest.bridge.utils import child_environment, process_running, wrapper_argv
from r1_retest.evidence.evidence_store import EvidenceStore
from r1_retest.utils import format_time, parse_time, seconds_between, utc_now


@dataclass
class Execution:
    """How one command ended: ``exited``, ``harness-timeout``, ``lost`` or ``start-failed``."""

    outcome: str
    exit_code: int | None
    started_at: str
    finished_at: str
    duration_seconds: float | None
    stdout: str
    stderr: str
    exit_file: str
    recovered: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_file": self.exit_file,
            "recovered": self.recovered,
            "notes": list(self.notes),
        }


class BridgeCommand:
    """Starts `python -m orbital.bridges …` in its own session, with stdout, stderr and the exit
    status written straight into evidence files.

    Ctrl-C reaches only the harness. The first Ctrl-C is answered by waiting on (a submission's
    task id must not be lost); a second one leaves the command running, and running the stage
    again collects its result from the files (:meth:`recover`).
    """

    def __init__(
        self,
        store: EvidenceStore,
        orbital_src: Path,
        url: str,
        environ: Mapping[str, str],
        say: Callable[[str], None],
    ) -> None:
        self._store = store
        self._orbital_src = orbital_src
        self._url = url
        self._environ = environ
        self._say = say
        self._process: subprocess.Popen[bytes] | None = None

    def start(self, name: str, arguments: tuple[str, ...]) -> dict[str, Any]:
        """Create the evidence files and start the command.

        Returns what the ``command-started`` event records.
        """
        stdout_path, stdout_fd = self._store.new_artifact(f"{name}.stdout")
        stderr_path, stderr_fd = self._store.new_artifact(f"{name}.stderr")
        exit_path, exit_fd = self._store.new_artifact(f"{name}.exit")
        os.close(exit_fd)
        argv = wrapper_argv(self._store.run_dir / exit_path, sys.executable, arguments)
        started = utc_now()
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed argv: sh, this Python, orbital.bridges
                argv,
                stdin=subprocess.DEVNULL,
                stdout=stdout_fd,
                stderr=stderr_fd,
                env=child_environment(self._environ, self._orbital_src, self._url),
                start_new_session=True,
            )
            pid: int | None = process.pid
            self._process = process
            error = None
        except OSError as exc:
            pid, self._process, error = None, None, f"{type(exc).__name__}: {exc}"
        finally:
            os.close(stdout_fd)
            os.close(stderr_fd)
        return {
            "pid": pid,
            "started_at": format_time(started),
            "stdout": stdout_path,
            "stderr": stderr_path,
            "exit_file": exit_path,
            "start_error": error,
        }

    def wait(self, started: dict[str, Any], budget_seconds: float) -> Execution | None:
        """Wait for the command started by :meth:`start`; ``None`` if the operator abandons it."""
        if started["start_error"] is not None or self._process is None:
            return self._ended(started, "start-failed", None, [started["start_error"]])
        process = self._process
        deadline = time.monotonic() + budget_seconds
        interrupted = False
        while True:
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._stop_group(process)
                    return self._ended(
                        started,
                        "harness-timeout",
                        self._exit_code(started),
                        [
                            f"still running after the harness budget of {budget_seconds:g} s; "
                            "stopped"
                        ],
                    )
                code = process.wait(timeout=min(remaining, 0.5))
                return self._ended(
                    started, "exited", self._exit_code(started) if code is not None else None, []
                )
            except subprocess.TimeoutExpired:
                continue
            except KeyboardInterrupt:
                if interrupted:
                    self._say(
                        "Leaving the command running; its output still goes to the evidence "
                        "files. Run the same stage again to collect its result."
                    )
                    return None
                interrupted = True
                self._say(
                    "Ctrl-C: the command keeps running in its own session, so that its "
                    "result (and task id) is not lost. Waiting for it; press Ctrl-C again "
                    "to stop waiting."
                )

    def recover(self, started: dict[str, Any], budget_seconds: float) -> Execution | None:
        """Collect a command started by an earlier, interrupted harness invocation."""
        pid = started.get("pid")
        marker = str(self._store.run_dir / started["exit_file"])
        if isinstance(pid, int) and process_running(pid, marker):
            self._say(f"The command started earlier (pid {pid}) is still running; waiting for it.")
            deadline = time.monotonic() + budget_seconds
            try:
                while process_running(pid, marker) and time.monotonic() < deadline:
                    time.sleep(0.2)
            except KeyboardInterrupt:
                self._say("Stopped waiting; the command keeps running. Run the stage again later.")
                return None
            if process_running(pid, marker):
                return None
        code = self._exit_code(started)
        stdout = self._store.run_dir / started["stdout"]
        if code is None and (not stdout.exists() or stdout.stat().st_size == 0):
            return self._ended(
                started,
                "lost",
                None,
                ["recovered after an interruption: the command left no output and no exit status"],
                recovered=True,
            )
        notes = [
            "recovered after an interruption of the harness; the command itself ran to its end"
        ]
        if code is None:
            notes.append("the exit status was not recorded")
        return self._ended(started, "exited", code, notes, recovered=True)

    # ------------------------------------------------------------------------------ helpers

    def _exit_code(self, started: dict[str, Any]) -> int | None:
        try:
            text = (self._store.run_dir / started["exit_file"]).read_text().strip()
        except OSError:
            return None
        return int(text) if text.lstrip("-").isdigit() else None

    def _ended(
        self,
        started: dict[str, Any],
        outcome: str,
        code: int | None,
        notes: list[str],
        recovered: bool = False,
    ) -> Execution:
        finished = utc_now()
        begun = started["started_at"]
        duration = None if recovered else seconds_between(finished, parse_time(begun))
        return Execution(
            outcome,
            code,
            begun,
            format_time(finished),
            duration,
            started["stdout"],
            started["stderr"],
            started["exit_file"],
            recovered,
            notes,
        )

    @staticmethod
    def _stop_group(process: subprocess.Popen[bytes]) -> None:
        for signum, pause in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
            try:
                os.killpg(process.pid, signum)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=pause)
                return
            except subprocess.TimeoutExpired:
                continue
