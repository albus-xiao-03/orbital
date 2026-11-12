"""Exception family of task admission."""

from __future__ import annotations


class ServerBusyError(Exception):
    """Another task is running; this server runs at most one task at a time."""

    def __init__(self, running_task_id: str) -> None:
        self.running_task_id = running_task_id
        super().__init__(f"another task is running: {running_task_id}")


class TaskConflictError(Exception):
    """This server instance already used the task id (different content, or no longer retained)."""

    def __init__(self, task_id: str, reason: str) -> None:
        self.task_id = task_id
        self.reason = reason
        super().__init__(f"Task id {task_id} was already used by this server instance ({reason}).")
