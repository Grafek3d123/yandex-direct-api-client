"""Модель набора минус-фраз (NegativeKeywordSharedSet)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ._helpers import to_int, to_str


@dataclass
class NegativeKeywordSharedSet:
    """Набор минус-фраз, общий для нескольких групп объявлений."""

    id: int
    name: str = ""
    negative_keywords: List[str] = field(default_factory=list)
    associated: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "NegativeKeywordSharedSet":
        return cls(
            id=to_int(d.get("Id")),
            name=to_str(d.get("Name")),
            negative_keywords=[str(x) for x in (d.get("NegativeKeywords") or [])],
            associated=d.get("Associated"),
            raw=d,
        )

    def to_new_payload(self) -> Dict[str, Any]:
        """Тело для negativekeywordsharedsets/add (SharedSetAddItem)."""
        body: Dict[str, Any] = {}
        if self.name:
            body["Name"] = self.name
        if self.negative_keywords:
            body["NegativeKeywords"] = list(self.negative_keywords)
        return body

    def to_update_payload(self) -> Dict[str, Any]:
        """Тело для negativekeywordsharedsets/update: new-поля + Id."""
        body = self.to_new_payload()
        if self.id:
            body["Id"] = self.id
        return body


__all__ = ["NegativeKeywordSharedSet"]
