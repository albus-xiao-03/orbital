"""Admission and execution of the single running task."""

from __future__ import annotations

import logging
import threading
import time

from orbital.bridges.executor.claude_code_executor import ClaudeCodeExecutor
from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.task_request import TaskRequest
from orbital.bridges.models.task_result import TaskResult
from orbital.bridges.models.task_status import TaskStatus
from orbital.bridges.server.task_registry import TaskRegistry


class TaskSupervisor:
    """Admits tasks through the registry and runs the admitted one in a worker thread.

    A settled status is recorded only once the executor has returned, which happens only after
    the Claude Code process has been reaped. If the executor raises, any running process is
    terminated and reaped first, and the task is recorded as ``failed`` / ``internal_error``.
    """

    def __init__(self, registry: TaskRegistry, executor: ClaudeCodeExecutor) -> None:
        self._registry = registry
        self._executor = executor
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._closed = False
        self._log = logging.getLogger("orbital.bridges.server")

    def submit(self, request: TaskRequest) -> tuple[TaskResult, bool]:
        """Admit *request* and start it if it is new; return its record and whether it is new.

        Raises ``ServerBusyError`` or ``TaskConflictError`` from the registry, and
        ``RuntimeError`` once the server is shutting down.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("the bridge server is shutting down")
            record, created = self._registry.admit(request)
            if not created:
                return record, False
            worker = threading.Thread(
                target=self._run, args=(request,), name=f"orbital-task-{request.task_id}"
            )
            worker.daemon = True
            try:
                worker.start()
            except RuntimeError as exc:
                failure = TaskResult.from_error(
                    request.task_id,
                    ErrorCode.INTERNAL_ERROR,
                    f"The bridge could not start the task ({exc}).",
                )
                self._registry.complete(failure)
                return failure, True
            self._worker = worker
        self._log.info(
            "task %s accepted (prompt %d bytes, execution timeout %d s)",
            request.task_id,
            len(request.prompt.encode("utf-8")),
            request.execution_timeout_seconds,
        )
        return record, True

    def status(self, task_id: str) -> TaskResult | None:
        """The current record of *task_id* in this server process, or ``None``."""
        return self._registry.get(task_id)

    def shutdown(self, timeout: float = 10.0) -> None:
        """Refuse new tasks, cancel the running one, and wait for it to be recorded."""
        with self._lock:
            self._closed = True
            worker = self._worker
        self._executor.cancel()
        if worker is not None:
            worker.join(timeout)

    def _run(self, request: TaskRequest) -> None:
        started = time.monotonic()
        try:
            result = self._executor.execute(request)
        except Exception as exc:
            self._log.exception("task %s: unexpected bridge error", request.task_id)
            self._executor.terminate_running()
            result = TaskResult.from_error(
                request.task_id,
                ErrorCode.INTERNAL_ERROR,
                f"Unexpected bridge error while running the task ({type(exc).__name__}); any "
                f"Claude Code process was terminated first.",
            )
        reportable = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.TIMED_OUT}
        if result.task_id != request.task_id or result.status not in reportable:
            result = TaskResult.from_error(
                request.task_id,
                ErrorCode.INTERNAL_ERROR,
                "The executor returned an invalid result.",
            )
        self._registry.complete(result)
        self._log.info(
            "task %s finished: %s%s after %.1f s",
            request.task_id,
            result.status.value,
            f" ({result.error.code.value})" if result.error is not None else "",
            time.monotonic() - started,
        )
