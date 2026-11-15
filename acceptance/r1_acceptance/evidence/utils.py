"""Static helpers of the evidence store: immutable file creation, naming and JSON encoding."""

from __future__ import annotations

import json
import os
import re
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUN_ID_PATTERN = re.compile(r"r1-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}")
EVENT_FILE_PATTERN = re.compile(r"([0-9]{6})-([a-z0-9-]+)\.json")
RUN_FILE = "run.json"
EVENTS_DIR = "events"
ARTIFACTS_DIR = "artifacts"
ATTACHMENTS_DIR = "attachments"
REPORTS_DIR = "reports"
LOCK_FILE = "run.lock"
MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024


def new_run_id(moment: datetime) -> str:
    """A unique run id: ``r1-<UTC time>-<6 random hex digits>``."""
    return f"r1-{moment.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


def create_new_file(path: Path, data: bytes) -> None:
    """Create *path* holding *data*; fail if it exists, so that evidence is never overwritten."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def json_bytes(document: Mapping[str, Any]) -> bytes:
    """*document* as indented UTF-8 JSON (a lone surrogate becomes its ``\\uXXXX`` escape)."""
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    return text.encode("utf-8", "backslashreplace")


def read_json_object(path: Path) -> dict[str, Any]:
    """The JSON object stored at *path*; ``ValueError`` if it is not one."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return document


def safe_file_name(name: str) -> str:
    """*name* reduced to letters, digits, dots, dashes and underscores (at most 80 characters)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:80] or "file"


def run_ids(results_root: Path) -> list[str]:
    """The ids of the runs below *results_root*, oldest first."""
    if not results_root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in results_root.iterdir()
        if entry.is_dir() and RUN_ID_PATTERN.fullmatch(entry.name)
    )
