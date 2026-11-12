"""The ChatGPT-side API of the bridge."""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from orbital.bridges.client.client_config import ClientConfig
from orbital.bridges.client.http_transport import HttpTransport
from orbital.bridges.client.utils.bridge_client import (
    GET_RECORD_STATUSES,
    POST_RECORD_STATUSES,
    RETRYABLE_CODES,
    backoff_seconds,
    health_problem,
    result_from_reply,
    utc_now_text,
)
from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.error_detail import ErrorDetail
from orbital.bridges.models.task_request import TaskRequest
from orbital.bridges.models.task_result import TaskResult
from orbital.bridges.models.task_status import TaskStatus
from orbital.bridges.models.utils import is_task_id, new_task_id
from orbital.bridges.utils import HEALTH_PATH, TASKS_PATH, encode_json, task_path


class BridgeClient:
    """Submits prompts to the bridge server and retrieves structured results.

    These methods never raise for task or communication outcomes: every outcome is a
    :class:`TaskResult` (or, for :meth:`ping`, an :class:`ErrorDetail`). They raise
    ``ValueError`` only for invalid arguments.

    Two time limits are kept apart (plan section 7): the *execution timeout* is sent with the
    task and enforced only by the server, which alone reports ``timed_out``; the *wait budget*
    is how long one call waits. When the budget runs out the client returns ``running`` with
    ``wait_deadline_reached``; stopping waiting never cancels the task.
    """

    def __init__(
        self,
        config: ClientConfig,
        *,
        transport: HttpTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._transport = transport if transport is not None else HttpTransport(config)
        self._clock = clock
        self._sleep = sleep

    def submit(self, prompt: str, *, execution_timeout_seconds: int | None = None) -> TaskResult:
        """Submit *prompt* under a new task id; return ``running`` or a failure."""
        timeout = (
            self._config.execution_timeout_seconds
            if execution_timeout_seconds is None
            else execution_timeout_seconds
        )
        request = TaskRequest(new_task_id(), prompt, timeout)
        body = encode_json(request.to_dict())
        if len(body) > self._config.max_request_bytes:
            return TaskResult.from_error(
                request.task_id,
                ErrorCode.PAYLOAD_TOO_LARGE,
                f"The request is {len(body)} bytes, over the {self._config.max_request_bytes}-"
                f"byte limit; it was not sent.",
            )
        reply = self._exchange("POST", TASKS_PATH, body, deadline=None)
        if isinstance(reply, ErrorDetail):
            return TaskResult.from_error(
                request.task_id,
                reply.code,
                f"{reply.message} The submission was not confirmed: the task may or may not have "
                f"been accepted. Check with: orbital-bridge wait {request.task_id} --max-wait 0",
            )
        return result_from_reply(request.task_id, *reply, POST_RECORD_STATUSES)

    def wait(self, task_id: str, *, max_wait_seconds: float | None = None) -> TaskResult:
        """Retrieve *task_id*, waiting up to the budget (``0`` means a single poll)."""
        if not is_task_id(task_id):
            raise ValueError("task_id must be a canonical, lowercase UUID version 4")
        budget = self._budget(max_wait_seconds, None)
        return self._poll(task_id, budget, poll_first=True)

    def run(
        self,
        prompt: str,
        *,
        execution_timeout_seconds: int | None = None,
        max_wait_seconds: float | None = None,
    ) -> TaskResult:
        """Submit *prompt*, then wait for its result within the budget."""
        budget = self._budget(max_wait_seconds, execution_timeout_seconds)
        submitted = self.submit(prompt, execution_timeout_seconds=execution_timeout_seconds)
        if submitted.status is not TaskStatus.RUNNING or budget == 0:
            return submitted
        return self._poll(submitted.task_id, budget, poll_first=False)

    def ping(self) -> ErrorDetail | None:
        """One authenticated round trip: ``None`` if the server answered and verified."""
        reply = self._transport.exchange("GET", HEALTH_PATH)
        if isinstance(reply, ErrorDetail):
            return reply
        return health_problem(*reply)

    def _budget(self, max_wait_seconds: float | None, execution_timeout: int | None) -> float:
        if max_wait_seconds is None:
            return self._config.wait_budget(execution_timeout)
        if (
            isinstance(max_wait_seconds, bool)
            or not isinstance(max_wait_seconds, int | float)
            or not math.isfinite(max_wait_seconds)
            or max_wait_seconds < 0
        ):
            raise ValueError("max_wait_seconds must be a non-negative number")
        return float(max_wait_seconds)

    def _exchange(
        self, method: str, path: str, body: bytes = b"", *, deadline: float | None
    ) -> tuple[int, bytes] | ErrorDetail:
        """One exchange, retrying transient failures with exponential backoff.

        At most ``max_retries`` retries follow consecutive transient failures, and none would
        start after *deadline*.
        """
        failures = 0
        while True:
            reply = self._transport.exchange(method, path, body)
            if not isinstance(reply, ErrorDetail) or reply.code not in RETRYABLE_CODES:
                return reply
            failures += 1
            delay = backoff_seconds(failures)
            if failures > self._config.max_retries or (
                deadline is not None and self._clock() + delay > deadline
            ):
                return reply
            self._sleep(delay)

    def _poll(self, task_id: str, budget: float, *, poll_first: bool) -> TaskResult:
        deadline = self._clock() + budget
        last_running: str | None = None
        if not poll_first:
            self._sleep(min(self._config.poll_interval_seconds, budget))
        while True:
            reply = self._exchange("GET", task_path(task_id), deadline=deadline)
            if isinstance(reply, ErrorDetail):
                note = (
                    f" The task was last confirmed running at {last_running}"
                    if last_running
                    else " The task's state is not confirmed"
                )
                return TaskResult.from_error(
                    task_id,
                    reply.code,
                    f"{reply.message}{note}; it may still be running. Retrieve it later with: "
                    f"orbital-bridge wait {task_id}",
                )
            result = result_from_reply(task_id, *reply, GET_RECORD_STATUSES)
            if result.status is not TaskStatus.RUNNING or budget == 0:
                return result
            last_running = utc_now_text()
            remaining = deadline - self._clock()
            if remaining <= 0:
                return TaskResult.from_error(
                    task_id,
                    ErrorCode.WAIT_DEADLINE_REACHED,
                    f"Stopped waiting after {budget:g} s; the task was still running at "
                    f"{last_running} and has not been confirmed finished. Retrieve it with: "
                    f"orbital-bridge wait {task_id}",
                )
            self._sleep(min(self._config.poll_interval_seconds, remaining))
