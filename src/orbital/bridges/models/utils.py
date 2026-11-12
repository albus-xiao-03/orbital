"""Helpers shared by the model types: task-id generation and validation, strict field readers."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any

TASK_ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def new_task_id() -> str:
    """Return a fresh task id: a canonical, lowercase UUID version 4."""
    return str(uuid.uuid4())


def is_task_id(value: object) -> bool:
    """Return ``True`` if *value* is a canonical, lowercase UUID version 4."""
    return isinstance(value, str) and TASK_ID_PATTERN.fullmatch(value) is not None


def require_object(value: object, what: str) -> Mapping[str, Any]:
    """Return *value* if it is a JSON object (``dict``); raise ``ValueError`` otherwise."""
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a JSON object")
    return value


def require_exact_keys(document: Mapping[str, Any], keys: frozenset[str], what: str) -> None:
    """Raise ``ValueError`` unless *document* has exactly *keys*."""
    present = set(document)
    missing = sorted(keys - present)
    unknown = sorted(present - keys)
    if missing:
        raise ValueError(f"{what} is missing {', '.join(missing)}")
    if unknown:
        raise ValueError(f"{what} has unknown key(s) {', '.join(unknown)}")


def read_str(document: Mapping[str, Any], key: str, what: str) -> str:
    """Return the string at *key*; raise ``ValueError`` if it is not a string."""
    value = document[key]
    if not isinstance(value, str):
        raise ValueError(f"{what}.{key} must be a string")
    return value


def read_optional_str(document: Mapping[str, Any], key: str, what: str) -> str | None:
    """Return the string or ``None`` at *key*; raise ``ValueError`` for any other type."""
    value = document[key]
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{what}.{key} must be a string or null")
    return value


def read_int(document: Mapping[str, Any], key: str, what: str) -> int:
    """Return the integer at *key*; booleans and floats are refused."""
    value = document[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{what}.{key} must be an integer")
    return value
