"""Handling of one bridge request."""

from __future__ import annotations

from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, Any

from orbital.bridges.auth.errors import AuthenticationError
from orbital.bridges.auth.utils import PROTOCOL_HEADER, PROTOCOL_VERSION, SCHEME, header_value
from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.task_request import TaskRequest
from orbital.bridges.models.utils import is_task_id
from orbital.bridges.server.errors import ServerBusyError, TaskConflictError
from orbital.bridges.server.utils import (
    error_document,
    format_peer,
    health_document,
    normalize_target,
    parse_content_length,
)
from orbital.bridges.utils import (
    HEALTH_PATH,
    JSON_CONTENT_TYPE,
    SERVICE_NAME,
    TASKS_PATH,
    decode_json_object,
    encode_json,
    task_id_from_path,
)

if TYPE_CHECKING:
    from orbital.bridges.server.bridge_server import BridgeServer


class BridgeRequestHandler(BaseHTTPRequestHandler):
    """Framing, authentication, routing and a signed response, in that order (plan section 10).

    Every response to a request with a well-formed nonce is signed, including ``401``, ``411``
    and ``413``. Unauthenticated requests never reach the supervisor or the executor.
    """

    server: BridgeServer
    protocol_version = "HTTP/1.1"
    server_version = SERVICE_NAME

    def setup(self) -> None:
        super().setup()
        # Per-connection socket timeout (plan section 8), so a slow client cannot hold a thread.
        self.connection.settimeout(self.server.config.socket_timeout_seconds)

    def version_string(self) -> str:
        return SERVICE_NAME

    def log_message(self, format: str, *args: Any) -> None:
        self.server.log.debug("%s %s", format_peer(self.client_address), format % args)

    # http.server dispatches on do_<METHOD>; every method goes through the same pipeline.
    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def _handle(self) -> None:
        self._responded = False
        method = self.command
        target = normalize_target(self.path)
        headers = dict(self.headers.items())
        nonce = self.server.authenticator.request_nonce(headers)
        try:
            self._process(method, target, headers, nonce)
        except Exception:
            self.server.log.exception("unexpected error while handling %s %s", method, target)
            if not self._responded:
                document = error_document(
                    ErrorCode.SERVER_ERROR,
                    "The bridge server failed unexpectedly while handling the request.",
                    None,
                )
                self._respond(method, target, nonce, 500, document)

    def _process(
        self, method: str, target: str, headers: dict[str, str], nonce: str | None
    ) -> None:
        config = self.server.config
        if header_value(headers, "Transfer-Encoding") is not None:
            self._error(
                method,
                target,
                nonce,
                411,
                ErrorCode.INVALID_REQUEST,
                "Chunked request bodies are not supported; send Content-Length.",
            )
            return
        try:
            length = parse_content_length(header_value(headers, "Content-Length"))
        except ValueError as exc:
            self._error(method, target, nonce, 400, ErrorCode.INVALID_REQUEST, str(exc))
            return
        if method == "POST" and length is None:
            self._error(
                method,
                target,
                nonce,
                411,
                ErrorCode.INVALID_REQUEST,
                "A POST request needs a Content-Length header.",
            )
            return
        if method != "POST" and length:
            self._error(
                method,
                target,
                nonce,
                411,
                ErrorCode.INVALID_REQUEST,
                f"A {method} request must not have a body.",
            )
            return
        if length is not None and length > config.max_request_bytes:
            self._error(
                method,
                target,
                nonce,
                413,
                ErrorCode.PAYLOAD_TOO_LARGE,
                f"The request body is {length} bytes; this server accepts at most "
                f"{config.max_request_bytes} bytes.",
            )
            return
        try:
            body = self.rfile.read(length) if length else b""
        except OSError:
            self.close_connection = True
            return
        if len(body) != (length or 0):
            self.close_connection = True
            return
        try:
            self.server.authenticator.verify_request(method, target, headers, body)
        except AuthenticationError as exc:
            self.server.log.warning(
                "authentication failed for %s %s from %s: %s",
                method,
                target,
                format_peer(self.client_address),
                exc,
            )
            message = f"{exc.reason.value}: {exc.detail}" if exc.detail else exc.reason.value
            document = error_document(ErrorCode.UNAUTHORIZED, message, None)
            self._respond(method, target, nonce, 401, document, (("WWW-Authenticate", SCHEME),))
            return
        if nonce is None:  # verify_request guarantees a well-formed nonce
            raise RuntimeError("an authenticated request has no nonce")
        self._route(method, target, body, nonce)

    def _route(self, method: str, target: str, body: bytes, nonce: str) -> None:
        task_id = task_id_from_path(target)
        if target == HEALTH_PATH:
            allowed = "GET"
        elif target == TASKS_PATH:
            allowed = "POST"
        elif task_id is not None:
            allowed = "GET"
        else:
            self._error(
                method, target, nonce, 404, ErrorCode.INVALID_REQUEST, f"Unknown route {target}."
            )
            return
        if method != allowed:
            self._error(
                method,
                target,
                nonce,
                405,
                ErrorCode.INVALID_REQUEST,
                f"{method} is not allowed on {target}; use {allowed}.",
                extra_headers=(("Allow", allowed),),
            )
            return
        if target == HEALTH_PATH:
            self._respond(method, target, nonce, 200, health_document())
        elif task_id is None:
            self._submit(method, target, body, nonce)
        else:
            self._status(method, target, task_id, nonce)

    def _submit(self, method: str, target: str, body: bytes, nonce: str) -> None:
        try:
            request = TaskRequest.from_dict(decode_json_object(body))
        except ValueError as exc:
            self._error(
                method,
                target,
                nonce,
                400,
                ErrorCode.INVALID_REQUEST,
                f"Invalid task request: {exc}.",
            )
            return
        limit = self.server.config.max_execution_timeout_seconds
        if request.execution_timeout_seconds > limit:
            self._error(
                method,
                target,
                nonce,
                400,
                ErrorCode.INVALID_REQUEST,
                f"execution_timeout_seconds exceeds this server's maximum of {limit} s.",
                task_id=request.task_id,
            )
            return
        try:
            record, created = self.server.supervisor.submit(request)
        except ServerBusyError as exc:
            self._error(
                method,
                target,
                nonce,
                409,
                ErrorCode.SERVER_BUSY,
                f"Another task is running ({exc.running_task_id}); this server runs one "
                f"task at a time. Retry once it has finished.",
                task_id=request.task_id,
            )
            return
        except TaskConflictError as exc:
            self._error(
                method,
                target,
                nonce,
                409,
                ErrorCode.TASK_ID_CONFLICT,
                str(exc),
                task_id=request.task_id,
            )
            return
        self._respond(method, target, nonce, 202 if created else 200, record.to_dict())

    def _status(self, method: str, target: str, task_id: str, nonce: str) -> None:
        if not is_task_id(task_id):
            self._error(
                method,
                target,
                nonce,
                400,
                ErrorCode.INVALID_REQUEST,
                "The task id in the path is not a canonical, lowercase UUID version 4.",
            )
            return
        record = self.server.supervisor.status(task_id)
        if record is not None:
            self._respond(method, target, nonce, 200, record.to_dict())
            return
        if self.server.registry.was_seen(task_id):
            message = (
                f"This server instance no longer retains the result of task {task_id}; it "
                f"keeps the {self.server.registry.retained_tasks} most recent finished results."
            )
        else:
            message = (
                f"This server instance, started at {self.server.started_at_text}, has no record "
                f"of task {task_id}. If the task was submitted before then, the server has "
                f"restarted since and the bridge does not know its outcome."
            )
        self._error(method, target, nonce, 404, ErrorCode.UNKNOWN_TASK, message, task_id=task_id)

    def _error(
        self,
        method: str,
        target: str,
        nonce: str | None,
        status: int,
        code: ErrorCode,
        message: str,
        *,
        task_id: str | None = None,
        extra_headers: Iterable[tuple[str, str]] = (),
    ) -> None:
        document = error_document(code, message, task_id)
        self._respond(method, target, nonce, status, document, extra_headers)

    def _respond(
        self,
        method: str,
        target: str,
        nonce: str | None,
        status: int,
        document: dict[str, Any],
        extra_headers: Iterable[tuple[str, str]] = (),
    ) -> None:
        body = encode_json(document)
        self.send_response(status)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        if nonce is not None:
            signed = self.server.authenticator.sign_response(method, target, nonce, status, body)
            for name, value in signed.items():
                self.send_header(name, value)
        else:
            self.send_header(PROTOCOL_HEADER, PROTOCOL_VERSION)
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True
        self._responded = True
