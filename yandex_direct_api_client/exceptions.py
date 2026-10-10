"""Кастомные исключения клиента Yandex.Direct API.

Все исключения наследуются от `YandexDirectError` и несут `request_id`
(Yandex `X-Request-Id`) — его нужно цитировать в тикетах поддержки.

Ошибки классифицируются (F-0.4), чтобы вызывающий код и retry-слой отличали
временные сбои от постоянных:

- ``auth`` — 401/403: токен невалиден или нет доступа к клиенту; повторы
  бессмысленны;
- ``rate_limit`` — 429: временная перегрузка, повторять с ``Retry-After``;
- ``retryable`` — 5xx и прочие временные сбои;
- ``validation`` — 400 с кодом ошибки: некорректный запрос, повтор не поможет;
- ``fatal`` — любой другой 4xx: постоянная ошибка конкретного запроса.

Все поля `response_body`/`details` и текст исключения проходят через redactor,
поэтому OAuth-токен не может попасть в лог, `repr` или печать исключения.
"""
from __future__ import annotations

from typing import Any, Optional

from .logs import redact, redact_text

#: Категории ошибок.
KIND_AUTH = "auth"
KIND_RATE_LIMIT = "rate_limit"
KIND_RETRYABLE = "retryable"
KIND_VALIDATION = "validation"
KIND_FATAL = "fatal"
KIND_OTHER = "other"


def classify_error(status_code: Optional[int]) -> str:
    """Определить категорию ошибки по HTTP-коду ответа.

    :param status_code: HTTP-статус ответа (None — неизвестно).
    :return: одна из констант `KIND_*`.
    """
    if status_code is None:
        return KIND_OTHER
    if status_code in (401, 403):
        return KIND_AUTH
    if status_code == 429:
        return KIND_RATE_LIMIT
    if status_code >= 500:
        return KIND_RETRYABLE
    if status_code == 400:
        return KIND_VALIDATION
    if 400 <= status_code < 500:
        return KIND_FATAL
    return KIND_OTHER


class YandexDirectError(Exception):
    """Базовое исключение клиента.

    :param message: текст ошибки (маскируется redactor'ом).
    :param request_id: `X-Request-Id` из ответа Яндекса, если он был.
    :param status_code: HTTP-статус ответа.
    :param response_body: тело ответа (маскируется redactor'ом).
    :param kind: категория ошибки; None — определяется по `status_code`.
    """

    #: Категория, если она задана классом, а не вычисляется по статусу.
    kind: Optional[str] = None

    def __init__(
        self,
        message: str,
        *,
        request_id: Optional[str] = None,
        status_code: Optional[int] = None,
        response_body: Optional[Any] = None,
        kind: Optional[str] = None,
    ) -> None:
        safe_message = redact_text(message)
        super().__init__(safe_message)
        self.message = safe_message
        self.request_id = request_id
        self.status_code = status_code
        self.response_body = redact(response_body)
        self.kind = kind or type(self).kind or classify_error(status_code)

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " | ".join(parts)

    @property
    def is_auth(self) -> bool:
        """Ошибка авторизации/доступа (повторять нельзя)."""
        return self.kind == KIND_AUTH

    @property
    def is_retryable(self) -> bool:
        """Временная ошибка — есть смысл повторить запрос."""
        return self.kind in (KIND_RATE_LIMIT, KIND_RETRYABLE)

    @property
    def is_validation(self) -> bool:
        """Ошибка валидации запроса (исправление данных, не повтор)."""
        return self.kind == KIND_VALIDATION

    @property
    def is_fatal(self) -> bool:
        """Постоянная ошибка: права, лимиты, блокировки — повтор не поможет."""
        return self.kind == KIND_FATAL

    @property
    def retry_after(self) -> Optional[float]:
        """Рекомендованная пауза перед повтором, если сервер её указал."""
        return None


class AuthError(YandexDirectError):
    """401/403 — токен невалиден, просрочен или нет доступа к клиенту."""

    kind = KIND_AUTH


class RateLimitError(YandexDirectError):
    """429 — лимит запросов исчерпан даже после всех ретраев."""

    kind = KIND_RATE_LIMIT

    def __init__(
        self,
        message: str,
        *,
        retry_after: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self._retry_after = retry_after

    @property
    def retry_after(self) -> Optional[float]:
        return self._retry_after


class ReportNotReadyError(YandexDirectError):
    """Отчёт не перешёл в READY за отведённое время (долгое 202-голосование)."""

    kind = KIND_RETRYABLE

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
    """Любой другой non-2xx или body со status=ERROR.

    Дополнительно несёт код ошибки Яндекса, детали и (для ошибок уровня
    объекта) идентификатор сущности, к которой относится ошибка.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[str] = None,
        details: Optional[Any] = None,
        object_id: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.error_code = error_code
        self.details = redact(details)
        self.object_id = object_id


class ValidationError(YandexDirectError):
    """Ошибка на стороне клиента до отправки запроса (readonly-режим, битые аргументы)."""

    kind = KIND_VALIDATION


__all__ = [
    "KIND_AUTH",
    "KIND_FATAL",
    "KIND_OTHER",
    "KIND_RATE_LIMIT",
    "KIND_RETRYABLE",
    "KIND_VALIDATION",
    "ApiError",
    "AuthError",
    "RateLimitError",
    "ReportNotReadyError",
    "ValidationError",
    "YandexDirectError",
    "classify_error",
]
