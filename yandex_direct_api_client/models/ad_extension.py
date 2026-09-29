"""Модели расширений объявлений: быстрые ссылки (Sitelinks) и уточнения (Callout)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ._helpers import to_int, to_optional_int, to_str


@dataclass
class Sitelink:
    """Одна быстрая ссылка внутри набора (без собственного Id)."""

    title: str = ""
    href: Optional[str] = None
    description: Optional[str] = None
    turbo_page_id: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Sitelink":
        return cls(
            title=to_str(d.get("Title")),
            href=d.get("Href"),
            description=d.get("Description"),
            turbo_page_id=to_optional_int(d.get("TurboPageId")),
        )

    def to_payload(self) -> Dict[str, Any]:
        """Тело одной быстрой ссылки (Sitelink для add)."""
        body: Dict[str, Any] = {"Title": self.title}
        if self.href is not None:
            body["Href"] = self.href
        if self.description is not None:
            body["Description"] = self.description
        if self.turbo_page_id is not None:
            body["TurboPageId"] = self.turbo_page_id
        return body


@dataclass
class SitelinksSet:
    """Набор быстрых ссылок (Id + массив Sitelink)."""

    id: int
    sitelinks: List[Sitelink] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SitelinksSet":
        return cls(
            id=to_int(d.get("Id")),
            sitelinks=[Sitelink.from_dict(s) for s in (d.get("Sitelinks") or [])],
            raw=d,
        )

    def to_new_payload(self) -> Dict[str, Any]:
        """Тело для sitelinks/add (SitelinksSetAddItem)."""
        return {"Sitelinks": [s.to_payload() for s in self.sitelinks]}


@dataclass
class Callout:
    """Уточнение (расширение типа CALLOUT)."""

    id: int
    callout_text: str = ""
    type: Optional[str] = None
    associated: Optional[str] = None
    state: Optional[str] = None
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Callout":
        callout = d.get("Callout") or {}
        return cls(
            id=to_int(d.get("Id")),
            callout_text=to_str(callout.get("CalloutText")),
            type=d.get("Type"),
            associated=d.get("Associated"),
            state=d.get("State"),
            status=d.get("Status"),
            raw=d,
        )

    def to_new_payload(self) -> Dict[str, Any]:
        """Тело для adextensions/add (AdExtensionAddItem)."""
        return {"Callout": {"CalloutText": self.callout_text}}


__all__ = ["Sitelink", "SitelinksSet", "Callout"]
