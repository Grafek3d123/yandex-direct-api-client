"""Typed-модели ответов Yandex.Direct API v5."""
from __future__ import annotations

from .ad import Ad, AdImage, AdText
from .ad_group import AdGroup
from .ad_group_item import AdGroupItem, AdGroupItemBids
from .campaign import Campaign
from .retargeting_adjustment import RetargetingBidAdjustment
from .stats import StatRow
from .token import TokenResponse

__all__ = [
    "Ad",
    "AdGroup",
    "AdGroupItem",
    "AdGroupItemBids",
    "AdImage",
    "AdText",
    "Campaign",
    "RetargetingBidAdjustment",
    "StatRow",
    "TokenResponse",
]
