"""Typed-модели ответов Yandex.Direct API v5."""
from __future__ import annotations

from .ad import Ad, AdText
from .ad_group import AdGroup
from .campaign import Campaign
from .stats import StatRow
from .token import TokenResponse

__all__ = [
    "Ad",
    "AdGroup",
    "AdText",
    "Campaign",
    "StatRow",
    "TokenResponse",
]
