"""yandex-direct-api-client — typed sync-клиент Yandex.Direct API v5.

Public API:

    from yandex_direct_api_client import YandexDirectClient
    from yandex_direct_api_client import (
        YandexDirectError, AuthError, RateLimitError,
        ReportNotReadyError, ApiError, ValidationError,
    )
    from yandex_direct_api_client import (
        Campaign, Ad, AdGroup, AdText, StatRow, TokenResponse,
    )
    from yandex_direct_api_client.auth import get_new_token, refresh_token
"""
from __future__ import annotations

from ._version import __version__
from .client import YandexDirectClient
from .exceptions import (
    ApiError,
    AuthError,
    RateLimitError,
    ReportNotReadyError,
    ValidationError,
    YandexDirectError,
)
from .models import (
    Ad,
    AdGroup,
    AdText,
    Campaign,
    StatRow,
    TokenResponse,
)
from .services.reports import parse_stats_tsv

__all__ = [
    "__version__",
    # client
    "YandexDirectClient",
    "parse_stats_tsv",
    # exceptions
    "YandexDirectError",
    "AuthError",
    "RateLimitError",
    "ReportNotReadyError",
    "ApiError",
    "ValidationError",
    # models
    "Campaign",
    "Ad",
    "AdGroup",
    "AdText",
    "StatRow",
    "TokenResponse",
]
