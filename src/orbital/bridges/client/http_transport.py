"""One signed HTTP exchange with the bridge server."""

from __future__ import annotations

import http.client
import urllib.error
import urllib.request

from orbital.bridges.auth.message_authenticator import MessageAuthenticator
from orbital.bridges.auth.utils import NONCE_HEADER
from orbital.bridges.client.client_config import ClientConfig
from orbital.bridges.client.utils.http_transport import (
    MAX_RESPONSE_BYTES,
    USER_AGENT,
    build_opener,
    classify_exception,
    classify_unverified,
)
from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.error_detail import ErrorDetail
from orbital.bridges.utils import JSON_CONTENT_TYPE


class HttpTransport:
    """Signs one request, sends it (through the environment's proxy by default) and verifies
    the reply.

    :meth:`exchange` returns ``(status, body)`` only for a reply whose signature verifies;
    every network failure and every unverified reply becomes an :class:`ErrorDetail` of the
    ``communication_error`` category instead. It never raises for those outcomes.
    """

    def __init__(
        self, config: ClientConfig, *, authenticator: MessageAuthenticator | None = None
    ) -> None:
        self._config = config
        self._authenticator = (
            authenticator if authenticator is not None else MessageAuthenticator(config.key)
        )
        self._opener = build_opener(config.use_env_proxy)

    def exchange(
        self, method: str, path: str, body: bytes = b""
    ) -> tuple[int, bytes] | ErrorDetail:
        """Send ``method path`` with *body*; return the verified ``(status, body)`` or an error."""
        headers = self._authenticator.sign_request(method, path, body)
        nonce = headers[NONCE_HEADER]
        headers["User-Agent"] = USER_AGENT
        headers["Accept"] = "application/json"
        data = None
        if method == "POST":
            headers["Content-Type"] = JSON_CONTENT_TYPE
            data = body
        # The URL is validated by ClientConfig to be http://host[:port]; no other scheme is used.
        request = urllib.request.Request(  # noqa: S310
            self._config.url + path, data=data, headers=headers, method=method
        )
        try:
            with self._opener.open(
                request, timeout=self._config.request_timeout_seconds
            ) as response:
                status = response.status
                reply_headers = dict(response.headers.items())
                reply_body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            status = error.code
            reply_headers = dict(error.headers.items()) if error.headers is not None else {}
            try:
                reply_body = error.read(MAX_RESPONSE_BYTES + 1)
            except (OSError, http.client.HTTPException) as exc:
                return classify_exception(exc)
            finally:
                error.close()
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            return classify_exception(exc)
        if len(reply_body) > MAX_RESPONSE_BYTES:
            return ErrorDetail(
                ErrorCode.RESPONSE_UNVERIFIED,
                f"The reply (HTTP {status}) exceeds {MAX_RESPONSE_BYTES} bytes and was not read "
                f"in full, so it cannot be verified.",
            )
        if not self._authenticator.verify_response(
            method, path, nonce, status, reply_body, reply_headers
        ):
            return classify_unverified(status, reply_body)
        return status, reply_body
