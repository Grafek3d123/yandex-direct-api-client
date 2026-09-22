"""Модель ретаргетинг-сегмента (RetargetingBidAdjustment)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ._helpers import to_float, to_int, to_optional_int


@dataclass
class RetargetingBidAdjustment:
    """Корректировка ставки по ретаргетинг-сегменту."""

    id: int
    campaign_id: Optional[int] = None
    segment_id: Optional[int] = None
    type: Optional[str] = None
    level_id: Optional[int] = None
    level_type: Optional[str] = None
    bid_delta: Optional[float] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RetargetingBidAdjustment":
        delta_raw = d.get("BidDelta")
        return cls(
            id=to_int(d.get("Id")),
            campaign_id=to_optional_int(d.get("CampaignId")),
            segment_id=to_optional_int(d.get("SegmentId")),
            type=d.get("Type"),
            level_id=to_optional_int(d.get("LevelId")),
            level_type=d.get("LevelType"),
            bid_delta=to_float(delta_raw) if delta_raw is not None else None,
            priority=to_optional_int(d.get("Priority")),
            enabled=d.get("Enabled"),
            raw=d,
        )

    def to_new_payload(self) -> Dict[str, Any]:
        """Тело для retargetingadjustments/add (RetargetingAdjustmentNew)."""
        body: Dict[str, Any] = {}
        if self.campaign_id is not None:
            body["CampaignId"] = self.campaign_id
        if self.segment_id is not None:
            body["SegmentId"] = self.segment_id
        if self.type is not None:
            body["Type"] = self.type
        if self.level_id is not None:
            body["LevelId"] = self.level_id
        if self.level_type is not None:
            body["LevelType"] = self.level_type
        if self.bid_delta is not None:
            body["BidDelta"] = self.bid_delta
        if self.priority is not None:
            body["Priority"] = self.priority
        if self.enabled is not None:
            body["Enabled"] = self.enabled
        return body

    def to_update_payload(self) -> Dict[str, Any]:
        """Тело для retargetingadjustments/update: new-поля + Id."""
        body = self.to_new_payload()
        if self.id:
            body["Id"] = self.id
        return body


__all__ = ["RetargetingBidAdjustment"]
