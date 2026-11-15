"""Static helpers of the evidence store: exclusive file creation and naming."""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from r1_retest.utils import utc_now

RUN_PREFIX = "r1rt-"
RUN_ID_PATTERN = re.compile(r"^r1rt-\d{8}T\d{6}Z-[0-9a-f]{6}$")
EVENT_FILE_PATTERN = re.compile(r"^(\d{6})-([a-z-]+)\.json$")
EVENTS_DIR = "events"
ARTIFACTS_DIR = "artifacts"
MANUAL_DIR = "manual"
ATTACHMENTS_DIR = "attachments"
REPORTS_DIR = "reports"
RUN_FILE = "run.json"
LOCK_FILE = "run.lock"
MAX_IMPORT_BYTES = 16 * 1024 * 1024


def new_run_id() -> str:
    return f"{RUN_PREFIX}{utc_now():%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def stamp() -> str:
    """A unique, sortable file-name prefix: UTC time to the millisecond plus random hex."""
    now = utc_now()
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z-{secrets.token_hex(2)}"


def create_new_file(path: Path, data: bytes) -> None:
    """Write *data* to a file that must not exist yet; evidence is never overwritten."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def open_new_file(path: Path) -> int:
    """Create an empty file that must not exist yet and return a write descriptor for it."""
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)


def safe_name(text: str) -> str:
    """*text* reduced to characters that are safe in a file name."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._")
    return cleaned[:80] or "item"


def run_ids(results_root: Path) -> list[str]:
    if not results_root.is_dir():
        return []
    return sorted(
        p.name for p in results_root.iterdir() if p.is_dir() and RUN_ID_PATTERN.match(p.name)
    )
