"""Unit-тесты для retry-слоя и token bucket."""
from __future__ import annotations

import time

import pytest
import requests
import responses

from yandex_direct_api_client.exceptions import (
    ApiError,
    AuthError,
    RateLimitError,
)
from yandex_direct_api_client.retry import TokenBucket, request_with_retry

URL = "https://api.direct.yandex.com/json/v5/campaigns/"


def test_token_bucket_blocks_excess_calls() -> None:
    bucket = TokenBucket(rate=20.0, capacity=2.0)
    # burst 2 — мгновенно
    start = time.monotonic()
    bucket.acquire()
    bucket.acquire()
    assert time.monotonic() - start < 0.05
    # 3-й ждёт ~0.05с (rate=20)
    bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.04


def test_token_bucket_invalid_rate() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate=0)


@responses.activate
def test_request_with_retry_returns_200() -> None:
    responses.add(responses.POST, URL, json={"result": {}}, status=200)
    bucket = TokenBucket(rate=1000.0)
    resp = request_with_retry(
        lambda: requests.post(URL), max_retries=2, bucket=bucket
    )
    assert resp.status_code == 200


@responses.activate
def test_request_with_retry_retries_429_then_succeeds() -> None:
    responses.add(
        responses.POST, URL, body="too many", status=429,
        headers={"Retry-After": "0"},
    )
    responses.add(responses.POST, URL, json={"result": {}}, status=200)
    bucket = TokenBucket(rate=1000.0)
    resp = request_with_retry(
        lambda: requests.post(URL), max_retries=2, bucket=bucket, base_delay=0.01
    )
    assert resp.status_code == 200
    assert len(responses.calls) == 2


@responses.activate
def test_request_with_retry_raises_after_max_retries_429() -> None:
    for _ in range(3):
        responses.add(
            responses.POST, URL, body="too many", status=429,
            headers={"Retry-After": "0"},
        )
    bucket = TokenBucket(rate=1000.0)
    with pytest.raises(RateLimitError) as exc:
        request_with_retry(
            lambda: requests.post(URL), max_retries=2, bucket=bucket,
            base_delay=0.01,
        )
    assert exc.value.status_code == 429


@responses.activate
def test_request_with_retry_auth_error_no_retry() -> None:
    responses.add(responses.POST, URL, body="forbidden", status=403)
    bucket = TokenBucket(rate=1000.0)
    with pytest.raises(AuthError):
        request_with_retry(
            lambda: requests.post(URL), max_retries=5, bucket=bucket
        )
    assert len(responses.calls) == 1


@responses.activate
def test_request_with_retry_generic_api_error() -> None:
    responses.add(responses.POST, URL, body="bad", status=400)
    bucket = TokenBucket(rate=1000.0)
    with pytest.raises(ApiError):
        request_with_retry(
            lambda: requests.post(URL), max_retries=5, bucket=bucket
        )
    assert len(responses.calls) == 1


@responses.activate
def test_request_with_retry_report_polling_202_then_200() -> None:
    responses.add(
        responses.POST, URL, body="queued", status=202,
        headers={"Retry-In": "0"},
    )
    responses.add(responses.POST, URL, body="ok", status=200)
    bucket = TokenBucket(rate=1000.0)
    resp = request_with_retry(
        lambda: requests.post(URL),
        max_retries=5,
        bucket=bucket,
        report=True,
        report_timeout=5.0,
    )
    assert resp.status_code == 200
    assert len(responses.calls) == 2


@responses.activate
def test_request_with_retry_report_timeout() -> None:
    for _ in range(10):
        responses.add(
            responses.POST, URL, body="queued", status=202,
            headers={"Retry-In": "1"},
        )
    bucket = TokenBucket(rate=1000.0)
    with pytest.raises(Exception) as exc:
        request_with_retry(
            lambda: requests.post(URL),
            max_retries=5,
            bucket=bucket,
            report=True,
            report_timeout=0.05,
        )
    # ReportNotReadyError импортирован из exceptions
    from yandex_direct_api_client.exceptions import ReportNotReadyError
    assert isinstance(exc.value, ReportNotReadyError)


@responses.activate
def test_request_with_retry_extracts_request_id() -> None:
    responses.add(
        responses.POST, URL, body="oops", status=400,
        headers={"X-Request-Id": "abc-123"},
    )
    bucket = TokenBucket(rate=1000.0)
    with pytest.raises(ApiError) as exc:
        request_with_retry(
            lambda: requests.post(URL), max_retries=0, bucket=bucket
        )
    assert exc.value.request_id == "abc-123"
