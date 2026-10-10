"""HTTP-транспорт: POST-запросы к API с retry, rate limiting и error handling.

Версия API — часть адреса: ``{api_url}/{api_version}/{service}/``. По умолчанию
используется `v5`; версия передаётся конкретным вызовом (например, `v501` для
Единой перфоманс-кампании) и не протекает в публичные методы сервисов.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from .config import (
    DEFAULT_API_VERSION,
    DEFAULT_REPORT_TIMEOUT,
    USER_AGENT,
    Settings,
)
from .exceptions import ApiError, ValidationError
from .logs import get_logger, log_bodies_enabled, redact, safe_extra
from .retry import TokenBucket, extract_request_id, request_with_retry

logger = get_logger(__name__)

#: Известные суффиксы версии API в базовом URL. Нужны, чтобы корректно менять
#: версию запроса, не ломая пользователей, которые задают `api_url` целиком
#: (например, `https://api.direct.yandex.com/json/v5`).
_VERSION_SUFFIXES = ("/json/v501", "/json/v5", "/v501", "/v5")


def _version_path(version: str) -> str:
    """Привести версию API к сегменту пути.

    Допустимы обе записи: полный сегмент (``json/v501``) и короткая
    (``v501``) — короткая дополняется префиксом ``json/``, как в адресе
    сервисов Yandex.Direct.

    :param version: версия API (``v5``, ``v501``, ``json/v501``).
    :return: сегмент пути для URL.
    """
    value = version.strip("/")
    if value.startswith("json/"):
        return value
    if value.startswith("v"):
        return f"json/{value}"
    return value


def _split_version(url: str) -> "tuple[str, Optional[str]]":
    """Отделить базовый URL от версии API, если она в него входит.

    :param url: базовый URL, возможно с версией на конце.
    :return: пара (база, версия или None).
    """
    base = url.rstrip("/")
    lowered = base.lower()
    for suffix in _VERSION_SUFFIXES:
        if lowered.endswith(suffix):
            return base[: -len(suffix)], base[-len(suffix) :]
    return base, None


class Transport:
    """Низкоуровневый HTTP-транспорт для Yandex.Direct API.

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

        self._settings = settings
        self._report_timeout = report_timeout
        self._bucket = TokenBucket(rate=settings.rate_limit_rps)
        self._session = session or requests.Session()
        self._session_owned = session is None
        self._closed = False
        self._last_request_id: Optional[str] = None
        self._base_url, self._url_version = _split_version(settings.api_url)

        headers: Dict[str, str] = {
            "Authorization": f"Bearer {settings.token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": USER_AGENT,
            # Справочники возвращают названия на языке запроса; по умолчанию —
            # русский (актуально для GeoRegions, AudienceInterests и т. п.).
            "Accept-Language": settings.accept_language,
        }
        # Client-Login обязателен только для агентского доступа. Прямому
        # рекламодателю заголовок не нужен — и Яндекс его не требует.
        if settings.client_login:
            headers["Client-Login"] = settings.client_login
        self._session.headers.update(headers)

    @property
    def api_url(self) -> str:
        """Базовый URL вместе с версией API по умолчанию."""
        return f"{self._base_url}/{_version_path(self.api_version)}"

    @property
    def api_version(self) -> str:
        """Версия API, используемая по умолчанию для всех вызовов."""
        return self._settings.api_version or self._url_version or DEFAULT_API_VERSION

    @property
    def last_request_id(self) -> Optional[str]:
        """`X-Request-Id` последнего ответа (None, если сервер его не прислал)."""
        return self._last_request_id

    @property
    def validate_enabled(self) -> bool:
        """Включена ли пред-отправочная валидация payload'ов."""
        return self._settings.validate

    @property
    def settings(self) -> Settings:
        """Настройки клиента (доступны сервисам для предохранителей)."""
        return self._settings

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
        report_timeout: Optional[float] = None,
        api_version: Optional[str] = None,
    ) -> requests.Response:
        """Выполнить POST-запрос к API-сервису.

        :param service: имя сервиса (campaigns, ads, reports, ...).
        :param payload: JSON-тело запроса.
        :param report: True для Reports API (polling 201/202).
        :param report_timeout: override таймаута ожидания отчёта для
            этого вызова (по умолчанию — из настроек клиента).
        :param api_version: версия API для этого вызова (None — из настроек).
        """
        version = _version_path(api_version or self.api_version)
        url = f"{self._base_url}/{version}/{service}/"
        method = str(payload.get("method", ""))
        log_ctx = safe_extra(
            service=service,
            api_version=version,
            method=method,
            client_login=self._settings.client_login or "-",
            readonly=self._settings.readonly,
        )

        if log_bodies_enabled():
            logger.debug(
                "direct request payload: %s",
                redact(payload),
                extra=log_ctx,
            )
        def _do() -> requests.Response:
            return self._session.post(
                url, json=payload, timeout=self._settings.timeout
            )

        started = time.monotonic()
        resp = request_with_retry(
            _do,
            max_retries=self._settings.max_retries,
            bucket=self._bucket,
            report=report,
            report_timeout=report_timeout or self._report_timeout,
            log_ctx=log_ctx,
        )
        self._last_request_id = extract_request_id(resp)
        duration_ms = int((time.monotonic() - started) * 1000)
        status = resp.status_code
        event = {
            **log_ctx,
            "request_id": self._last_request_id or "-",
            "status_code": status,
            "duration_ms": duration_ms,
        }
        if method.lower() == "get":
            logger.debug(
                "direct response %s: status=%s duration_ms=%s",
                service,
                status,
                duration_ms,
                extra=event,
            )
        else:
            logger.info(
                "direct mutation %s/%s: status=%s duration_ms=%s",
                service,
                method,
                status,
                duration_ms,
                extra=event,
            )
        if log_bodies_enabled():
            logger.debug("direct response body: %s", redact(resp.text[:4000]), extra=event)
        return resp

    def post_result(
        self,
        service: str,
        payload: Dict[str, Any],
        *,
        report: bool = False,
        api_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST + разбор error-блока. Возвращает result или бросает ApiError."""
        resp = self.post(service, payload, report=report, api_version=api_version)
        return self._check_body_errors(resp)

    @staticmethod
    def _check_body_errors(resp: requests.Response) -> Dict[str, Any]:
        """Проверить JSON-ответ на error-блок и вернуть result (или {})."""
        request_id = extract_request_id(resp)
        try:
            data: Dict[str, Any] = resp.json()
        except ValueError as e:
            raise ApiError(
                f"API вернул не-JSON: {resp.text[:200]}",
                request_id=request_id,
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
                request_id=request_id,
                status_code=resp.status_code,
                response_body=data,
            )
        result: Dict[str, Any] = data.get("result") or {}
        if isinstance(result, dict) and result.get("status") == "ERROR":
            raise ApiError(
                "API вернул status=ERROR в result",
                request_id=request_id,
                status_code=resp.status_code,
                response_body=data,
            )
        return result


__all__ = ["Transport"]
