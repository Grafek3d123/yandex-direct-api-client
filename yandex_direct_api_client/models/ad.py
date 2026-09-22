"""Модели объявлений Яндекс.Директа."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ._helpers import to_int, to_optional_int, to_str


@dataclass
class AdText:
    """Текстовая часть TextAd (Title/Text/Href)."""

    title: str = ""
    text: str = ""
    href: str = ""

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "AdText":
        if not d:
            return cls()
        return cls(
            title=to_str(d.get("Title")),
            text=to_str(d.get("Text")),
            href=to_str(d.get("Href")),
        )


@dataclass
class Ad:
    """Объявление Директа (базовые поля + текстовая часть, если запрошена)."""

    id: int
    ad_group_id: Optional[int] = None
    campaign_id: Optional[int] = None
    status: Optional[str] = None
    state: Optional[str] = None
    type: Optional[str] = None
    name: Optional[str] = None
    text_ad: Optional[AdText] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Ad":
        text_ad_raw = d.get("TextAd")
        return cls(
            id=to_int(d.get("Id")),
            ad_group_id=to_optional_int(d.get("AdGroupId")),
            campaign_id=to_optional_int(d.get("CampaignId")),
            status=d.get("Status"),
            state=d.get("State"),
            type=d.get("Type"),
            name=d.get("Name"),
            text_ad=AdText.from_dict(text_ad_raw) if text_ad_raw else None,
            raw=d,
        )


__all__ = ["Ad", "AdText"]
