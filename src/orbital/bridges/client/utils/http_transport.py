"""Helpers of HttpTransport: URL opener, and classification of failures and unverified replies."""

from __future__ import annotations

import http.client
import urllib.error
import urllib.request

from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.error_detail import ErrorDetail

MAX_RESPONSE_BYTES = 64 * 1024 * 1024
EXCERPT_CHARS = 500
USER_AGENT = "orbital-bridge/1"


def build_opener(use_env_proxy: bool) -> urllib.request.OpenerDirector:
    """An opener for plain HTTP that never follows redirects.

    With *use_env_proxy*, ``HTTP_PROXY`` / ``NO_PROXY`` from the environment apply, as inside a
    sandbox. Redirects are not followed, so a signed request is never re-sent elsewhere; a
    redirect surfaces as an unverified response.
    """
    opener = urllib.request.OpenerDirector()
    proxy = urllib.request.ProxyHandler() if use_env_proxy else urllib.request.ProxyHandler({})
    for handler in (
        proxy,
        urllib.request.HTTPHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def excerpt(body: bytes) -> str:
    """At most :data:`EXCERPT_CHARS` characters of *body*, whitespace collapsed, for messages."""
    text = " ".join(body.decode("utf-8", errors="replace").split())
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS] + " ..."


def describe(error: object) -> str:
    """``TypeName: text`` of an exception (or a plain reason string)."""
    if isinstance(error, BaseException):
        text = str(error)
        return f"{type(error).__name__}: {text}" if text else type(error).__name__
    return str(error)


def classify_exception(exc: BaseException) -> ErrorDetail:
    """Map a network-level failure to ``connection_failed``, ``connection_interrupted`` or
    ``request_timeout`` (all ``communication_error``)."""
    reason: object = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, TimeoutError):
        return ErrorDetail(
            ErrorCode.REQUEST_TIMEOUT,
            "No HTTP response from the bridge within the request timeout.",
        )
    if isinstance(
        reason,
        ConnectionResetError | ConnectionAbortedError | BrokenPipeError | http.client.HTTPException,
    ):
        return ErrorDetail(
            ErrorCode.CONNECTION_INTERRUPTED,
            f"The connection to the bridge was interrupted ({describe(reason)}).",
        )
    return ErrorDetail(
        ErrorCode.CONNECTION_FAILED, f"Could not connect to the bridge ({describe(reason)})."
    )


def classify_unverified(status: int, body: bytes) -> ErrorDetail:
    """Map a reply whose signature does not verify to a ``communication_error`` detail.

    Nothing in such a reply is trusted: its text is only quoted, labelled as unverified, and a
    code it claims is never used.
    """
    text = excerpt(body) or "(empty body)"
    if status == 401:
        return ErrorDetail(
            ErrorCode.UNVERIFIED_AUTH_REJECTION,
            "Received HTTP 401 whose signature could not be verified with the local key. The "
            "most likely cause is that the two sides use different ORBITAL_BRIDGE_KEY values; "
            "an intermediary may also have answered. The task's state is not confirmed (it was "
            f"most likely not accepted). Unverified response text: {text}",
        )
    if status == 403:
        return ErrorDetail(
            ErrorCode.NETWORK_POLICY_BLOCKED,
            "Received HTTP 403 without a valid bridge signature: the sandbox proxy appears to "
            "have refused the request; check the network policy for the bridge address. "
            f"Unverified proxy text: {text}",
        )
    if status in (502, 503, 504):
        return ErrorDetail(
            ErrorCode.GATEWAY_ERROR,
            f"Received HTTP {status} without a valid bridge signature: an intermediary reported "
            "a gateway failure (is the bridge server running, and is its port published?). "
            f"Unverified text: {text}",
        )
    return ErrorDetail(
        ErrorCode.RESPONSE_UNVERIFIED,
        f"Received HTTP {status} without a valid bridge signature, so it is not trusted. "
        f"Unverified text: {text}",
    )
