"""Сервис отчётов и статистики через Reports API."""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Sequence

from .._transport import Transport
from ..models.stats import StatRow

_DEFAULT_STAT_FIELDS = [
    "AdId",
    "Impressions",
    "Clicks",
    "Ctr",
    "Cost",
    "BounceRate",
    "Bounces",
]


def _datetime_now_str() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_stats_tsv(text: str) -> List[StatRow]:
    """Распарсить TSV-отчёт AD_PERFORMANCE_REPORT, агрегируя по AdId.

    Поддерживает произвольный порядок колонок — индексы берутся из
    строки-заголовка. Строки `Total...` пропускаются.
    """
    lines = text.splitlines()
    header_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if "AdId" in line and "Impressions" in line:
            header_idx = i
            break
    if header_idx is None:
        return []

    header = lines[header_idx].split("\t")

    aggregated: Dict[int, StatRow] = {}
    for line in lines[header_idx + 1 :]:
        if not line.strip() or line.startswith("Total"):
            continue
        parts = line.split("\t")
        row = StatRow.from_tsv_row_by_header(parts, header)
        if row is None:
            continue
        prev = aggregated.get(row.ad_id)
        aggregated[row.ad_id] = prev.merged_with(row) if prev else row
    return list(aggregated.values())


class ReportService:
    """Отчёты и статистика Yandex.Direct."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def get_ad_stats(
        self,
        *,
        ad_ids: Optional[Sequence[int]] = None,
        campaign_ids: Optional[Sequence[int]] = None,
        period_days: int = 30,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        report_name: Optional[str] = None,
    ) -> List[StatRow]:
        """Статистика по объявлениям (AD_PERFORMANCE_REPORT).

        :param ad_ids: фильтр по ID объявлений.
        :param campaign_ids: фильтр по ID кампаний.
        :param period_days: период в днях, если date_from/date_to не заданы.
        :param date_from: явная дата начала (включительно).
        :param date_to: явная дата конца (включительно).
        :param report_name: имя отчёта (по умолчанию автогенерируемое).
        :return: агрегированные строки StatRow (по одной на AdId).
        """
        if date_from is None or date_to is None:
            today = _dt.date.today()
            date_to = date_to or today
            date_from = date_from or (date_to - _dt.timedelta(days=period_days))

        criteria: Dict[str, Any] = {
            "DateFrom": date_from.isoformat(),
            "DateTo": date_to.isoformat(),
        }
        if ad_ids:
            criteria["AdIds"] = [str(a) for a in ad_ids]
        if campaign_ids:
            criteria["CampaignIds"] = [str(c) for c in campaign_ids]

        payload: Dict[str, Any] = {
            "method": "build",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": _DEFAULT_STAT_FIELDS,
                "ReportName": (
                    report_name or f"ydac-{_datetime_now_str()}"
                ),
                "ReportType": "AD_PERFORMANCE_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "NO",
                "IncludeDiscount": "NO",
            },
        }

        resp = self._transport.post("reports", payload, report=True)
        return parse_stats_tsv(resp.text)


__all__ = ["ReportService", "parse_stats_tsv"]
