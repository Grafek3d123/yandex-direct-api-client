"""Кастомные исключения клиента Yandex.Direct API.

Все исключения наследуются от `YandexDirectError` и несут `request_id`
(Yandex `X-Request-Id`) — его нужно цитировать в тикетах поддержки.
"""
from __future__ import annotations

from typing import Any, Optional


class YandexDirectError(Exception):
    """Базовое исключение клиента."""

    def __init__(
        self,
        message: str,
        *,
        request_id: Optional[str] = None,
        status_code: Optional[int] = None,
        response_body: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " | ".join(parts)


class AuthError(YandexDirectError):
    """401/403 — токен невалиден, просрочен или нет доступа к клиенту."""


class RateLimitError(YandexDirectError):
    """429 — лимит запросов исчерпан даже после всех ретраев."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ReportNotReadyError(YandexDirectError):
    """Отчёт не перешёл в READY за отведённое время (долгое 202-голосирование)."""

    def __init__(
        self,
        message: str,
        *,
        report_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.report_id = report_id


class ApiError(YandexDirectError):
    """Любой другой non-2xx или body со status=ERROR."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[str] = None,
        details: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.error_code = error_code
        self.details = details


class ValidationError(YandexDirectError):
    """Ошибка на стороне клиента до отправки запроса (readonly-режим, битые аргументы)."""


__all__ = [
    "YandexDirectError",
    "AuthError",
    "RateLimitError",
    "ReportNotReadyError",
    "ApiError",
    "ValidationError",
]
