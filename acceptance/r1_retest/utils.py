"""Constants and static helpers shared by the whole harness."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

HARNESS_NAME = "r1-retest"
HARNESS_VERSION = "1.0.0"
RUN_SCHEMA = "r1-retest/run/1"
REPORT_SCHEMA = "r1-retest/report/1"
MINIMUM_PYTHON = (3, 11)

# The implementation under test: plans/R1-fix.md, fix round 1 (HEAD 135e0f2).
EXPECTED_COMMIT = "135e0f2ecd1c70af3fd0752fca3e3c1ced30e43d"
EXPECTED_SOURCE_DIGEST = "2f98d10483d133a81d10b0c397a0810d920e23461a0bc48ef9af98703fa6b21c"
PREVIOUS_RUN_ID = "r1-20261115T030647Z-bc9829"

DEFAULT_URL = "http://host.docker.internal:8765"
DEFAULT_RESULTS = "~/orbital-acceptance/r1-retest"
DEFAULT_PREVIOUS_RESULTS = "~/orbital-acceptance/r1-acceptance"
RESULTS_ENV = "R1_RETEST_RESULTS"

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
TASK_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
OFFSET = re.compile(r"^([+-])(\d{2})(\d{2})$")


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_time(moment: datetime) -> str:
    """``YYYY-MM-DDTHH:MM:SS.mmmZ`` in UTC."""
    return (
        moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
    )


def parse_time(text: str) -> datetime:
    """An ISO 8601 UTC time ending in ``Z`` (any fraction)."""
    if not ISO_UTC.match(text):
        raise ValueError(f"not an ISO UTC time: {text!r}")
    head, _, fraction = text[:-1].partition(".")
    moment = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    if fraction:
        moment += timedelta(microseconds=int((fraction + "000000")[:6]))
    return moment


def parse_offset(text: str) -> timezone:
    """A ``date +%z`` offset such as ``-0500``."""
    match = OFFSET.match(text.strip())
    if not match:
        raise ValueError(f"not a UTC offset: {text!r}")
    sign = -1 if match.group(1) == "-" else 1
    return timezone(sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3))))


def seconds_between(later: datetime, earlier: datetime) -> float:
    return round((later - earlier).total_seconds(), 3)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    """Digest of the ``*.py`` files below *root* (relative paths and contents, sorted).

    The same algorithm as the earlier acceptance run and plans/R1-fix.md, so digests compare.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(sha256_file(path).encode("ascii") + b"\n")
    return digest.hexdigest()


def read_git_commit(repository: Path) -> str | None:
    """The commit checked out in *repository*, read from ``.git`` without running git."""
    git = repository / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head.startswith("ref: "):
        return head or None
    ref = head[5:]
    try:
        return (git / ref).read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except OSError:
        return None
    return None


def redact_url(url: str) -> str:
    """*url* without any user information (a proxy URL may carry credentials)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparsable>"
    if parts.username is None and parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, f"<redacted>@{host}", parts.path, parts.query, parts.fragment))


def json_bytes(document: Any) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n").encode(
        "utf-8"
    )
