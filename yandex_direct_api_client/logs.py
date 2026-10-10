"""Структурированное логирование клиента и маскирование секретов.

Модуль даёт два независимых механизма:

1. **Логирование.** Корневой логгер `yandex_direct_api_client` получает
   `NullHandler`, поэтому библиотека по умолчанию молчит и не влияет на вывод
   приложения (F-0.6). Каждый запрос логируется с полями `extra`:
   `service`, `api_version`, `method`, `client_login`, `request_id`,
   `status_code`, `duration_ms`, `attempt`, `readonly`.

2. **Redactor.** Любые структуры и тексты, попадающие в логи, `repr` и
   исключения, проходят через `redact()`: значения секретных ключей
   (`Authorization`, `token`, `access_token`, `refresh_token`, `client_secret`,
   `password`) заменяются на `***`, а токеноподобные строки маскируются
   по шаблону — независимо от имени ключа (F-0.6, тест безопасности).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Final, FrozenSet, Optional

#: Маска вместо секретного значения.
MASK: Final[str] = "***"

#: Имена ключей, значения которых маскируются всегда (в любом регистре).
SENSITIVE_KEYS: Final[FrozenSet[str]] = frozenset(
    {
        "authorization",
        "token",
        "access_token",
        "accesstoken",
        "refresh_token",
        "refreshtoken",
        "client_secret",
        "clientsecret",
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
    }
)

#: Токены Яндекса: OAuth-токены Direct начинаются с `t1.`, токены Метрики/Директа
#: нового формата — с `y0_`/`y1_`. Маскируем такие строки в любом тексте,
#: даже если они пришли в поле с «безобидным» именем.
_TOKEN_RE = re.compile(r"\b(?:t1\.|y0_|y1_)[A-Za-z0-9._\-]{6,}")

#: `Bearer <token>` в заголовках и текстах ошибок.
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]+")

#: Имя переменной окружения, включающей тела запросов/ответов в лог.
ENV_LOG_BODIES = "YANDEX_DIRECT_LOG_BODIES"

_ROOT_LOGGER_NAME = "yandex_direct_api_client"
_root_logger = logging.getLogger(_ROOT_LOGGER_NAME)
if not _root_logger.handlers:
    _root_logger.addHandler(logging.NullHandler())


def get_logger(name: str) -> logging.Logger:
    """Логгер дочернего модуля пакета (наследует настройки корневого).

    :param name: имя модуля, обычно `__name__`.
    :return: экземпляр `logging.Logger`.
    """
    return logging.getLogger(name)


def log_bodies_enabled() -> bool:
    """Включено ли логирование тел запросов/ответов (уровень DEBUG)."""
    raw = os.environ.get(ENV_LOG_BODIES)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def redact_text(value: str) -> str:
    """Замаскировать токеноподобные строки внутри произвольного текста.

    :param value: исходный текст.
    :return: текст с замаскированными секретами.
    """
    if not value:
        return value
    masked = _BEARER_RE.sub(r"\1 " + MASK, value)
    return _TOKEN_RE.sub(MASK, masked)


def redact(value: Any) -> Any:
    """Рекурсивно замаскировать секреты в структуре любого типа.

    Ключи из `SENSITIVE_KEYS` заменяются на `MASK`; строковые значения
    дополнительно проходят через `redact_text`, чтобы токен не утек даже
    под «невинным» именем поля.

    :param value: любое значение (dict, list, кортеж, строка, скаляр).
    :return: структура с замаскированными секретами.
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        result: Dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.strip().lower() in SENSITIVE_KEYS:
                result[key] = MASK
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def safe_extra(request_id: Optional[str] = None, **fields: Any) -> Dict[str, Any]:
    """Собрать `extra`-поля лог-сообщения с уже замаскированными значениями.

    :param request_id: идентификатор запроса Яндекса (`X-Request-Id`).
    :param fields: остальные поля (`service`, `status_code`, ...).
    :return: словарь, пригодный для передачи в `logger.info(msg, extra=...)`.
    """
    extra: Dict[str, Any] = {"request_id": request_id or "-"}
    for key, value in fields.items():
        extra[key] = redact(value)
    return extra


__all__ = [
    "ENV_LOG_BODIES",
    "MASK",
    "SENSITIVE_KEYS",
    "get_logger",
    "log_bodies_enabled",
    "redact",
    "redact_text",
    "safe_extra",
]
