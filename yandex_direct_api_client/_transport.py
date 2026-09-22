"""HTTP-транспорт: POST-запросы к API с retry, rate limiting и error handling."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

from .config import DEFAULT_REPORT_TIMEOUT, USER_AGENT, Settings
from .exceptions import ApiError, ValidationError
from .retry import TokenBucket, request_with_retry

logger = logging.getLogger(__name__)


class Transport:
    """Низкоуровневый HTTP-транспорт для Yandex.Direct API v5.

    Инкапсулирует `requests.Session`, retry, token-bucket rate limiting
    и разбор error-блоков в JSON-ответах.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        session: Optional[requests.Session] = None,
        report_timeout: float = DEFAULT_REPORT_TIMEOUT,
    ) -> None:
        if not settings.token:
            raise ValidationError("token не задан")
        if not settings.client_login:
            raise ValidationError("client_login не задан")

        self._settings = settings
        self._report_timeout = report_timeout
        self._bucket = TokenBucket(rate=settings.rate_limit_rps)
        self._session = session or requests.Session()
        self._session_owned = session is None
        self._closed = False

        self._session.headers.update(
            {
                "Authorization": f"Bearer {settings.token}",
                "Content-Type": "application/json; charset=utf-8",
                "Client-Login": settings.client_login,
                "User-Agent": USER_AGENT,
            }
        )

    @property
    def api_url(self) -> str:
        return self._settings.api_url.rstrip("/")

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._session_owned:
            self._session.close()

    def post(
        self,
        service: str,
        payload: Dict[str, Any],
        *,
        report: bool = False,
    ) -> requests.Response:
        """Выполнить POST-запрос к API-сервису.

        :param service: имя сервиса (campaigns, ads, reports, ...).
        :param payload: JSON-тело запроса.
        :param report: True для Reports API (polling 201/202).
        """
        url = f"{self.api_url}/{service}/"

        def _do() -> requests.Response:
            return self._session.post(
                url, json=payload, timeout=self._settings.timeout
            )

        return request_with_retry(
            _do,
            max_retries=self._settings.max_retries,
            bucket=self._bucket,
            report=report,
            report_timeout=self._report_timeout,
        )

    def post_result(
        self,
        service: str,
        payload: Dict[str, Any],
        *,
        report: bool = False,
    ) -> Dict[str, Any]:
        """POST + разбор error-блока. Возвращает result или бросает ApiError."""
        resp = self.post(service, payload, report=report)
        return self._check_body_errors(resp)

    @staticmethod
    def _check_body_errors(resp: requests.Response) -> Dict[str, Any]:
        """Проверить JSON-ответ на error-блок и вернуть result (или {})."""
        try:
            data: Dict[str, Any] = resp.json()
        except ValueError as e:
            raise ApiError(
                f"API вернул не-JSON: {resp.text[:200]}",
                status_code=resp.status_code,
                response_body=resp.text,
            ) from e

        if "error" in data:
            err = data["error"] or {}
            raise ApiError(
                f"API error: {err.get('error_string') or err.get('error_code')}",
                error_code=(
                    str(err.get("error_code")) if err.get("error_code") else None
                ),
                details=err.get("details"),
                status_code=resp.status_code,
                response_body=data,
            )
        result: Dict[str, Any] = data.get("result") or {}
        if isinstance(result, dict) and result.get("status") == "ERROR":
            raise ApiError(
                "API вернул status=ERROR в result",
                status_code=resp.status_code,
                response_body=data,
            )
        return result


__all__ = ["Transport"]
