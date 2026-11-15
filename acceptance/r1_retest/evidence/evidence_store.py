"""The run directory: append-only events, artifacts, manual imports, attachments and reports."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from r1_retest.evidence.utils import (
    ARTIFACTS_DIR,
    ATTACHMENTS_DIR,
    EVENT_FILE_PATTERN,
    EVENTS_DIR,
    LOCK_FILE,
    MANUAL_DIR,
    REPORTS_DIR,
    RUN_FILE,
    create_new_file,
    new_run_id,
    open_new_file,
    run_ids,
    safe_name,
    stamp,
)
from r1_retest.utils import format_time, json_bytes, sha256_file, utc_now


class EvidenceStore:
    """One acceptance run's directory.

    Every file is created exclusively (``O_EXCL``) and never rewritten or removed: events are
    numbered files, and a report is a new directory each time. A half-written event (after a
    crash) is skipped and listed, never repaired.
    """

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self._unreadable: list[str] = []

    # ------------------------------------------------------------------ creation and opening

    @classmethod
    def create(cls, results_root: Path, info: dict[str, Any]) -> EvidenceStore:
        results_root.mkdir(parents=True, exist_ok=True)
        run_id = new_run_id()
        run_dir = results_root / run_id
        run_dir.mkdir()
        for name in (EVENTS_DIR, ARTIFACTS_DIR, MANUAL_DIR, ATTACHMENTS_DIR, REPORTS_DIR):
            (run_dir / name).mkdir()
        create_new_file(run_dir / RUN_FILE, json_bytes({"run_id": run_id, **info}))
        return cls(run_dir)

    @classmethod
    def open(cls, results_root: Path, run_id: str | None = None) -> EvidenceStore:
        ids = run_ids(results_root)
        if run_id is None:
            if not ids:
                raise FileNotFoundError(f"no r1-retest run under {results_root}; run 'init' first")
            run_id = ids[-1]
        elif run_id not in ids:
            raise FileNotFoundError(f"no run {run_id} under {results_root}")
        return cls(results_root / run_id)

    @property
    def run_id(self) -> str:
        return self.run_dir.name

    def info(self) -> dict[str, Any]:
        document: dict[str, Any] = json.loads((self.run_dir / RUN_FILE).read_text(encoding="utf-8"))
        return document

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        """Exclusive access for one harness command at a time (the lock file is never removed)."""
        descriptor = os.open(self.run_dir / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError(
                    f"another r1-retest command is working on run {self.run_id}; wait for it"
                ) from None
            yield
        finally:
            os.close(descriptor)

    # --------------------------------------------------------------------------------- events

    def _event_files(self) -> list[tuple[int, Path]]:
        found = []
        for path in (self.run_dir / EVENTS_DIR).iterdir():
            match = EVENT_FILE_PATTERN.match(path.name)
            if match:
                found.append((int(match.group(1)), path))
        return sorted(found)

    def append_event(self, kind: str, payload: dict[str, Any]) -> int:
        files = self._event_files()
        sequence = files[-1][0] + 1 if files else 1
        document = {"seq": sequence, "kind": kind, "at": format_time(utc_now()), **payload}
        create_new_file(
            self.run_dir / EVENTS_DIR / f"{sequence:06d}-{kind}.json", json_bytes(document)
        )
        return sequence

    def events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        self._unreadable = []
        for _, path in self._event_files():
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._unreadable.append(path.relative_to(self.run_dir).as_posix())
                continue
            if isinstance(document, dict):
                events.append(document)
            else:
                self._unreadable.append(path.relative_to(self.run_dir).as_posix())
        return events

    def unreadable_events(self) -> list[str]:
        return list(self._unreadable)

    # --------------------------------------------------------------------- files of evidence

    def new_artifact(self, name: str) -> tuple[str, int]:
        """Create an empty artifact for a child process to write; return (relative path, fd)."""
        relative = f"{ARTIFACTS_DIR}/{stamp()}-{safe_name(name)}"
        return relative, open_new_file(self.run_dir / relative)

    def write_file(self, folder: str, name: str, data: bytes) -> str:
        relative = f"{folder}/{stamp()}-{safe_name(name)}"
        create_new_file(self.run_dir / relative, data)
        return relative

    def read_bytes(self, relative: str) -> bytes:
        return (self.run_dir / relative).read_bytes()

    def describe(self, relative: str) -> dict[str, Any]:
        path = self.run_dir / relative
        if not path.is_file():
            return {"path": relative, "missing": True}
        return {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}

    def save_report(self, files: dict[str, bytes]) -> Path:
        folder = self.run_dir / REPORTS_DIR / stamp()
        folder.mkdir()
        for name, data in files.items():
            create_new_file(folder / name, data)
        return folder

    def evidence_index(self) -> list[dict[str, Any]]:
        """Every evidence file except reports and the lock, with size and SHA-256."""
        index = []
        for path in sorted(self.run_dir.rglob("*")):
            relative = path.relative_to(self.run_dir).as_posix()
            if (
                not path.is_file()
                or relative == LOCK_FILE
                or relative.startswith(REPORTS_DIR + "/")
            ):
                continue
            index.append(
                {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            )
        return index
