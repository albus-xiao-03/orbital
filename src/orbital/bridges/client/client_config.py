"""Settings of the ChatGPT-side bridge client."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Self
from urllib.parse import urlsplit

from orbital.bridges.auth.shared_key import SharedKey
from orbital.bridges.utils import env_float, env_int, env_text


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Settings of the bridge client (plan section 13).

    ``url`` must be ``http://host[:port]`` with no path, query, fragment or userinfo.
    ``execution_timeout_seconds`` is sent with each task and enforced by the server;
    ``max_wait_seconds`` is the client's own waiting budget and is never sent (``None`` means
    the execution timeout plus :attr:`WAIT_GRACE_SECONDS`).
    """

    key: SharedKey
    url: str = "http://host.docker.internal:8765"
    execution_timeout_seconds: int = 1800
    max_wait_seconds: float | None = None
    poll_interval_seconds: float = 2.0
    request_timeout_seconds: float = 30.0
    max_retries: int = 5
    max_request_bytes: int = 1048576
    use_env_proxy: bool = True

    WAIT_GRACE_SECONDS: ClassVar[float] = 60.0

    def __post_init__(self) -> None:
        if not isinstance(self.key, SharedKey):
            raise ValueError("key must be a SharedKey")
        if not isinstance(self.url, str):
            raise ValueError("url must be a string")
        parts = urlsplit(self.url.strip())
        try:
            parts.port  # noqa: B018 - raises ValueError for an invalid port
        except ValueError:
            raise ValueError(f"the bridge URL {self.url!r} has an invalid port") from None
        if (
            parts.scheme != "http"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError(
                f"the bridge URL must be http://host[:port] with no path, query or credentials, "
                f"not {self.url!r}"
            )
        object.__setattr__(self, "url", f"http://{parts.netloc}")
        for name in ("execution_timeout_seconds", "max_request_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer of at least 1")
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or self.max_retries < 0
        ):
            raise ValueError("max_retries must be an integer of at least 0")
        for name, minimum, optional in (
            ("poll_interval_seconds", 0.0, False),
            ("request_timeout_seconds", 0.0, False),
            ("max_wait_seconds", 0.0, True),
        ):
            value = getattr(self, name)
            if optional and value is None:
                continue
            finite = (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and math.isfinite(value)
            )
            # Timeouts and intervals must be positive; a zero wait budget means a single poll.
            if not finite or not (value >= minimum if optional else value > minimum):
                kind = "a non-negative number or None" if optional else "a positive number"
                raise ValueError(f"{name} must be {kind}")
        if not isinstance(self.use_env_proxy, bool):
            raise ValueError("use_env_proxy must be a bool")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        """Build the settings from ``ORBITAL_BRIDGE_*`` variables; unset ones keep the defaults."""
        source = os.environ if env is None else env
        key_text = source.get("ORBITAL_BRIDGE_KEY", "").strip()
        if not key_text:
            raise ValueError("ORBITAL_BRIDGE_KEY is not set; use the same key as the server")
        try:
            key = SharedKey.from_text(key_text)
        except ValueError as exc:
            raise ValueError(f"ORBITAL_BRIDGE_KEY is invalid: {exc}") from None
        settings: dict[str, Any] = {}
        if source.get("ORBITAL_BRIDGE_URL", "").strip():
            settings["url"] = env_text(source, "ORBITAL_BRIDGE_URL", "")
        integers = (
            ("ORBITAL_BRIDGE_EXECUTION_TIMEOUT", "execution_timeout_seconds"),
            ("ORBITAL_BRIDGE_MAX_RETRIES", "max_retries"),
            ("ORBITAL_BRIDGE_MAX_REQUEST_BYTES", "max_request_bytes"),
        )
        for env_name, field_name in integers:
            if source.get(env_name, "").strip():
                settings[field_name] = env_int(source, env_name, 0)
        numbers = (
            ("ORBITAL_BRIDGE_MAX_WAIT", "max_wait_seconds"),
            ("ORBITAL_BRIDGE_POLL_INTERVAL", "poll_interval_seconds"),
            ("ORBITAL_BRIDGE_REQUEST_TIMEOUT", "request_timeout_seconds"),
        )
        for env_name, field_name in numbers:
            if source.get(env_name, "").strip():
                settings[field_name] = env_float(source, env_name, None)
        return cls(key=key, **settings)

    def wait_budget(self, execution_timeout_seconds: int | None = None) -> float:
        """The default waiting budget: ``max_wait_seconds``, or the execution timeout plus 60 s."""
        if self.max_wait_seconds is not None:
            return float(self.max_wait_seconds)
        timeout = (
            self.execution_timeout_seconds
            if execution_timeout_seconds is None
            else execution_timeout_seconds
        )
        return timeout + self.WAIT_GRACE_SECONDS
