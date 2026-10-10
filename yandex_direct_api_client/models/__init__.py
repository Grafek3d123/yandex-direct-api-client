"""Typed-модели ответов Yandex.Direct API v5."""
from __future__ import annotations

from .ad import (
    Ad,
    AdImage,
    AdText,
    BannerAd,
    CpmBannerAdBuilderAd,
    ImageAdRef,
    ResponsiveAd,
)
from .ad_extension import Callout, Sitelink, SitelinksSet
from .ad_group import AdGroup
from .ad_group_item import AdGroupItem, AdGroupItemBids
from .ad_group_payloads import (
    AdGroupBuilder,
    AutotargetingSetting,
    CpmBannerAdGroup,
    DynamicFeedAdGroup,
    DynamicSiteAdGroup,
    SmartAdGroup,
    TextAdGroup,
    UnifiedAdGroup,
    build_ad_group,
)
from .audience_target import AudienceTarget
from .batch import BatchResult, ItemFailure
from .campaign import Campaign
from .campaign_payloads import (
    CampaignBase,
    CampaignBuilder,
    CpmBannerCampaign,
    FrequencyCap,
    PriorityGoal,
    TextCampaign,
    UnifiedCampaign,
    UnifiedStrategy,
    build_campaign,
)
from .dictionaries import (
    AdType,
    AudienceCriteriaType,
    AudienceDemographicProfile,
    AudienceInterestSegment,
    Currency,
    DictEntry,
    GeoRegion,
    Interest,
    RetargetingList,
    Site,
    TimeZone,
)
from .negative_keyword import NegativeKeywordSharedSet
from .report import ReportFilter, ReportOrder, ReportResult, ReportRow
from .retargeting_adjustment import RetargetingBidAdjustment
from .retargeting_condition import RetargetingCondition
from .stats import StatRow
from .targeting import (
    GENDER_ALL,
    GENDER_FEMALE,
    GENDER_MALE,
    ContextTarget,
    DemographicsSpec,
    DemographicsTarget,
    InterestSpec,
    InterestTarget,
    RetargetingSpec,
    RetargetingTarget,
    check_keywords_allowed,
)
from .token import TokenResponse

__all__ = [
    "Ad",
    "AdGroup",
    "AdGroupItem",
    "AdGroupItemBids",
    "AdImage",
    "AdGroupBuilder",
    "AdText",
    "AdType",
    "AudienceCriteriaType",
    "AudienceDemographicProfile",
    "AudienceTarget",
    "AudienceInterestSegment",
    "AutotargetingSetting",
    "BannerAd",
    "BatchResult",
    "Callout",
    "Campaign",
    "CampaignBase",
    "CampaignBuilder",
    "ContextTarget",
    "CpmBannerAdBuilderAd",
    "CpmBannerAdGroup",
    "CpmBannerCampaign",
    "Currency",
    "DemographicsSpec",
    "DemographicsTarget",
    "DictEntry",
    "DynamicFeedAdGroup",
    "DynamicSiteAdGroup",
    "FrequencyCap",
    "GENDER_ALL",
    "GENDER_FEMALE",
    "GENDER_MALE",
    "GeoRegion",
    "ImageAdRef",
    "Interest",
    "InterestSpec",
    "InterestTarget",
    "ItemFailure",
    "NegativeKeywordSharedSet",
    "PriorityGoal",
    "ResponsiveAd",
    "RetargetingSpec",
    "RetargetingTarget",
    "SmartAdGroup",
    "TextAdGroup",
    "TextCampaign",
    "build_ad_group",
    "build_campaign",
    "check_keywords_allowed",
    "ReportFilter",
    "ReportOrder",
    "ReportResult",
    "ReportRow",
    "RetargetingBidAdjustment",
    "RetargetingCondition",
    "RetargetingList",
    "Sitelink",
    "SitelinksSet",
    "Site",
    "StatRow",
    "TimeZone",
    "TokenResponse",
    "UnifiedAdGroup",
    "UnifiedCampaign",
    "UnifiedStrategy",
]
