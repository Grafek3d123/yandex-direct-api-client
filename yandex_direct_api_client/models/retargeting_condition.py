"""Модель условия ретаргетинга (RetargetingCondition).

В актуальном справочнике Yandex Direct API v5 отдельный сервис
``retargetingconditions`` отсутствует: условия ретаргетинга управляются
сервисом ``audiencetargets`` через поле ``RetargetingListId``. Модель описывает
такое условие, привязанное к ретаргетинг-списку.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ._helpers import to_int, to_optional_int


@dataclass
class RetargetingCondition:
    """Условие ретаргетинга (аудитория по ретаргетинг-списку)."""

    id: int
    ad_group_id: Optional[int] = None
    campaign_id: Optional[int] = None
    retargeting_list_id: Optional[int] = None
    context_bid: Optional[int] = None
    strategy_priority: Optional[str] = None
    state: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RetargetingCondition":
        return cls(
            id=to_int(d.get("Id")),
            ad_group_id=to_optional_int(d.get("AdGroupId")),
            campaign_id=to_optional_int(d.get("CampaignId")),
            retargeting_list_id=to_optional_int(d.get("RetargetingListId")),
            context_bid=to_optional_int(d.get("ContextBid")),
            strategy_priority=d.get("StrategyPriority"),
            state=d.get("State"),
            raw=d,
        )

    def to_new_payload(self) -> Dict[str, Any]:
        """Тело для audiencetargets/add (условие на ретаргетинг-список)."""
        body: Dict[str, Any] = {}
        if self.ad_group_id is not None:
            body["AdGroupId"] = self.ad_group_id
        if self.retargeting_list_id is not None:
            body["RetargetingListId"] = self.retargeting_list_id
        if self.context_bid is not None:
            body["ContextBid"] = self.context_bid
        if self.strategy_priority is not None:
            body["StrategyPriority"] = self.strategy_priority
        return body


__all__ = ["RetargetingCondition"]
