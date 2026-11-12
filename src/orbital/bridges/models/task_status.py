"""Status of a delegated task, as reported by the bridge."""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """The closed set of states a delegated task can be reported in.

    Each value makes one precise claim about the Claude Code process:

    * ``running``: at the server's last report the process was executing; it may have
      finished since.
    * ``succeeded``: the process exited with status 0 and itself reported success. This is
      Claude Code's own report, not a check that the delegated objective was achieved.
    * ``failed``: the process ended without reporting success, could not be started, or the
      bridge failed while running it; in every case it is no longer running.
    * ``timed_out``: the process was still running at its execution deadline and the server
      terminated it and confirmed that it exited.
    * ``rejected``: the request was refused before execution.
    * ``communication_error``: no authoritative answer was obtained; the outcome is unknown.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    COMMUNICATION_ERROR = "communication_error"
    REJECTED = "rejected"

    @property
    def is_settled(self) -> bool:
        """``True`` when the outcome is settled: the task ended, or it was never executed.

        ``running`` is not settled, and neither is ``communication_error``, whose outcome is
        unknown.
        """
        return self in {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.REJECTED,
        }
