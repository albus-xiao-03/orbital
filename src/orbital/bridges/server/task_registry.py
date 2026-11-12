"""In-memory record of this server process's tasks."""

from __future__ import annotations

import hashlib
import threading
from collections import deque

from orbital.bridges.models.task_request import TaskRequest
from orbital.bridges.models.task_result import TaskResult
from orbital.bridges.server.errors import ServerBusyError, TaskConflictError


class TaskRegistry:
    """Thread-safe store of task results for the lifetime of one server process.

    Idempotency, conflict detection, single execution and retention hold only within that
    lifetime: a restarted server starts empty (plan section 10). The registry keeps the
    ``retained_tasks`` most recent finished results, never evicts the running task, and
    remembers every task id it has seen.
    """

    def __init__(self, retained_tasks: int = 100) -> None:
        if retained_tasks < 1:
            raise ValueError("retained_tasks must be at least 1")
        self._retained = retained_tasks
        self._lock = threading.Lock()
        self._results: dict[str, TaskResult] = {}
        self._fingerprints: dict[str, str] = {}
        self._finished: deque[str] = deque()
        self._seen: set[str] = set()
        self._running: str | None = None

    @property
    def retained_tasks(self) -> int:
        """How many finished results are kept."""
        return self._retained

    @property
    def running_task_id(self) -> str | None:
        """Id of the running task, if any."""
        with self._lock:
            return self._running

    def admit(self, request: TaskRequest) -> tuple[TaskResult, bool]:
        """Admit *request*; return its record and whether it is new (plan section 10).

        1. A known id with the same content returns the existing record (idempotent).
        2. A known id with different content, or whose result was evicted, is a conflict.
        3. While another task runs, the server is busy.
        4. Otherwise a ``running`` record is created.
        """
        material = f"{request.execution_timeout_seconds}\n{request.prompt}".encode()
        fingerprint = hashlib.sha256(material).hexdigest()
        task_id = request.task_id
        with self._lock:
            if task_id in self._seen:
                if task_id in self._results and self._fingerprints[task_id] == fingerprint:
                    return self._results[task_id], False
                reason = (
                    "it was submitted with different content"
                    if task_id in self._results
                    else "its result is no longer retained"
                )
                raise TaskConflictError(task_id, reason)
            if self._running is not None:
                raise ServerBusyError(self._running)
            record = TaskResult.running(task_id)
            self._seen.add(task_id)
            self._results[task_id] = record
            self._fingerprints[task_id] = fingerprint
            self._running = task_id
            return record, True

    def complete(self, result: TaskResult) -> None:
        """Record the settled result of an admitted task and apply the retention limit."""
        if not result.status.is_settled:
            raise ValueError("only a settled result can complete a task")
        with self._lock:
            task_id = result.task_id
            if task_id not in self._results:
                raise ValueError(f"task {task_id} was not admitted or is no longer retained")
            self._results[task_id] = result
            if self._running == task_id:
                self._running = None
            self._finished.append(task_id)
            while len(self._finished) > self._retained:
                evicted = self._finished.popleft()
                self._results.pop(evicted, None)
                self._fingerprints.pop(evicted, None)

    def get(self, task_id: str) -> TaskResult | None:
        """The current record of *task_id*, or ``None`` if unknown or no longer retained."""
        with self._lock:
            return self._results.get(task_id)

    def was_seen(self, task_id: str) -> bool:
        """``True`` if this server process ever admitted *task_id*."""
        with self._lock:
            return task_id in self._seen
