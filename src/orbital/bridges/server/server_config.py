"""Settings of the Claude-side bridge server."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Self

from orbital.bridges.auth.shared_key import SharedKey
from orbital.bridges.utils import env_int, env_text


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Settings of the bridge server (plan section 13).

    ``claude_args`` must not contain flags that would change the output contract the bridge
    relies on (``-p``/``--print``, ``--output-format``, ``--input-format``, ``--session-id``,
    ``-r``/``--resume``, ``-c``/``--continue``, ``--verbose``).
    """

    key: SharedKey
    # The server listens on every interface by default so that a sandbox can publish its port.
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8765
    workdir: Path = field(default_factory=Path.cwd)
    claude_bin: str = "claude"
    claude_args: tuple[str, ...] = ("--permission-prompts", "none")
    max_execution_timeout_seconds: int = 14400
    max_request_bytes: int = 1048576
    retained_tasks: int = 100
    clock_skew_seconds: int = 300
    socket_timeout_seconds: float = 30.0
    grace_seconds: float = 5.0

    FORBIDDEN_CLAUDE_ARGS: ClassVar[frozenset[str]] = frozenset(
        {
            "-p",
            "--print",
            "--output-format",
            "--input-format",
            "--session-id",
            "-r",
            "--resume",
            "-c",
            "--continue",
            "--verbose",
        }
    )
    FORBIDDEN_SHORT_LETTERS: ClassVar[frozenset[str]] = frozenset("prc")

    def __post_init__(self) -> None:
        if not isinstance(self.key, SharedKey):
            raise ValueError("key must be a SharedKey")
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("host must be a non-empty string")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 0 <= self.port <= 65535
        ):
            raise ValueError("port must be an integer between 0 and 65535")
        if not isinstance(self.workdir, Path):
            raise ValueError("workdir must be a Path")
        if not isinstance(self.claude_bin, str) or not self.claude_bin.strip():
            raise ValueError("claude_bin must be a non-empty string")
        if not isinstance(self.claude_args, tuple) or not all(
            isinstance(arg, str) for arg in self.claude_args
        ):
            raise ValueError("claude_args must be a tuple of strings")
        for arg in self.claude_args:
            flag = arg.split("=", 1)[0]
            combined_short = re.fullmatch(r"-[A-Za-z]{2,}", flag) is not None
            if flag in self.FORBIDDEN_CLAUDE_ARGS or (
                combined_short and set(flag[1:]) & self.FORBIDDEN_SHORT_LETTERS
            ):
                raise ValueError(
                    f"claude_args must not contain {arg!r}: the bridge sets Claude Code's "
                    "output contract itself"
                )
        for name in (
            "max_execution_timeout_seconds",
            "max_request_bytes",
            "retained_tasks",
            "clock_skew_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer of at least 1")
        for name in ("socket_timeout_seconds", "grace_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
                raise ValueError(f"{name} must be a positive number")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        """Build the settings from ``ORBITAL_BRIDGE_*`` variables; unset ones keep the defaults.

        ``ORBITAL_BRIDGE_KEY`` is required. ``ORBITAL_BRIDGE_CLAUDE_ARGS`` uses shell syntax and,
        when set (even to an empty value), replaces the default ``--permission-prompts none``.
        """
        source = os.environ if env is None else env
        key_text = source.get("ORBITAL_BRIDGE_KEY", "").strip()
        if not key_text:
            raise ValueError(
                "ORBITAL_BRIDGE_KEY is not set; generate one with "
                'python3 -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        try:
            key = SharedKey.from_text(key_text)
        except ValueError as exc:
            raise ValueError(f"ORBITAL_BRIDGE_KEY is invalid: {exc}") from None
        settings: dict[str, Any] = {}
        if source.get("ORBITAL_BRIDGE_HOST", "").strip():
            settings["host"] = env_text(source, "ORBITAL_BRIDGE_HOST", "")
        if source.get("ORBITAL_BRIDGE_WORKDIR", "").strip():
            settings["workdir"] = Path(env_text(source, "ORBITAL_BRIDGE_WORKDIR", ""))
        if source.get("ORBITAL_BRIDGE_CLAUDE_BIN", "").strip():
            settings["claude_bin"] = env_text(source, "ORBITAL_BRIDGE_CLAUDE_BIN", "")
        if "ORBITAL_BRIDGE_CLAUDE_ARGS" in source:
            try:
                settings["claude_args"] = tuple(shlex.split(source["ORBITAL_BRIDGE_CLAUDE_ARGS"]))
            except ValueError as exc:
                raise ValueError(
                    f"ORBITAL_BRIDGE_CLAUDE_ARGS is not valid shell syntax: {exc}"
                ) from None
        integers = (
            ("ORBITAL_BRIDGE_PORT", "port"),
            ("ORBITAL_BRIDGE_MAX_EXECUTION_TIMEOUT", "max_execution_timeout_seconds"),
            ("ORBITAL_BRIDGE_MAX_REQUEST_BYTES", "max_request_bytes"),
            ("ORBITAL_BRIDGE_RETAINED_TASKS", "retained_tasks"),
            ("ORBITAL_BRIDGE_CLOCK_SKEW", "clock_skew_seconds"),
        )
        for env_name, field_name in integers:
            if source.get(env_name, "").strip():
                settings[field_name] = env_int(source, env_name, 0)
        return cls(key=key, **settings)
