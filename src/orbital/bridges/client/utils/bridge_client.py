"""Helpers of BridgeClient: mapping of verified replies to results, retry policy values, clock."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType

from orbital.bridges.auth.utils import PROTOCOL_VERSION
from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.error_detail import ErrorDetail
from orbital.bridges.models.task_result import TaskResult
from orbital.bridges.models.task_status import TaskStatus
from orbital.bridges.utils import SERVICE_NAME, decode_json_object

RETRYABLE_CODES = frozenset(
    {
        ErrorCode.CONNECTION_FAILED,
        ErrorCode.CONNECTION_INTERRUPTED,
        ErrorCode.REQUEST_TIMEOUT,
        ErrorCode.GATEWAY_ERROR,
    }
)
SERVER_REPORTED_STATUSES = frozenset(
    {TaskStatus.RUNNING, TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.TIMED_OUT}
)
# The error codes the bridge server can send with each HTTP status (plan section 8).
SERVER_ERROR_CODES = MappingProxyType(
    {
        400: frozenset({ErrorCode.INVALID_REQUEST}),
        401: frozenset({ErrorCode.UNAUTHORIZED}),
        404: frozenset({ErrorCode.UNKNOWN_TASK, ErrorCode.INVALID_REQUEST}),
        405: frozenset({ErrorCode.INVALID_REQUEST}),
        409: frozenset({ErrorCode.SERVER_BUSY, ErrorCode.TASK_ID_CONFLICT}),
        411: frozenset({ErrorCode.INVALID_REQUEST}),
        413: frozenset({ErrorCode.PAYLOAD_TOO_LARGE}),
        500: frozenset({ErrorCode.SERVER_ERROR}),
    }
)
POST_RECORD_STATUSES = frozenset({200, 202})
GET_RECORD_STATUSES = frozenset({200})
MAX_BACKOFF_SECONDS = 30.0


def backoff_seconds(consecutive_failures: int) -> float:
    """Delay before the next retry: 1, 2, 4, 8, 16 s ... capped at 30 s."""
    return min(2.0 ** (consecutive_failures - 1), MAX_BACKOFF_SECONDS)


def utc_now_text() -> str:
    """The current time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def error_from_reply(status: int, body: bytes, task_id: str | None) -> ErrorDetail | str:
    """The error of a **verified** 4xx/5xx reply, or a description of why the reply is invalid.

    The body's code must be one the server can send with that status, and a task id it names
    must be the one asked about.
    """
    allowed = SERVER_ERROR_CODES.get(status)
    if allowed is None:
        return f"The bridge answered with an unexpected HTTP status {status}."
    try:
        document = decode_json_object(body)
        if set(document) != {"error", "task_id"}:
            raise ValueError("the error body must have exactly the keys error and task_id")
        detail = ErrorDetail.from_dict(document["error"])
    except ValueError as exc:
        return f"The bridge's HTTP {status} reply is not a valid error body ({exc})."
    named = document["task_id"]
    if named is not None and (not isinstance(named, str) or (task_id and named != task_id)):
        return f"The bridge's HTTP {status} reply names another task ({named!r})."
    if detail.code not in allowed:
        return f"The bridge's HTTP {status} reply carries the unexpected code {detail.code.value}."
    return detail


def result_from_reply(
    task_id: str, status: int, body: bytes, record_statuses: frozenset[int]
) -> TaskResult:
    """Map a **verified** reply to a result for *task_id* (plan section 11)."""
    if status in record_statuses:
        try:
            result = TaskResult.from_dict(decode_json_object(body))
        except ValueError as exc:
            return TaskResult.from_error(
                task_id,
                ErrorCode.INVALID_RESPONSE,
                f"The bridge's HTTP {status} reply is not a valid task record ({exc}).",
            )
        if result.task_id != task_id:
            return TaskResult.from_error(
                task_id,
                ErrorCode.INVALID_RESPONSE,
                f"The bridge's reply carries task id {result.task_id} instead of {task_id}.",
            )
        if result.status not in SERVER_REPORTED_STATUSES or (
            result.status is TaskStatus.RUNNING and result.error is not None
        ):
            return TaskResult.from_error(
                task_id,
                ErrorCode.INVALID_RESPONSE,
                f"The bridge's reply has a status the server never reports ({result.status}).",
            )
        return result
    detail = error_from_reply(status, body, task_id)
    if isinstance(detail, str):
        return TaskResult.from_error(task_id, ErrorCode.INVALID_RESPONSE, detail)
    return TaskResult.from_error(task_id, detail.code, detail.message)


def health_problem(status: int, body: bytes) -> ErrorDetail | None:
    """``None`` for a verified, well-formed health reply; otherwise what is wrong with it."""
    if status == 200:
        try:
            document = decode_json_object(body)
        except ValueError as exc:
            return ErrorDetail(ErrorCode.INVALID_RESPONSE, f"Invalid health reply ({exc}).")
        if document == {"service": SERVICE_NAME, "protocol_version": PROTOCOL_VERSION}:
            return None
        return ErrorDetail(ErrorCode.INVALID_RESPONSE, f"Unexpected health reply: {document!r}.")
    detail = error_from_reply(status, body, None)
    return ErrorDetail(ErrorCode.INVALID_RESPONSE, detail) if isinstance(detail, str) else detail
