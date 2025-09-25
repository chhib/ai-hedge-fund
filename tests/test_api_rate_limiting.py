from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from src.data.borsdata_client import BorsdataAPIError, BorsdataClient, RateLimiter


class DummyResponse:
    """Lightweight stand-in for `requests.Response` objects."""

    def __init__(
        self,
        *,
        status_code: int,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = headers or {}
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._json_data


class StubLimiter:
    """Simple limiter stub tracking acquire calls."""

    def __init__(self, period_seconds: float) -> None:
        self.period_seconds = period_seconds
        self.calls = 0

    def acquire(self) -> None:
        self.calls += 1


def test_rate_limiter_waits_when_window_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = {"value": 0.0}
    sleeps: list[float] = []

    def monotonic() -> float:
        return fake_time["value"]

    def fake_sleep(duration: float) -> None:
        sleeps.append(duration)
        fake_time["value"] += duration

    monkeypatch.setattr("src.data.borsdata_client.time.monotonic", monotonic)

    limiter = RateLimiter(max_calls=2, period_seconds=5.0, sleep_func=fake_sleep)

    fake_time["value"] = 0.0
    limiter.acquire()
    fake_time["value"] = 0.1
    limiter.acquire()
    fake_time["value"] = 0.2
    limiter.acquire()

    assert sleeps, "Limiter should have requested a sleep when capacity is exhausted"
    assert pytest.approx(sleeps[0], rel=1e-6) == 4.8


def test_request_retries_on_429_and_honors_retry_after() -> None:
    limiter = StubLimiter(period_seconds=10.0)
    sleep_calls: list[float] = []

    def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    responses = [
        DummyResponse(status_code=429, headers={"Retry-After": "2"}, text="Too many"),
        DummyResponse(status_code=200, json_data={"ok": True}),
    ]

    session = Mock()
    session.request.side_effect = responses

    client = BorsdataClient(
        session=session,
        rate_limiter=limiter,
        sleep_func=fake_sleep,
        max_retries=3,
    )

    result = client._request("GET", "/v1/test", api_key="token")

    assert result == {"ok": True}
    assert limiter.calls == 2
    assert session.request.call_count == 2
    assert sleep_calls == [2.0]

    method, url = session.request.call_args.args
    params = session.request.call_args.kwargs.get("params")
    assert method == "GET"
    assert url.endswith("/v1/test")
    assert params["authKey"] == "token"


def test_request_uses_limiter_period_when_retry_after_invalid() -> None:
    limiter = StubLimiter(period_seconds=5.5)
    sleep_calls: list[float] = []

    def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    session = Mock()
    session.request.side_effect = [
        DummyResponse(status_code=429, headers={"Retry-After": "not-a-number"}, text="Slow down"),
        DummyResponse(status_code=200, json_data={"done": True}),
    ]

    client = BorsdataClient(
        session=session,
        rate_limiter=limiter,
        sleep_func=fake_sleep,
        max_retries=1,
    )

    result = client._request("GET", "/v1/other", api_key="token")

    assert result == {"done": True}
    assert limiter.calls == 2
    assert sleep_calls == [pytest.approx(5.5)]


def test_request_raises_after_retry_budget_exhausted() -> None:
    limiter = StubLimiter(period_seconds=10.0)

    session = Mock()
    session.request.side_effect = [
        DummyResponse(status_code=429, text="Too many"),
        DummyResponse(status_code=429, text="Still too many"),
        DummyResponse(status_code=429, text="Again"),
    ]

    client = BorsdataClient(
        session=session,
        rate_limiter=limiter,
        sleep_func=lambda _: None,
        max_retries=2,
    )

    with pytest.raises(BorsdataAPIError) as excinfo:
        client._request("GET", "/v1/exhaust", api_key="token")

    assert "429" in str(excinfo.value)
    assert limiter.calls == 3
    assert session.request.call_count == 3


def test_request_raises_on_non_429_error() -> None:
    limiter = StubLimiter(period_seconds=10.0)
    session = Mock()
    session.request.return_value = DummyResponse(status_code=500, text="Server error")

    client = BorsdataClient(
        session=session,
        rate_limiter=limiter,
        sleep_func=lambda _: None,
    )

    with pytest.raises(BorsdataAPIError) as excinfo:
        client._request("GET", "/v1/failure", api_key="token")

    assert "500" in str(excinfo.value)
    assert limiter.calls == 1
    assert session.request.call_count == 1
