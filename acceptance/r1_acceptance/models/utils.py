"""Static helpers of the models: strict readers for the JSON documents of the evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def require_object(value: object, what: str) -> Mapping[str, Any]:
    """*value* as a JSON object, or ``ValueError``."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{what} must be a JSON object")
    return value


def read_str(data: Mapping[str, Any], key: str) -> str:
    """The string at *key*."""
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key!r} must be a string")
    return value


def read_optional_str(data: Mapping[str, Any], key: str) -> str | None:
    """The string at *key*, or ``None`` when it is missing or null."""
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{key!r} must be a string or null")
    return value


def read_int(data: Mapping[str, Any], key: str) -> int:
    """The integer at *key* (a boolean is not an integer here)."""
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key!r} must be an integer")
    return value


def read_optional_int(data: Mapping[str, Any], key: str) -> int | None:
    """The integer at *key*, or ``None`` when it is missing or null."""
    if data.get(key) is None:
        return None
    return read_int(data, key)


def read_optional_float(data: Mapping[str, Any], key: str) -> float | None:
    """The number at *key* as a float, or ``None`` when it is missing or null."""
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key!r} must be a number or null")
    return float(value)


def read_str_tuple(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """The list of strings at *key* (missing means empty)."""
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key!r} must be a list of strings")
    return tuple(value)


def read_int_tuple(data: Mapping[str, Any], key: str) -> tuple[int, ...]:
    """The list of integers at *key* (missing means empty)."""
    value = data.get(key, [])
    if not isinstance(value, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    ):
        raise ValueError(f"{key!r} must be a list of integers")
    return tuple(value)


def read_optional_object(data: Mapping[str, Any], key: str) -> dict[str, Any] | None:
    """The JSON object at *key*, or ``None`` when it is missing or null."""
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{key!r} must be an object or null")
    return value
