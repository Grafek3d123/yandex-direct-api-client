"""Конфигурация клиента: значения по умолчанию и fallback на переменные окружения."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from ._version import __version__

DEFAULT_API_URL = "https://api.direct.yandex.com/json/v5"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_RATE_LIMIT_RPS = 5.0
DEFAULT_REPORT_TIMEOUT = 1800.0
DEFAULT_CHUNK_SIZE = 500

USER_AGENT = f"yandex-direct-api-client/{__version__}"

ENV_TOKEN = "YANDEX_DIRECT_TOKEN"
ENV_REFRESH_TOKEN = "YANDEX_DIRECT_REFRESH_TOKEN"
ENV_CLIENT_ID = "YANDEX_DIRECT_CLIENT_ID"
ENV_CLIENT_SECRET = "YANDEX_DIRECT_CLIENT_SECRET"
ENV_CLIENT_LOGIN = "YANDEX_DIRECT_CLIENT_LOGIN"
ENV_API_URL = "YANDEX_DIRECT_API_URL"
ENV_TIMEOUT = "YANDEX_DIRECT_TIMEOUT"
ENV_MAX_RETRIES = "YANDEX_DIRECT_MAX_RETRIES"
ENV_RATE_LIMIT_RPS = "YANDEX_DIRECT_RATE_LIMIT_RPS"
ENV_READONLY = "YANDEX_DIRECT_READONLY"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Настройки клиента. Значения `None` означают «подтянуть из env или default»."""

    token: Optional[str] = None
    refresh_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    client_login: Optional[str] = None
    api_url: str = DEFAULT_API_URL
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS
    readonly: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        """Собрать настройки из переменных окружения (без бросков, если чего-то нет)."""
        timeout_raw = os.environ.get(ENV_TIMEOUT)
        retries_raw = os.environ.get(ENV_MAX_RETRIES)
        rps_raw = os.environ.get(ENV_RATE_LIMIT_RPS)
        return cls(
            token=os.environ.get(ENV_TOKEN),
            refresh_token=os.environ.get(ENV_REFRESH_TOKEN),
            client_id=os.environ.get(ENV_CLIENT_ID),
            client_secret=os.environ.get(ENV_CLIENT_SECRET),
            client_login=os.environ.get(ENV_CLIENT_LOGIN),
            api_url=os.environ.get(ENV_API_URL, DEFAULT_API_URL),
            timeout=float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT,
            max_retries=int(retries_raw) if retries_raw else DEFAULT_MAX_RETRIES,
            rate_limit_rps=float(rps_raw) if rps_raw else DEFAULT_RATE_LIMIT_RPS,
            readonly=_env_bool(ENV_READONLY, False),
        )

    def merged_with(
        self,
        *,
        token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        client_login: Optional[str] = None,
        api_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        rate_limit_rps: Optional[float] = None,
        readonly: Optional[bool] = None,
    ) -> "Settings":
        """Слить явные аргументы поверх env-настроек. Явное всегда побеждает env."""
        env = self
        return Settings(
            token=token if token is not None else env.token,
            refresh_token=(
                refresh_token if refresh_token is not None else env.refresh_token
            ),
            client_id=client_id if client_id is not None else env.client_id,
            client_secret=(
                client_secret if client_secret is not None else env.client_secret
            ),
            client_login=(
                client_login if client_login is not None else env.client_login
            ),
            api_url=api_url if api_url is not None else env.api_url,
            timeout=timeout if timeout is not None else env.timeout,
            max_retries=(
                max_retries if max_retries is not None else env.max_retries
            ),
            rate_limit_rps=(
                rate_limit_rps if rate_limit_rps is not None else env.rate_limit_rps
            ),
            readonly=readonly if readonly is not None else env.readonly,
        )


__all__ = [
    "Settings",
    "DEFAULT_API_URL",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RATE_LIMIT_RPS",
    "DEFAULT_REPORT_TIMEOUT",
    "DEFAULT_CHUNK_SIZE",
    "USER_AGENT",
]
