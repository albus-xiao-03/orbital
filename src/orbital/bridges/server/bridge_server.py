"""The Claude-side bridge server."""

from __future__ import annotations

import logging
import os
import socket
import threading
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from socketserver import TCPServer

from orbital.bridges.auth.message_authenticator import MessageAuthenticator
from orbital.bridges.auth.nonce_cache import NonceCache
from orbital.bridges.executor.claude_code_executor import ClaudeCodeExecutor
from orbital.bridges.server.request_handler import BridgeRequestHandler
from orbital.bridges.server.server_config import ServerConfig
from orbital.bridges.server.task_registry import TaskRegistry
from orbital.bridges.server.task_supervisor import TaskSupervisor


class BridgeServer(ThreadingHTTPServer):
    """HTTP server wired to the authenticator, task registry, supervisor and executor.

    It binds on construction, so :attr:`port` is known even when the configured port is 0. Run
    it with :meth:`serve_forever` and end it with :meth:`stop` (graceful: the running task is
    terminated and reaped). Task records live in memory and are lost when the process exits.
    """

    daemon_threads = True

    def __init__(self, config: ServerConfig, *, executor: ClaudeCodeExecutor | None = None) -> None:
        self.config = config
        self.log = logging.getLogger("orbital.bridges.server")
        self.started_at = datetime.now(UTC)
        self.authenticator = MessageAuthenticator(
            config.key,
            clock_skew_seconds=config.clock_skew_seconds,
            nonce_cache=NonceCache(ttl_seconds=2 * config.clock_skew_seconds),
        )
        self.registry = TaskRegistry(config.retained_tasks)
        self.executor = (
            executor
            if executor is not None
            else ClaudeCodeExecutor(
                workdir=config.workdir,
                claude_bin=config.claude_bin,
                claude_args=config.claude_args,
                grace_seconds=config.grace_seconds,
            )
        )
        self.supervisor = TaskSupervisor(self.registry, self.executor)
        self._serving_thread: threading.Thread | None = None
        if ":" in config.host:
            self.address_family = socket.AF_INET6
        if "CLAUDECODE" in os.environ:
            self.log.warning(
                "This server was started from inside a Claude Code session; that session's "
                "variables are removed from every task's environment. Prefer a plain shell."
            )
        super().__init__((config.host, config.port), BridgeRequestHandler)

    def server_bind(self) -> None:
        # Skip HTTPServer.server_bind, which does a reverse DNS lookup of the bind address.
        TCPServer.server_bind(self)
        self.server_name = str(self.server_address[0])
        self.server_port = int(self.server_address[1])

    @property
    def port(self) -> int:
        """The port the server is listening on."""
        return int(self.server_address[1])

    @property
    def started_at_text(self) -> str:
        """When this server instance started, as ``YYYY-MM-DDTHH:MM:SSZ``."""
        return self.started_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        self._serving_thread = threading.current_thread()
        try:
            super().serve_forever(poll_interval)
        finally:
            self._serving_thread = None

    def stop(self, timeout: float = 10.0) -> None:
        """Stop accepting connections, cancel the running task and wait until it is reaped and
        recorded (at most *timeout* seconds), then close the socket."""
        serving = self._serving_thread
        if serving is not None and serving is not threading.current_thread():
            self.shutdown()
        self.supervisor.shutdown(timeout)
        self.server_close()
