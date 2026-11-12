"""Supervision of one child process: stdin, bounded capture, deadline and confirmed termination."""

from __future__ import annotations

import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from orbital.bridges.executor.process_output import ProcessOutput
from orbital.bridges.executor.utils.process_runner import (
    descendants,
    drain_bounded,
    drain_tail,
    feed_stdin,
    has_exited,
    is_alive,
    kill_tracked,
    signal_group,
)


class ProcessRunner:
    """Runs one child process and guarantees it is gone before :meth:`run` returns.

    The child gets its own session (``start_new_session``), its stdin is fed by a writer
    thread, and stdout and stderr are drained by reader threads (stdout bounded, stderr keeping
    its tail). While it runs, its descendants are tracked through ``/proc`` because Claude Code
    runs tool processes in their own sessions, outside its process group.

    On the deadline or on :meth:`cancel` the whole tree is terminated (plan section 10):
    snapshot the descendants, ``SIGTERM`` the process group, wait a grace period, then
    ``SIGKILL`` the group and every tracked descendant still alive, reap the process and
    re-check the descendants. Only then are ``timed_out`` / ``cancelled`` reported.

    This relies on Linux ``/proc``. A runner serves a single :meth:`run`.
    """

    def __init__(
        self,
        *,
        stdout_limit: int = 32 * 1024 * 1024,
        stderr_limit: int = 64 * 1024,
        grace_seconds: float = 5.0,
        poll_seconds: float = 0.2,
        scan_seconds: float = 1.0,
        pipe_grace_seconds: float = 2.0,
        confirm_seconds: float = 2.0,
    ) -> None:
        self._stdout_limit = stdout_limit
        self._stderr_limit = stderr_limit
        self._grace = grace_seconds
        self._poll = poll_seconds
        self._scan = scan_seconds
        self._pipe_grace = pipe_grace_seconds
        self._confirm = confirm_seconds
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Ask the current (or imminent) :meth:`run` to terminate the process tree."""
        self._cancel.set()

    def run(
        self,
        argv: Sequence[str],
        *,
        stdin: bytes,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: float,
    ) -> ProcessOutput:
        """Run *argv* to completion, the deadline, or cancellation; never leave it running."""
        started = time.monotonic()
        if self._cancel.is_set():
            return ProcessOutput(None, b"", b"", 0.0, cancelled=True)
        try:
            # argv comes from the server configuration, never from a shell string or a prompt.
            process = subprocess.Popen(  # noqa: S603
                list(argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=dict(env),
                start_new_session=True,
                bufsize=0,
            )
        except OSError as exc:
            elapsed = time.monotonic() - started
            return ProcessOutput(
                None, b"", b"", elapsed, start_error=f"{type(exc).__name__}: {exc}"
            )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise RuntimeError("the child process pipes were not created")

        stdout = bytearray()
        stderr = bytearray()
        overflowed = threading.Event()
        writer = threading.Thread(target=feed_stdin, args=(process.stdin, stdin), daemon=True)
        readers = [
            threading.Thread(
                target=drain_bounded,
                args=(process.stdout, self._stdout_limit, stdout, overflowed),
                daemon=True,
            ),
            threading.Thread(
                target=drain_tail, args=(process.stderr, self._stderr_limit, stderr), daemon=True
            ),
        ]
        for thread in (writer, *readers):
            thread.start()

        tracked: dict[int, int] = {}
        timed_out = False
        cancelled = False
        unconfirmed: tuple[int, ...] = ()
        deadline = started + timeout_seconds
        next_scan = started
        try:
            while True:
                if time.monotonic() >= next_scan:
                    tracked.update(descendants(process.pid))
                    next_scan = time.monotonic() + self._scan
                try:
                    process.wait(timeout=self._poll)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if self._cancel.is_set():
                    cancelled = True
                elif time.monotonic() >= deadline:
                    timed_out = True
                else:
                    continue
                unconfirmed = self._terminate(process, tracked)
                break
        except BaseException:
            # Never leave the child running behind an unexpected error.
            self._terminate(process, tracked)
            raise

        pipe_deadline = time.monotonic() + self._pipe_grace
        for reader in readers:
            reader.join(max(0.0, pipe_deadline - time.monotonic()))
        return ProcessOutput(
            process.returncode,
            bytes(stdout),
            bytes(stderr),
            time.monotonic() - started,
            stdout_truncated=overflowed.is_set(),
            timed_out=timed_out,
            cancelled=cancelled,
            unconfirmed_pids=unconfirmed,
            pipes_held_open=any(reader.is_alive() for reader in readers),
        )

    def _terminate(
        self, process: subprocess.Popen[bytes], tracked: dict[int, int]
    ) -> tuple[int, ...]:
        """Terminate the whole tree and reap the process; return descendants still alive.

        The process is reaped only after every signal has been sent, so its process-group id
        stays reserved for the whole sequence. If it was already reaped, group signals are
        skipped and only tracked descendants (identified by start time) are signalled.
        """
        pid = process.pid
        reaped = process.returncode is not None
        tracked.update(descendants(pid))
        if not reaped:
            signal_group(pid, signal.SIGTERM)
            grace_deadline = time.monotonic() + self._grace
            while not has_exited(pid) and time.monotonic() < grace_deadline:
                time.sleep(0.05)
            tracked.update(descendants(pid))
            signal_group(pid, signal.SIGKILL)
        kill_tracked(tracked, signal.SIGKILL)
        process.wait()
        confirm_deadline = time.monotonic() + self._confirm
        while True:
            survivors = {pid: start for pid, start in tracked.items() if is_alive(pid, start)}
            if not survivors or time.monotonic() >= confirm_deadline:
                return tuple(sorted(survivors))
            kill_tracked(survivors, signal.SIGKILL)
            time.sleep(0.05)
