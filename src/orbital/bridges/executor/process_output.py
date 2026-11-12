"""What one supervised child process produced, and how it ended."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessOutput:
    """Outcome of :meth:`ProcessRunner.run`.

    * ``returncode`` is ``None`` only if the process could not be started (see
      ``start_error``); a negative value means it was killed by that signal.
    * ``stdout`` holds at most the runner's capture limit; ``stdout_truncated`` says whether
      more was written. ``stderr_tail`` keeps only the last bytes of stderr.
    * ``timed_out`` and ``cancelled`` are set only after the process was terminated **and**
      reaped. ``unconfirmed_pids`` lists descendants whose termination could not be confirmed.
    * ``pipes_held_open`` is set when, after a normal exit, a descendant kept the output pipes
      open; the output captured until then is returned.
    """

    returncode: int | None
    stdout: bytes
    stderr_tail: bytes
    duration_seconds: float
    stdout_truncated: bool = False
    timed_out: bool = False
    cancelled: bool = False
    start_error: str | None = None
    unconfirmed_pids: tuple[int, ...] = ()
    pipes_held_open: bool = False
