"""Retry-слой и token-bucket rate limiter для клиента Yandex.Direct.

- `TokenBucket` — проактивный rate limiter, чтобы не ловить 429.
- `request_with_retry` — обёртка вокруг одного HTTP-запроса:
  * `429 Too Many Requests` → экспоненциальный backoff с учётом `Retry-After`.
  * `202 Accepted` / `201 Created` (Reports API) → polling до готовности отчёта.
  * `401/403` → сразу пробрасываем `AuthError`.
  * Прочие non-2xx → `ApiError`.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import requests

from .config import DEFAULT_REPORT_TIMEOUT
from .exceptions import (
    ApiError,
    AuthError,
    RateLimitError,
    ReportNotReadyError,
)

logger = logging.getLogger(__name__)


class TokenBucket:
    """Простой тред-безопасный token bucket.

    :param rate: скорость пополнения, токенов в секунду.
    :param capacity: максимальный burst; по умолчанию равен `rate`.
    """

    def __init__(self, rate: float, capacity: Optional[float] = None) -> None:
        if rate <= 0:
            raise ValueError("rate должен быть > 0")
        self.rate = float(rate)
        self.capacity = float(capacity) if capacity is not None else float(rate)
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> float:
        """Заблокироваться до тех пор, пока не будет доступно `tokens`.

        Возвращает сколько секунд реально ждали.
        """
        if tokens <= 0:
            return 0.0
        waited_total = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity, self._tokens + (now - self._last) * self.rate
                )
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited_total
                need = (tokens - self._tokens) / self.rate
            time.sleep(need)
            waited_total += need


def _parse_retry_after(resp: requests.Response, default: float) -> float:
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def _parse_retry_in(resp: requests.Response, default: float) -> float:
    """Яндекс.Директ возвращает `Retry-In` / `retryIn` для Reports API."""
    for header in ("Retry-In", "retryIn", "X-Retry-In"):
        raw = resp.headers.get(header)
        if raw is None:
            continue
        try:
            return max(0.0, float(raw))
        except ValueError:
            return default
    return default


def _extract_request_id(resp: requests.Response) -> Optional[str]:
    return (
        resp.headers.get("X-Request-Id")
        or resp.headers.get("X-RequestId")
        or resp.headers.get("requestId")
    )


def request_with_retry(
    do_request: Callable[[], requests.Response],
    *,
    max_retries: int,
    bucket: TokenBucket,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    report: bool = False,
    report_timeout: float = DEFAULT_REPORT_TIMEOUT,
) -> requests.Response:
    """Выполнить HTTP-запрос с retry и rate limiting.

    :param do_request: callable, делающий один HTTP-запрос и возвращающий
        `requests.Response`.
    :param max_retries: максимум повторов при 429 и 202.
    :param bucket: общий token bucket для throttling-а запросов.
    :param base_delay: базовая задержка backoff при 429 без `Retry-After`.
    :param max_delay: потолок одной задержки.
    :param report: если True — трактовать 202/201 как "отчёт в очереди"
        и поллить до готовности с `report_timeout`.
    :param report_timeout: максимум секунд ожидания готовности отчёта.
    :return: успешный `Response` (2xx).
    :raises AuthError: 401/403.
    :raises RateLimitError: 429 после исчерпания ретраев.
    :raises ReportNotReadyError: отчёт не готов за `report_timeout`.
    :raises ApiError: остальные non-2xx.
    """
    started = time.monotonic()
    attempt = 0

    while True:
        bucket.acquire()
        resp = do_request()
        status = resp.status_code
        req_id = _extract_request_id(resp)

        # Успешный ответ
        if 200 <= status < 300 and not (report and status in (201, 202)):
            return resp

        # Auth
        if status in (401, 403):
            raise AuthError(
                f"Ошибка авторизации: {resp.text[:300]}",
                request_id=req_id,
                status_code=status,
                response_body=resp.text,
            )

        # Rate limit (429) — retry с backoff
        if status == 429:
            if attempt >= max_retries:
                raise RateLimitError(
                    "Превышен лимит запросов (429) после всех повторов",
                    retry_after=_parse_retry_after(resp, default=base_delay),
                    request_id=req_id,
                    status_code=status,
                    response_body=resp.text,
                )
            wait = min(
                max_delay,
                _parse_retry_after(resp, default=base_delay * (2 ** attempt)),
            )
            logger.warning(
                "429 Too Many Requests, retry %d/%d через %.1fс",
                attempt + 1,
                max_retries,
                wait,
            )
            time.sleep(wait)
            attempt += 1
            continue

        # Reports polling (201/202)
        if report and status in (201, 202):
            elapsed = time.monotonic() - started
            if elapsed >= report_timeout:
                raise ReportNotReadyError(
                    f"Отчёт не готов за {report_timeout:.0f} секунд",
                    report_id=resp.headers.get("Report-Id"),
                    request_id=req_id,
                    status_code=status,
                    response_body=resp.text,
                )
            wait = _parse_retry_in(resp, default=min(10.0, report_timeout - elapsed))
            logger.info(
                "Отчёт в очереди (HTTP %d), следующий poll через %.1fс",
                status,
                wait,
            )
            time.sleep(wait)
            continue

        # Любая другая ошибка — не retryable
        raise ApiError(
            f"API вернул HTTP {status}: {resp.text[:300]}",
            request_id=req_id,
            status_code=status,
            response_body=resp.text,
        )


__all__ = [
    "TokenBucket",
    "request_with_retry",
]
