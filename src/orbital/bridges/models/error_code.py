"""Machine-readable error codes, each belonging to exactly one status category."""

from __future__ import annotations

from enum import StrEnum
from typing import assert_never

from orbital.bridges.models.task_status import TaskStatus


class ErrorCode(StrEnum):
    """Stable error codes. A result's error code must belong to the result's status.

    See :attr:`category` for the status each code belongs to.
    """

    # rejected: the request was refused before execution
    UNAUTHORIZED = "unauthorized"
    INVALID_REQUEST = "invalid_request"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    SERVER_BUSY = "server_busy"
    TASK_ID_CONFLICT = "task_id_conflict"
    # communication_error: no authoritative answer was obtained; the outcome is unknown
    CONNECTION_FAILED = "connection_failed"
    CONNECTION_INTERRUPTED = "connection_interrupted"
    REQUEST_TIMEOUT = "request_timeout"
    GATEWAY_ERROR = "gateway_error"
    NETWORK_POLICY_BLOCKED = "network_policy_blocked"
    UNVERIFIED_AUTH_REJECTION = "unverified_auth_rejection"
    RESPONSE_UNVERIFIED = "response_unverified"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN_TASK = "unknown_task"
    SERVER_ERROR = "server_error"
    # failed: the Claude Code process ended without reporting success, or never started
    CLAUDE_ERROR = "claude_error"
    EXECUTOR_FAILED = "executor_failed"
    EXECUTOR_UNAVAILABLE = "executor_unavailable"
    INVALID_EXECUTOR_OUTPUT = "invalid_executor_output"
    EXECUTION_CANCELLED = "execution_cancelled"
    INTERNAL_ERROR = "internal_error"
    # timed_out: the execution deadline was reached and termination was confirmed
    EXECUTION_TIMEOUT = "execution_timeout"
    # running: the client stopped waiting; the task was not confirmed finished
    WAIT_DEADLINE_REACHED = "wait_deadline_reached"

    @property
    def category(self) -> TaskStatus:
        """The status that a result carrying this code must have."""
        match self:
            case (
                ErrorCode.UNAUTHORIZED
                | ErrorCode.INVALID_REQUEST
                | ErrorCode.PAYLOAD_TOO_LARGE
                | ErrorCode.SERVER_BUSY
                | ErrorCode.TASK_ID_CONFLICT
            ):
                return TaskStatus.REJECTED
            case (
                ErrorCode.CONNECTION_FAILED
                | ErrorCode.CONNECTION_INTERRUPTED
                | ErrorCode.REQUEST_TIMEOUT
                | ErrorCode.GATEWAY_ERROR
                | ErrorCode.NETWORK_POLICY_BLOCKED
                | ErrorCode.UNVERIFIED_AUTH_REJECTION
                | ErrorCode.RESPONSE_UNVERIFIED
                | ErrorCode.INVALID_RESPONSE
                | ErrorCode.UNKNOWN_TASK
                | ErrorCode.SERVER_ERROR
            ):
                return TaskStatus.COMMUNICATION_ERROR
            case (
                ErrorCode.CLAUDE_ERROR
                | ErrorCode.EXECUTOR_FAILED
                | ErrorCode.EXECUTOR_UNAVAILABLE
                | ErrorCode.INVALID_EXECUTOR_OUTPUT
                | ErrorCode.EXECUTION_CANCELLED
                | ErrorCode.INTERNAL_ERROR
            ):
                return TaskStatus.FAILED
            case ErrorCode.EXECUTION_TIMEOUT:
                return TaskStatus.TIMED_OUT
            case ErrorCode.WAIT_DEADLINE_REACHED:
                return TaskStatus.RUNNING
            case _:
                assert_never(self)
