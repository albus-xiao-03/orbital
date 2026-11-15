"""EvidenceStore: the directory of one acceptance run, where nothing is overwritten or deleted."""

from __future__ import annotations

import fcntl
import os
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from r1_acceptance.evidence.utils import (
    ARTIFACTS_DIR,
    ATTACHMENTS_DIR,
    EVENT_FILE_PATTERN,
    EVENTS_DIR,
    LOCK_FILE,
    MAX_ATTACHMENT_BYTES,
    REPORTS_DIR,
    RUN_FILE,
    create_new_file,
    json_bytes,
    new_run_id,
    read_json_object,
    run_ids,
    safe_file_name,
)
from r1_acceptance.utils import format_time, sha256_bytes, sha256_file, utc_now


class EvidenceStore:
    """The evidence of one acceptance run, kept in its own directory.

    Layout of ``<results root>/<run id>/``:

    - ``run.json``: the run's settings and environment, written once;
    - ``events/NNNNNN-<kind>.json``: one immutable file per event, from which the run's
      state is derived;
    - ``artifacts/``: the raw output of every command;
    - ``attachments/``: copies of the files attached to manual records;
    - ``reports/<id>/``: generated reports, each in a new directory.

    Every file is created exclusively, so an existing file is never overwritten, and nothing
    is ever deleted. Commands that write take an advisory lock on ``run.lock`` first.
    """

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = run_dir
        self._info = read_json_object(run_dir / RUN_FILE)
        self._lock_descriptor: int | None = None

    @classmethod
    def create(cls, results_root: Path, info: Mapping[str, Any]) -> EvidenceStore:
        """Create a new run directory with a unique id below *results_root*."""
        results_root.mkdir(parents=True, exist_ok=True)
        run_id = new_run_id(utc_now())
        run_dir = results_root / run_id
        run_dir.mkdir()
        for name in (EVENTS_DIR, ARTIFACTS_DIR, ATTACHMENTS_DIR, REPORTS_DIR):
            (run_dir / name).mkdir()
        create_new_file(run_dir / RUN_FILE, json_bytes({"run_id": run_id, **info}))
        return cls(run_dir)

    @classmethod
    def open(cls, results_root: Path, run_id: str | None = None) -> EvidenceStore:
        """Open the run *run_id*, or the latest run below *results_root*."""
        ids = run_ids(results_root)
        if run_id is None:
            if not ids:
                raise LookupError(
                    f"there is no acceptance run in {results_root}; start one with: "
                    "r1-acceptance init"
                )
            run_id = ids[-1]
        elif run_id not in ids:
            raise LookupError(f"there is no run {run_id!r} in {results_root}")
        return cls(results_root / run_id)

    @property
    def run_id(self) -> str:
        """The run's unique id (the name of its directory)."""
        return self._run_dir.name

    @property
    def run_dir(self) -> Path:
        """The run's directory."""
        return self._run_dir

    @property
    def info(self) -> Mapping[str, Any]:
        """The content of ``run.json``."""
        return self._info

    def lock(self) -> None:
        """Take the run's lock for this process; ``RuntimeError`` if another process holds it.

        The lock is released when the process exits; the lock file is never removed.
        """
        if self._lock_descriptor is not None:
            return
        descriptor = os.open(self._run_dir / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise RuntimeError(
                f"another r1-acceptance command is working on run {self.run_id}; "
                "wait until it finishes"
            ) from exc
        self._lock_descriptor = descriptor

    def append_event(self, kind: str, payload: Mapping[str, Any]) -> int:
        """Record a new event and return its sequence number."""
        sequence = self._last_sequence() + 1
        while True:
            document = {
                "seq": sequence,
                "kind": kind,
                "at": format_time(utc_now()),
                "payload": dict(payload),
            }
            try:
                create_new_file(
                    self._run_dir / EVENTS_DIR / f"{sequence:06d}-{kind}.json",
                    json_bytes(document),
                )
            except FileExistsError:
                sequence += 1
                continue
            return sequence

    def events(self) -> list[dict[str, Any]]:
        """Every readable event of the run, in sequence order.

        An event file that cannot be read can only come from a command killed while writing it.
        It is left in place, skipped as if the event never happened, and listed by
        :meth:`unreadable_events`.
        """
        found = [event for event in map(self._read_event, self._event_files()) if event]
        found.sort(key=lambda event: int(event["seq"]))
        return found

    def unreadable_events(self) -> list[str]:
        """The names of event files that cannot be read."""
        return [path.name for path in self._event_files() if self._read_event(path) is None]

    def write_artifact(self, name: str, data: bytes) -> str:
        """Store raw command output as a new artifact; return its path relative to the run."""
        relative = f"{ARTIFACTS_DIR}/{safe_file_name(name)}"
        create_new_file(self._run_dir / relative, data)
        return relative

    def read_artifact(self, relative: str) -> bytes:
        """The content of an artifact, by its path relative to the run."""
        return (self._run_dir / relative).read_bytes()

    def store_attachment(self, source: Path) -> dict[str, Any]:
        """Copy *source* into the run as a new attachment and describe the copy."""
        size = source.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            raise ValueError(
                f"{source} has {size} bytes; attachments are limited to {MAX_ATTACHMENT_BYTES}"
            )
        data = source.read_bytes()
        relative = f"{ATTACHMENTS_DIR}/{secrets.token_hex(4)}-{safe_file_name(source.name)}"
        create_new_file(self._run_dir / relative, data)
        return {
            "original": str(source),
            "stored": relative,
            "sha256": sha256_bytes(data),
            "bytes": len(data),
        }

    def save_report(self, files: Mapping[str, bytes]) -> Path:
        """Write one report's *files* into a new directory below ``reports/``; return it."""
        name = f"{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
        directory = self._run_dir / REPORTS_DIR / name
        directory.mkdir()
        for file_name, data in files.items():
            create_new_file(directory / safe_file_name(file_name), data)
        return directory

    def evidence_index(self) -> list[dict[str, Any]]:
        """Path, size and SHA-256 of every evidence file (reports and the lock file excluded)."""
        entries: list[dict[str, Any]] = []
        for path in sorted(self._run_dir.rglob("*")):
            relative = path.relative_to(self._run_dir)
            if not path.is_file() or relative.parts[0] == REPORTS_DIR or path.name == LOCK_FILE:
                continue
            entries.append(
                {
                    "path": relative.as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        return entries

    def _event_files(self) -> list[Path]:
        return sorted(
            path
            for path in (self._run_dir / EVENTS_DIR).iterdir()
            if EVENT_FILE_PATTERN.fullmatch(path.name)
        )

    @staticmethod
    def _read_event(path: Path) -> dict[str, Any] | None:
        try:
            event = read_json_object(path)
        except (OSError, ValueError):
            return None
        if not {"seq", "kind", "at", "payload"} <= event.keys() or not isinstance(
            event["seq"], int
        ):
            return None
        return event

    def _last_sequence(self) -> int:
        last = 0
        for path in (self._run_dir / EVENTS_DIR).iterdir():
            match = EVENT_FILE_PATTERN.fullmatch(path.name)
            if match is not None:
                last = max(last, int(match.group(1)))
        return last
