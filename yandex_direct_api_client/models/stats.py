"""Модели статистики из Reports API."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ._helpers import to_float, to_int


@dataclass
class StatRow:
    """Строка статистики по объявлению (одна строка = один AdId, уже агрегированная)."""

    ad_id: int
    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    cost: float = 0.0  # рубли (конвертировано из микрорублей)
    bounce_rate: float = 0.0  # проценты
    bounces: int = 0

    @classmethod
    def from_tsv_row(cls, parts: List[str]) -> Optional["StatRow"]:
        """Разбор строки TSV-отчёта AD_PERFORMANCE_REPORT (упрощённый).

        Ожидаемый порядок колонок: AdId, Impressions, Clicks, Ctr, Cost,
        BounceRate, Bounces.
        """
        if len(parts) < 5:
            return None
        ad_id = to_int(parts[0], default=-1)
        if ad_id < 0:
            return None
        impressions = to_int(parts[1])
        clicks = to_int(parts[2])
        ctr = to_float(parts[3])
        cost_micro = to_float(parts[4])
        bounce_rate = to_float(parts[5]) if len(parts) > 5 else 0.0
        bounces = to_int(parts[6]) if len(parts) > 6 else 0
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
        """Разбор строки TSV с произвольным порядком колонок, по header-списку."""
        idx = {name: i for i, name in enumerate(header)}
        ad_id_i = idx.get("AdId")
        if ad_id_i is None or ad_id_i >= len(parts):
            return None
        ad_id = to_int(parts[ad_id_i], default=-1)
        if ad_id < 0:
            return None

        def _get(name: str, default: int = 0) -> int:
            i = idx.get(name)
            if i is None or i >= len(parts):
                return default
            return to_int(parts[i], default)

        def _getf(name: str, default: float = 0.0) -> float:
            i = idx.get(name)
            if i is None or i >= len(parts):
                return default
            return to_float(parts[i], default)

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
        """Суммировать показатели при агрегации по AdId.

        bounce_rate рассчитывается как средневзвешенное по bounces/суммарным
        визитам (impressions используются как proxy для визитов).
        """
        impressions = self.impressions + other.impressions
        clicks = self.clicks + other.clicks
        ctr = round(clicks / impressions * 100, 2) if impressions > 0 else 0.0
        bounces = self.bounces + other.bounces
        # Weighted average bounce rate: total_bounces / total_clicks * 100
        total_clicks = self.clicks + other.clicks
        if total_clicks > 0:
            bounce_rate = round(bounces / total_clicks * 100, 2)
        else:
            bounce_rate = 0.0
        return StatRow(
            ad_id=self.ad_id,
            impressions=impressions,
            clicks=clicks,
            ctr=ctr,
            cost=self.cost + other.cost,
            bounce_rate=bounce_rate,
            bounces=bounces,
        )


__all__ = ["StatRow"]
