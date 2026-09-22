"""Модель группы объявлений Яндекс.Директа."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ._helpers import to_int, to_optional_int, to_str


@dataclass
class AdGroup:
    """Группа объявлений Директа."""

    id: int
    campaign_id: Optional[int] = None
    name: str = ""
    status: Optional[str] = None
    state: Optional[str] = None
    type: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AdGroup":
        return cls(
            id=to_int(d.get("Id")),
            campaign_id=to_optional_int(d.get("CampaignId")),
            name=to_str(d.get("Name")),
            status=d.get("Status"),
            state=d.get("State"),
            type=d.get("Type"),
            raw=d,
        )


__all__ = ["AdGroup"]
