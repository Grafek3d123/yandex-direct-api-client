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

    def to_payload(self) -> Dict[str, Any]:
        """Тело TextAd для запросов add/update."""
        payload: Dict[str, Any] = {"Title": self.title, "Text": self.text}
        if self.href:
            payload["Href"] = self.href
        return payload


@dataclass
class AdImage:
    """Картинка объявления (ImageAd)."""

    image_id: str = ""
    autofocus: Optional[bool] = None

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "AdImage":
        if not d:
            return cls()
        return cls(
            image_id=to_str(d.get("ImageId")),
            autofocus=d.get("Autofocus"),
        )

    def to_payload(self) -> Dict[str, Any]:
        """Тело ImageAd для запросов add/update."""
        payload: Dict[str, Any] = {"ImageId": self.image_id}
        if self.autofocus is not None:
            payload["Autofocus"] = self.autofocus
        return payload


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


__all__ = ["Ad", "AdImage", "AdText"]
