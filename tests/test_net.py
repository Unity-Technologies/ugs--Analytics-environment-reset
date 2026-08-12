"""Tests for net.py — retry and error-classification helpers."""
import socket
from unittest.mock import patch

import pytest
import requests

from net import (
    NetworkError,
    TransientError,
    describe,
    is_dns_failure,
    retrying,
    with_retry,
)


def _no_sleep(_seconds):
    """Stand-in for time.sleep so retry tests run instantly."""


class TestIsDnsFailure:

    def test_gaierror_is_dns(self):
        assert is_dns_failure(socket.gaierror(11001, "getaddrinfo failed"))

    def test_urllib3_name_resolution_message_is_dns(self):
        exc = requests.ConnectionError(
            "HTTPSConnectionPool(host='services.unity.com', port=443): "
            "Max retries exceeded (Caused by NameResolutionError(...))"
        )
        assert is_dns_failure(exc)

    def test_connection_refused_is_not_dns(self):
        assert not is_dns_failure(requests.ConnectionError("Connection refused"))


class TestDescribe:

    def test_dns_message_mentions_resolution_and_vpn(self):
        msg = describe(socket.gaierror("getaddrinfo failed"), "Zendesk")
        assert "resolve" in msg.lower()
        assert "VPN" in msg
        assert "Zendesk" in msg

    def test_read_timeout_distinguished_from_connect_timeout(self):
        read = describe(requests.ReadTimeout("slow"), "the API")
        connect = describe(requests.ConnectTimeout("nope"), "the API")
        assert "did not respond in time" in read
        assert "Timed out connecting" in connect

    def test_transient_error_passes_message_through(self):
        msg = describe(TransientError("HTTP 404 from the endpoint."), "Sheets")
        assert "HTTP 404" in msg
        assert "Sheets" in msg


class TestWithRetry:

    def test_returns_value_without_retrying_on_success(self):
        calls = []

        def func():
            calls.append(1)
            return "ok"

        assert with_retry(func, what="the API", sleep=_no_sleep) == "ok"
        assert len(calls) == 1

    def test_recovers_after_transient_failures(self):
        calls = []

        def func():
            calls.append(1)
            if len(calls) < 3:
                raise requests.ConnectionError("NameResolutionError")
            return "ok"

        assert with_retry(func, what="the API", sleep=_no_sleep) == "ok"
        assert len(calls) == 3

    def test_raises_network_error_after_exhausting_attempts(self):
        def func():
            raise requests.ConnectionError("Connection refused")

        with pytest.raises(NetworkError, match="Gave up after 3 attempts"):
            with_retry(func, what="the API", sleep=_no_sleep)

    def test_retries_transient_error_from_caller(self):
        calls = []

        def func():
            calls.append(1)
            if len(calls) < 2:
                raise TransientError("HTTP 404 from the Apps Script endpoint.")
            return "ok"

        assert with_retry(func, what="Sheets", sleep=_no_sleep) == "ok"
        assert len(calls) == 2

    def test_does_not_retry_http_errors(self):
        """A 403 means the server said no — replaying it will not help."""
        calls = []

        def func():
            calls.append(1)
            raise requests.HTTPError("403 Forbidden")

        with pytest.raises(requests.HTTPError):
            with_retry(func, what="the API", sleep=_no_sleep)
        assert len(calls) == 1

    def test_read_timeout_not_replayed_when_disabled(self):
        """Non-idempotent calls must not resend a request that was delivered."""
        calls = []

        def func():
            calls.append(1)
            raise requests.ReadTimeout("timed out")

        with pytest.raises(NetworkError, match="may already have taken effect"):
            with_retry(
                func,
                what="the auto-provisioning service",
                retry_on_read_timeout=False,
                sleep=_no_sleep,
            )
        assert len(calls) == 1

    def test_connect_failure_still_retried_when_read_timeout_disabled(self):
        """Nothing was sent on a connect failure, so replaying is safe."""
        calls = []

        def func():
            calls.append(1)
            if len(calls) < 2:
                raise requests.ConnectionError("NameResolutionError")
            return "deleted"

        result = with_retry(
            func,
            what="the auto-provisioning service",
            retry_on_read_timeout=False,
            sleep=_no_sleep,
        )
        assert result == "deleted"
        assert len(calls) == 2

    def test_backoff_doubles_between_attempts(self):
        delays = []

        def func():
            raise requests.ConnectionError("boom")

        with pytest.raises(NetworkError):
            with_retry(
                func, what="the API", attempts=4, backoff=1.0, sleep=delays.append
            )
        assert delays == [1.0, 2.0, 4.0]


class TestRetryingDecorator:

    def test_preserves_signature_and_replays_arguments(self):
        calls = []

        @retrying("the API", backoff=0)
        def fetch(project_id, token):
            calls.append((project_id, token))
            if len(calls) < 2:
                raise requests.ConnectionError("getaddrinfo failed")
            return ["env"]

        with patch("net.time.sleep"):
            assert fetch("proj-123", token="tok") == ["env"]
        assert calls == [("proj-123", "tok"), ("proj-123", "tok")]

    def test_preserves_function_metadata(self):
        @retrying("the API")
        def fetch_environments(project_id):
            """Docstring survives."""

        assert fetch_environments.__name__ == "fetch_environments"
        assert fetch_environments.__doc__ == "Docstring survives."
