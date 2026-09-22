"""Модель кампании Яндекс.Директа."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ._helpers import to_date, to_int, to_str


@dataclass
class Campaign:
    """Кампания Директа."""

    id: int
    name: str
    status: Optional[str] = None
    state: Optional[str] = None
    type: Optional[str] = None
    start_date: Optional[_dt.date] = None
    end_date: Optional[_dt.date] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Campaign":
        return cls(
            id=to_int(d.get("Id")),
            name=to_str(d.get("Name")),
            status=d.get("Status"),
            state=d.get("State"),
            type=d.get("Type"),
            start_date=to_date(d.get("StartDate")),
            end_date=to_date(d.get("EndDate")),
            raw=d,
        )


__all__ = ["Campaign"]
