"""Shared helpers for surviving flaky connectivity and DNS failures.

Every outbound call in this tool goes through :func:`with_retry`, so a dropped
VPN, a DNS hiccup, or a captive-portal style failure produces a retry and then a
readable message instead of a raw traceback.
"""
import functools
import logging
import socket
import time

import requests

logger = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF = 2.0

# Substrings that appear (via urllib3) when the failure was name resolution
# rather than a refused/unreachable connection.
_DNS_MARKERS = (
    "nameresolutionerror",
    "getaddrinfo failed",
    "name or service not known",
    "temporary failure in name resolution",
    "no address associated with hostname",
    "nodename nor servname provided",
    "failed to resolve",
)

# Exceptions worth retrying: none of them mean "the server said no".
RETRYABLE = (
    requests.ConnectionError,
    requests.Timeout,
    socket.gaierror,
    socket.timeout,
    # TransientError is appended below, once defined.
)


class NetworkError(Exception):
    """A connectivity problem the user can act on (offline, DNS, timeout)."""


class TransientError(Exception):
    """Raised by callers to mark a non-network failure as worth retrying.

    Used for responses that are flaky rather than wrong — e.g. Google Apps
    Script intermittently serving a 404 from its content-echo layer.
    """


RETRYABLE = RETRYABLE + (TransientError,)


def is_dns_failure(exc: BaseException) -> bool:
    """True if the exception looks like a name-resolution failure."""
    if isinstance(exc, socket.gaierror):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _DNS_MARKERS)


def describe(exc: BaseException, what: str) -> str:
    """Build an actionable one-line explanation for a failed network call."""
    if isinstance(exc, TransientError):
        return f"{what}: {exc}"
    if is_dns_failure(exc):
        return (
            f"Could not resolve the hostname for {what} (DNS failure). "
            "Check your internet connection and that the VPN is connected."
        )
    if isinstance(exc, requests.ReadTimeout):
        return (
            f"{what} accepted the connection but did not respond in time. "
            "It may be slow or partially down — try again shortly."
        )
    if isinstance(exc, (requests.ConnectTimeout, socket.timeout, requests.Timeout)):
        return (
            f"Timed out connecting to {what}. "
            "Check your internet connection and that the VPN is connected."
        )
    return (
        f"Could not connect to {what} ({exc.__class__.__name__}). "
        "Check your internet connection and that the VPN is connected."
    )


def with_retry(
    func,
    *,
    what: str,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff: float = DEFAULT_BACKOFF,
    retry_on_read_timeout: bool = True,
    sleep=None,
):
    """Call ``func()``, retrying transient network failures with backoff.

    Args:
        func: Zero-argument callable performing the request.
        what: Human-readable name of the target, used in log/error messages.
        attempts: Total number of tries (including the first).
        backoff: Seconds to wait before the second try; doubles each retry.
        retry_on_read_timeout: Set False for non-idempotent requests. A read
            timeout means the request *was* delivered and may still be
            executing server-side, so replaying it could duplicate the action.
            Connect-phase failures are still retried — nothing was sent.

    Raises:
        NetworkError: after the final attempt fails, or immediately for a
            non-retryable read timeout.
    """
    # Resolved at call time, not bind time, so patching net.time.sleep works.
    sleep = sleep or time.sleep
    delay = backoff
    last_exc: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return func()
        except RETRYABLE as exc:
            last_exc = exc

            if isinstance(exc, requests.ReadTimeout) and not retry_on_read_timeout:
                raise NetworkError(
                    f"{describe(exc, what)} Not retrying automatically, because the "
                    "request may already have taken effect."
                ) from exc

            if attempt == attempts:
                break

            logger.warning(
                "%s (attempt %d/%d). Retrying in %.0fs...",
                describe(exc, what),
                attempt,
                attempts,
                delay,
            )
            sleep(delay)
            delay *= 2

    raise NetworkError(
        f"{describe(last_exc, what)} Gave up after {attempts} attempts."
    ) from last_exc


def retrying(
    what: str,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff: float = DEFAULT_BACKOFF,
    retry_on_read_timeout: bool = True,
):
    """Decorator form of :func:`with_retry`.

    Wraps a whole function so every call retries transient network failures::

        @retrying("the Unity Services API")
        def fetch_environments(project_id, token):
            ...

    The wrapped function keeps its normal signature; arguments are bound at
    call time and replayed on each attempt.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return with_retry(
                lambda: func(*args, **kwargs),
                what=what,
                attempts=attempts,
                backoff=backoff,
                retry_on_read_timeout=retry_on_read_timeout,
            )
        return wrapper
    return decorator
