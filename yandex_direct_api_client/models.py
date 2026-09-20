"""Typed-ответы API Яндекс.Директа в виде dataclass'ов.

Все классы имеют `from_dict()` — конструктор из сырого JSON-словаря.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.replace(",", ".").strip()
        if value in {"", "--"}:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _to_date(value: Any) -> Optional[_dt.date]:
    """Разобрать дату Директа формата 'YYYY-MM-DD'. Пустое/недата -> None."""
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass
class Campaign:
    """Кампания Директа."""

    id: int
    name: str
    status: Optional[str] = None
    state: Optional[str] = None
    start_date: Optional[_dt.date] = None
    end_date: Optional[_dt.date] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Campaign":
        return cls(
            id=_to_int(d.get("Id")),
            name=_to_str(d.get("Name")),
            status=d.get("Status"),
            state=d.get("State"),
            start_date=_to_date(d.get("StartDate")),
            end_date=_to_date(d.get("EndDate")),
            raw=d,
        )


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
            title=_to_str(d.get("Title")),
            text=_to_str(d.get("Text")),
            href=_to_str(d.get("Href")),
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
            id=_to_int(d.get("Id")),
            ad_group_id=(
                _to_int(d["AdGroupId"]) if d.get("AdGroupId") is not None else None
            ),
            campaign_id=(
                _to_int(d["CampaignId"]) if d.get("CampaignId") is not None else None
            ),
            status=d.get("Status"),
            state=d.get("State"),
            type=d.get("Type"),
            name=d.get("Name"),
            text_ad=AdText.from_dict(text_ad_raw) if text_ad_raw else None,
            raw=d,
        )


@dataclass
class AdTextEntry:
    """Запись из `get_ads_text_batch` — id + текстовая часть."""

    id: int
    text_ad: AdText

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AdTextEntry":
        return cls(
            id=_to_int(d.get("Id")),
            text_ad=AdText.from_dict(d.get("TextAd")),
        )


@dataclass
class StatRow:
    """Строка статистики по объявлению (одна строка = один AdId, уже агрегированная)."""

    ad_id: int
    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    cost: float = 0.0  # в рублях (из микрорублей)
    bounce_rate: float = 0.0  # в процентах
    bounces: int = 0

    @classmethod
    def from_tsv_row(cls, parts: List[str]) -> Optional["StatRow"]:
        """Разбор строки TSV-отчёта AD_PERFORMANCE_REPORT (упрощённый).

        Ожидаемый порядок колонок: AdId, Impressions, Clicks, Ctr, Cost,
        BounceRate, Bounces. Для полного парсинга с произвольным порядком
        колонок используйте `parse_stats_tsv` в `client.py`.
        """
        if len(parts) < 5:
            return None
        ad_id = _to_int(parts[0], default=-1)
        if ad_id < 0:
            return None
        impressions = _to_int(parts[1])
        clicks = _to_int(parts[2])
        ctr = _to_float(parts[3])
        # Cost приходит в микрорублях
        cost_micro = _to_float(parts[4])
        bounce_rate = _to_float(parts[5]) if len(parts) > 5 else 0.0
        bounces = _to_int(parts[6]) if len(parts) > 6 else 0
        return cls(
            ad_id=ad_id,
            impressions=impressions,
            clicks=clicks,
            ctr=ctr,
            cost=cost_micro / 1_000_000.0,
            bounce_rate=bounce_rate,
            bounces=bounces,
        )

    @classmethod
    def from_tsv_row_by_header(
        cls, parts: List[str], header: List[str]
    ) -> Optional["StatRow"]:
        """Разбор строки TSV с произвольным порядком колонок, по header-списку.

        :param parts: значения строки.
        :param header: имена колонок из заголовка отчёта.
        """
        idx = {name: i for i, name in enumerate(header)}
        ad_id_i = idx.get("AdId")
        if ad_id_i is None or ad_id_i >= len(parts):
            return None
        ad_id = _to_int(parts[ad_id_i], default=-1)
        if ad_id < 0:
            return None

        def _get(name: str, default: int = 0) -> int:
            i = idx.get(name)
            if i is None or i >= len(parts):
                return default
            return _to_int(parts[i], default)

        def _getf(name: str, default: float = 0.0) -> float:
            i = idx.get(name)
            if i is None or i >= len(parts):
                return default
            return _to_float(parts[i], default)

        cost_micro = _getf("Cost")
        return cls(
            ad_id=ad_id,
            impressions=_get("Impressions"),
            clicks=_get("Clicks"),
            ctr=_getf("Ctr"),
            cost=cost_micro / 1_000_000.0,
            bounce_rate=_getf("BounceRate"),
            bounces=_get("Bounces"),
        )

    def merged_with(self, other: "StatRow") -> "StatRow":
        """Суммирует показатели (для агрегации по дням)."""
        impressions = self.impressions + other.impressions
        clicks = self.clicks + other.clicks
        ctr = round(clicks / impressions * 100, 2) if impressions > 0 else 0.0
        return StatRow(
            ad_id=self.ad_id,
            impressions=impressions,
            clicks=clicks,
            ctr=ctr,
            cost=self.cost + other.cost,
            bounce_rate=self.bounce_rate + other.bounce_rate,
            bounces=self.bounces + other.bounces,
        )


@dataclass
class TokenResponse:
    """Ответ OAuth-эндпоинтов Яндекса (token / refresh)."""

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TokenResponse":
        return cls(
            access_token=_to_str(d.get("access_token")),
            refresh_token=(
                _to_str(d["refresh_token"]) if d.get("refresh_token") else None
            ),
            token_type=_to_str(d.get("token_type"), default="bearer"),
            expires_in=(
                _to_int(d["expires_in"]) if d.get("expires_in") is not None else None
            ),
        )


__all__ = [
    "Campaign",
    "Ad",
    "AdText",
    "AdTextEntry",
    "StatRow",
    "TokenResponse",
]
