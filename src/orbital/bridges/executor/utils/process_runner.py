"""Helpers of ProcessRunner: pipe pumping, and process-tree inspection and signalling.

Process-tree helpers read Linux ``/proc``.
"""

from __future__ import annotations

import contextlib
import os
import signal
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import IO

CHUNK_SIZE = 65536
DEAD_STATES = frozenset({"Z", "X"})


def feed_stdin(stream: IO[bytes], data: bytes) -> None:
    """Write *data* to a child's stdin, then close it.

    A child that stops reading early is tolerated; its output decides the outcome.
    """
    fd = stream.fileno()
    view = memoryview(data)
    try:
        while view:
            written = os.write(fd, view)
            view = view[written:]
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError):
            stream.close()


def drain_bounded(
    stream: IO[bytes], limit: int, sink: bytearray, overflowed: threading.Event
) -> None:
    """Read *stream* to EOF, keeping at most *limit* bytes; set *overflowed* if more arrive."""
    fd = stream.fileno()
    try:
        while chunk := os.read(fd, CHUNK_SIZE):
            room = limit - len(sink)
            if room > 0:
                sink += chunk[:room]
            if len(chunk) > room:
                overflowed.set()
    finally:
        stream.close()


def drain_tail(stream: IO[bytes], limit: int, sink: bytearray) -> None:
    """Read *stream* to EOF, keeping only its last *limit* bytes."""
    fd = stream.fileno()
    try:
        while chunk := os.read(fd, CHUNK_SIZE):
            sink += chunk
            excess = len(sink) - limit
            if excess > 0:
                del sink[:excess]
    finally:
        stream.close()


def process_info(pid: int) -> tuple[str, int, int] | None:
    """``(state, parent pid, start time)`` of *pid* from ``/proc``, or ``None`` if it is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    fields = stat[stat.rindex(")") + 2 :].split()
    return fields[0], int(fields[1]), int(fields[19])


def descendants(root: int) -> dict[int, int]:
    """Map every live descendant of *root* (children, grandchildren, ...) to its start time.

    Descendants are found through parent links, so this includes processes that moved to other
    sessions or process groups, as Claude Code's tool processes do.
    """
    children: dict[int, list[int]] = {}
    start_times: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        info = process_info(pid)
        if info is None or info[0] in DEAD_STATES:
            continue
        children.setdefault(info[1], []).append(pid)
        start_times[pid] = info[2]
    found: dict[int, int] = {}
    pending = [root]
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in found:
                found[child] = start_times[child]
                pending.append(child)
    return found


def has_exited(pid: int) -> bool:
    """``True`` once child *pid* has exited, without reaping it.

    Leaving the exited child unreaped keeps its pid, and therefore its process-group id,
    reserved, so signalling that group cannot reach an unrelated process that reused the pid.
    """
    try:
        return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except ChildProcessError:
        return True


def is_alive(pid: int, start_time: int) -> bool:
    """``True`` if *pid* still runs and is the same process (same start time, not a zombie)."""
    info = process_info(pid)
    return info is not None and info[2] == start_time and info[0] not in DEAD_STATES


def kill_tracked(tracked: Mapping[int, int], sig: signal.Signals) -> None:
    """Send *sig* to each tracked process that is still the same live process."""
    for pid, start_time in tracked.items():
        if is_alive(pid, start_time):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, sig)


def signal_group(pgid: int, sig: signal.Signals) -> None:
    """Send *sig* to process group *pgid*, ignoring a group that no longer exists."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)
