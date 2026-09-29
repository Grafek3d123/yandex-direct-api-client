"""Typed-модели ответов Yandex.Direct API v5."""
from __future__ import annotations

from .ad import Ad, AdImage, AdText
from .ad_extension import Callout, Sitelink, SitelinksSet
from .ad_group import AdGroup
from .ad_group_item import AdGroupItem, AdGroupItemBids
from .audience_target import AudienceTarget
from .campaign import Campaign
from .negative_keyword import NegativeKeywordSharedSet
from .report import ReportFilter, ReportOrder, ReportResult, ReportRow
from .retargeting_adjustment import RetargetingBidAdjustment
from .retargeting_condition import RetargetingCondition
from .stats import StatRow
from .token import TokenResponse

__all__ = [
    "Ad",
    "AdGroup",
    "AdGroupItem",
    "AdGroupItemBids",
    "AdImage",
    "AdText",
    "AudienceTarget",
    "Callout",
    "Campaign",
    "NegativeKeywordSharedSet",
    "ReportFilter",
    "ReportOrder",
    "ReportResult",
    "ReportRow",
    "RetargetingBidAdjustment",
    "RetargetingCondition",
    "Sitelink",
    "SitelinksSet",
    "StatRow",
    "TokenResponse",
]
