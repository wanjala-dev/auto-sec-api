"""Unit tests for the retry_with_backoff utility."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from components.payments.application.utils.retry import is_transient, retry_with_backoff


class TestIsTransient:
    def test_connection_error_is_transient(self):
        assert is_transient(ConnectionError("refused"))

    def test_timeout_error_is_transient(self):
        assert is_transient(TimeoutError("timed out"))

    def test_os_error_is_transient(self):
        assert is_transient(OSError("network unreachable"))

    def test_value_error_is_not_transient(self):
        assert not is_transient(ValueError("bad input"))

    def test_runtime_error_is_not_transient(self):
        assert not is_transient(RuntimeError("unexpected"))


class TestRetryWithBackoff:
    def test_success_on_first_try(self):
        fn = MagicMock(return_value="ok")
        result = retry_with_backoff(fn, max_attempts=3, base_delay=0)
        assert result == "ok"
        assert fn.call_count == 1

    def test_retries_on_transient_then_succeeds(self):
        fn = MagicMock(side_effect=[ConnectionError("fail"), ConnectionError("fail"), "ok"])
        result = retry_with_backoff(fn, max_attempts=3, base_delay=0)
        assert result == "ok"
        assert fn.call_count == 3

    def test_raises_after_max_attempts(self):
        fn = MagicMock(side_effect=ConnectionError("always fails"))
        with pytest.raises(ConnectionError, match="always fails"):
            retry_with_backoff(fn, max_attempts=3, base_delay=0)
        assert fn.call_count == 3

    def test_does_not_retry_non_transient(self):
        fn = MagicMock(side_effect=ValueError("bad input"))
        with pytest.raises(ValueError, match="bad input"):
            retry_with_backoff(fn, max_attempts=3, base_delay=0)
        assert fn.call_count == 1

    def test_on_retry_callback_called(self):
        fn = MagicMock(side_effect=[ConnectionError("fail"), "ok"])
        callback = MagicMock()
        retry_with_backoff(fn, max_attempts=3, base_delay=0, on_retry=callback)
        callback.assert_called_once()
        exc, attempt, _delay = callback.call_args[0]
        assert isinstance(exc, ConnectionError)
        assert attempt == 1

    def test_passes_args_and_kwargs(self):
        fn = MagicMock(return_value="ok")
        retry_with_backoff(fn, "a", "b", key="val", max_attempts=1, base_delay=0)
        fn.assert_called_once_with("a", "b", key="val")
