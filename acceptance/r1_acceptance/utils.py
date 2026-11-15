"""Constants and static helpers shared by the whole harness."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

HARNESS_NAME = "r1-acceptance"
HARNESS_VERSION = "1.0.0"
RUN_SCHEMA = "orbital-r1-acceptance-run/1"
REPORT_SCHEMA = "orbital-r1-acceptance-report/1"
MINIMUM_PYTHON = (3, 11)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


def utc_now() -> datetime:
    """The current time in UTC."""
    return datetime.now(UTC)


def format_time(moment: datetime) -> str:
    """*moment* as ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (UTC, millisecond precision)."""
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_time(text: str) -> datetime:
    """Parse a UTC timestamp that ends in ``Z``, with or without fractional seconds."""
    if not text.endswith("Z"):
        raise ValueError(f"not a UTC timestamp: {text!r}")
    return datetime.fromisoformat(text[:-1]).replace(tzinfo=UTC)


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of *data*."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of the file at *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    """Digest of the ``*.py`` files below *root*: relative paths and contents, in sorted order.

    It identifies the exact code without git; ``__pycache__`` directories are ignored.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(sha256_file(path).encode("ascii") + b"\n")
    return digest.hexdigest()


def read_git_commit(repository: Path) -> str | None:
    """The commit checked out in *repository*, read from ``.git`` without running git.

    ``None`` when it cannot be determined (no ``.git`` directory, or an unusual layout).
    """
    git_dir = repository / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head if COMMIT_PATTERN.fullmatch(head) else None
        ref = head.removeprefix("ref: ")
        loose = git_dir / ref
        if loose.is_file():
            value = loose.read_text(encoding="utf-8").strip()
            return value if COMMIT_PATTERN.fullmatch(value) else None
        packed = git_dir / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                fields = line.split()
                if len(fields) == 2 and fields[1] == ref and COMMIT_PATTERN.fullmatch(fields[0]):
                    return fields[0]
    except OSError:
        return None
    return None


def redact_url(url: str) -> str:
    """*url* without user information (``user:password@``), for records."""
    try:
        parts = urlsplit(url)
        if parts.username is None and parts.password is None:
            return url
        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
    except ValueError:
        return "<unparseable>"
    return urlunsplit((parts.scheme, f"<redacted>@{host}", parts.path, parts.query, parts.fragment))
