"""Helpers shared by both sides of the bridge: API paths, strict JSON and environment readers."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

SERVICE_NAME = "orbital-bridge"
JSON_CONTENT_TYPE = "application/json; charset=utf-8"
TASKS_PATH = "/v1/tasks"
HEALTH_PATH = "/v1/health"


def task_path(task_id: str) -> str:
    """Return the path of one task's record, ``/v1/tasks/<task_id>``."""
    return f"{TASKS_PATH}/{task_id}"


def task_id_from_path(path: str) -> str | None:
    """Return the id segment of ``/v1/tasks/<id>``, or ``None`` if *path* is not a task path."""
    prefix = TASKS_PATH + "/"
    if not path.startswith(prefix):
        return None
    segment = path[len(prefix) :]
    return segment if segment and "/" not in segment else None


def encode_json(document: Mapping[str, Any]) -> bytes:
    """Encode *document* as compact UTF-8 JSON; NaN and infinities are refused.

    A lone surrogate (which UTF-8 cannot represent, but which a JSON ``\\ud800`` escape can
    produce) is written back as the same ``\\uXXXX`` escape, so the result is still valid JSON.
    """
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return text.encode("utf-8", errors="backslashreplace")


def decode_json_object(raw: bytes) -> dict[str, Any]:
    """Strictly decode a UTF-8 JSON object.

    Raises ``ValueError`` if the bytes are not UTF-8, not JSON, not an object at the top level,
    or contain duplicate keys, ``NaN`` or infinities.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("the body is not valid UTF-8") from exc
    try:
        document = json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_no_constants)
    except json.JSONDecodeError as exc:
        raise ValueError(f"the body is not valid JSON ({exc.msg})") from exc
    except RecursionError as exc:
        raise ValueError("the body is nested too deeply") from exc
    if not isinstance(document, dict):
        raise ValueError("the body is not a JSON object")
    return document


def env_text(env: Mapping[str, str], name: str, default: str) -> str:
    """Return the stripped value of *name*, or *default* when it is unset or blank."""
    value = env.get(name, "").strip()
    return value or default


def env_int(env: Mapping[str, str], name: str, default: int) -> int:
    """Return *name* as an integer, or *default* when it is unset or blank."""
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, not {raw!r}") from None


def env_float(env: Mapping[str, str], name: str, default: float | None) -> float | None:
    """Return *name* as a finite number, or *default* when it is unset or blank."""
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, not {raw!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, not {raw!r}")
    return value


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError(f"duplicate key {key!r}")
        document[key] = value
    return document


def _no_constants(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")
