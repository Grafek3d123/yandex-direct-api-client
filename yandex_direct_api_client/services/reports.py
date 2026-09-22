"""Сервис отчётов и статистики через Reports API.

Универсальный метод `get()` + типизированные обёртки для стандартных типов
отчётов. Один путь выполнения: обёртки только формируют параметры и
делегируют в `get()`.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Dict, List, Optional, Sequence

from .._transport import Transport
from ..exceptions import ValidationError
from ..models.report import ReportFilter, ReportOrder, ReportResult, ReportRow
from ..models.stats import StatRow

logger = logging.getLogger(__name__)

# Лимиты Reports API (официальная документация):
# - не более 10 целей в Goals;
# - до 1 000 000 строк на отчёт (Page.Limit по умолчанию);
# практический лимит на размер фильтра по ID за один запрос:
MAX_FILTER_IDS = 1000

# Колонки, по которым распознаётся строка-заголовок TSV
_KNOWN_COLUMNS = frozenset(
    {
        "Date", "CampaignId", "CampaignName", "AdGroupId", "AdGroupName",
        "AdId", "Query", "Criteria", "CriteriaId", "CriteriaType",
        "Clicks", "Impressions", "Cost", "Ctr", "Conversions",
        "ConversionRate", "CostPerConversion", "BounceRate", "Bounces",
        "AvgClickPosition", "AvgCpc", "Device", "Slot", "Month", "Week",
        "Year", "Quarter", "HourOfDay", "DayOfWeek",
    }
)

_AD_STAT_FIELDS = [
    "AdId",
    "Impressions",
    "Clicks",
    "Ctr",
    "Cost",
    "BounceRate",
    "Bounces",
]

_CAMPAIGN_STAT_FIELDS = [
    "CampaignId",
    "CampaignName",
    "Impressions",
    "Clicks",
    "Cost",
    "Conversions",
    "ConversionRate",
]

_ADGROUP_STAT_FIELDS = [
    "AdGroupId",
    "AdGroupName",
    "CampaignId",
    "Impressions",
    "Clicks",
    "Cost",
    "Conversions",
]

_CRITERIA_STAT_FIELDS = [
    "AdGroupId",
    "CriteriaId",
    "CriteriaType",
    "Criteria",
    "Impressions",
    "Clicks",
    "Cost",
    "Conversions",
]

_SEARCH_QUERY_FIELDS = [
    "AdGroupId",
    "Query",
    "Impressions",
    "Clicks",
    "Cost",
    "AvgClickPosition",
    "Ctr",
]


def _datetime_now_str() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_report_tsv(text: str) -> ReportResult:
    """Распарсить TSV-ответ Reports API в ReportResult.

    Заголовок ищется как первая строка, чьи колонки содержат известные
    имена полей; строки `Total...` пропускаются.
    """
    lines = text.splitlines()
    header_idx: Optional[int] = None
    for i, line in enumerate(lines):
        cells = line.split("	")
        if len(cells) >= 2 and any(c in _KNOWN_COLUMNS for c in cells):
            header_idx = i
            break
    if header_idx is None:
        return ReportResult(raw_text=text)

    columns = lines[header_idx].split("	")
    rows: List[ReportRow] = []
    for line in lines[header_idx + 1 :]:
        if not line.strip() or line.startswith("Total"):
            continue
        parts = line.split("	")
        row = ReportRow(
            fields={
                col: parts[i]
                for i, col in enumerate(columns)
                if i < len(parts) and parts[i] != ""
            }
        )
        if row.fields:
            rows.append(row)
    return ReportResult(columns=columns, rows=rows, raw_text=text)


def parse_stats_tsv(text: str) -> List[StatRow]:
    """Распарсить TSV-отчёт AD_PERFORMANCE_REPORT, агрегируя по AdId.

    Поддерживает произвольный порядок колонок — индексы берутся из
    строки-заголовка. Строки `Total...` пропускаются.
    """
    result = parse_report_tsv(text)
    aggregated: Dict[int, StatRow] = {}
    for row in result.rows:
        ad_id = row.as_int("AdId", default=-1)
        if ad_id < 0:
            continue
        stat = _stat_row_from_report_row(row)
        prev = aggregated.get(ad_id)
        aggregated[ad_id] = prev.merged_with(stat) if prev else stat
    return list(aggregated.values())


def _stat_row_from_report_row(row: ReportRow) -> StatRow:
    return StatRow(
        ad_id=row.as_int("AdId"),
        impressions=row.as_int("Impressions"),
        clicks=row.as_int("Clicks"),
        ctr=row.as_float("Ctr"),
        cost=row.as_money("Cost"),
        bounce_rate=row.as_float("BounceRate"),
        bounces=row.as_int("Bounces"),
    )


def _date_windows(
    date_from: _dt.date, date_to: _dt.date, max_days: int
) -> List[Sequence[_dt.date]]:
    """Разбить диапазон дат на окна не длиннее max_days (для больших периодов)."""
    windows: List[Sequence[_dt.date]] = []
    start = date_from
    while start <= date_to:
        end = min(start + _dt.timedelta(days=max_days - 1), date_to)
        windows.append((start, end))
        start = end + _dt.timedelta(days=1)
    return windows


def _chunk_id_filters(
    id_filters: List[ReportFilter],
) -> List[List[ReportFilter]]:
    """Разбить ID-фильтры на батчи, где каждый фильтр <= MAX_FILTER_IDS."""
    per_field_chunks: List[List[ReportFilter]] = []
    for f in id_filters:
        values = list(f.values)
        chunks = [
            ReportFilter(f.field_name, f.operator, values[i : i + MAX_FILTER_IDS])
            for i in range(0, len(values), MAX_FILTER_IDS)
        ]
        per_field_chunks.append(chunks)
    # Декартово произведение чанков по разным полям
    batches: List[List[ReportFilter]] = [[]]
    for chunks in per_field_chunks:
        batches = [batch + [c] for batch in batches for c in chunks]
    return batches


def _merge_results(results: List[ReportResult]) -> ReportResult:
    """Объединить результаты нескольких запросов (чанки/окна дат)."""
    if len(results) == 1:
        return results[0]
    all_rows: List[ReportRow] = []
    for r in results:
        all_rows.extend(r.rows)
    columns = next((r.columns for r in results if r.columns), [])
    return ReportResult(columns=columns, rows=all_rows)


class ReportService:
    """Отчёты и статистика Yandex.Direct (Reports API)."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    # -------- универсальный метод --------
    def get(
        self,
        *,
        report_type: str,
        field_names: Sequence[str],
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        date_range_type: Optional[str] = None,
        filters: Optional[Sequence[ReportFilter]] = None,
        order_by: Optional[Sequence[ReportOrder]] = None,
        goals: Optional[Sequence[str]] = None,
        attribution_models: Optional[Sequence[str]] = None,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        ad_ids: Optional[Sequence[int]] = None,
        page_limit: Optional[int] = None,
        include_vat: bool = False,
        include_discount: bool = False,
        report_name: Optional[str] = None,
        max_days: Optional[int] = None,
        report_timeout: Optional[float] = None,
    ) -> ReportResult:
        """Универсальный отчёт Reports API (метод build + TSV).

        :param report_type: тип отчёта (CAMPAIGN_PERFORMANCE_REPORT, ...).
        :param field_names: колонки отчёта (FieldNames).
        :param date_from: начало периода (для CUSTOM_DATE).
        :param date_to: конец периода (для CUSTOM_DATE).
        :param date_range_type: готовый период (LAST_7_DAYS, LAST_30_DAYS,
            THIS_MONTH, ...); если None — CUSTOM_DATE по date_from/date_to.
        :param filters: произвольные фильтры (ReportFilter).
        :param order_by: сортировка (ReportOrder).
        :param goals: ID целей Метрики (до 10) — конверсии по целям.
        :param attribution_models: модели атрибуции (LC, LSCCD, FCCD, AUTO).
        :param campaign_ids: фильтр по ID кампаний (авто-чанкинг по 1000).
        :param ad_group_ids: фильтр по ID групп (авто-чанкинг по 1000).
        :param ad_ids: фильтр по ID объявлений (авто-чанкинг по 1000).
        :param page_limit: лимит строк (Page.Limit, по умолчанию 1 000 000).
        :param include_vat: включать НДС в суммы.
        :param include_discount: учитывать скидку.
        :param report_name: имя отчёта (по умолчанию автогенерируемое).
        :param max_days: разбивать период на окна не длиннее N дней
            (для очень больших диапазонов; None — не разбивать).
        :param report_timeout: таймаут ожидания готовности отчёта для
            этого вызова (override настройки клиента).
        :return: ReportResult с типизированными строками.
        """
        if not field_names:
            raise ValidationError("field_names не может быть пустым")
        if goals and len(goals) > 10:
            raise ValidationError("Goals: не более 10 целей (лимит API)")
        if date_range_type is None:
            if date_from is None or date_to is None:
                raise ValidationError(
                    "Укажите date_from и date_to либо date_range_type"
                )
            if date_to < date_from:
                raise ValidationError("date_to раньше date_from")
            date_range_type = "CUSTOM_DATE"

        # Фильтры по ID: объединяем с пользовательскими, чанкуем по лимиту
        id_filters: List[ReportFilter] = []
        if campaign_ids:
            id_filters.append(
                ReportFilter("CampaignId", "EQUALS", [str(i) for i in campaign_ids])
            )
        if ad_group_ids:
            id_filters.append(
                ReportFilter("AdGroupId", "EQUALS", [str(i) for i in ad_group_ids])
            )
        if ad_ids:
            id_filters.append(
                ReportFilter("AdId", "EQUALS", [str(i) for i in ad_ids])
            )
        user_filters = list(filters or [])

        needs_id_chunks = any(len(f.values) > MAX_FILTER_IDS for f in id_filters)
        needs_date_windows = (
            date_range_type == "CUSTOM_DATE"
            and max_days is not None
            and date_from is not None
            and date_to is not None
            and (date_to - date_from).days + 1 > max_days
        )

        if not needs_id_chunks and not needs_date_windows:
            return self._build_one(
                report_type=report_type,
                field_names=field_names,
                date_from=date_from,
                date_to=date_to,
                date_range_type=date_range_type,
                filters=user_filters + id_filters,
                order_by=order_by,
                goals=goals,
                attribution_models=attribution_models,
                page_limit=page_limit,
                include_vat=include_vat,
                include_discount=include_discount,
                report_name=report_name,
                report_timeout=report_timeout,
            )

        # Двумерное разбиение: окна дат x чанки ID-фильтров
        if needs_date_windows:
            windows = _date_windows(date_from, date_to, max_days)  # type: ignore[arg-type]
        else:
            windows = [(date_from, date_to)]  # type: ignore[list-item]
        filter_batches = (
            _chunk_id_filters(id_filters) if needs_id_chunks else [id_filters]
        )

        results: List[ReportResult] = []
        for w_idx, window in enumerate(windows):
            for f_idx, batch in enumerate(filter_batches):
                suffix = f"-{w_idx + 1}-{f_idx + 1}"
                results.append(
                    self._build_one(
                        report_type=report_type,
                        field_names=field_names,
                        date_from=window[0] if date_range_type == "CUSTOM_DATE" else None,
                        date_to=window[1] if date_range_type == "CUSTOM_DATE" else None,
                        date_range_type=date_range_type,
                        filters=user_filters + batch,
                        order_by=order_by,
                        goals=goals,
                        attribution_models=attribution_models,
                        page_limit=page_limit,
                        include_vat=include_vat,
                        include_discount=include_discount,
                        report_name=(report_name or "ydac") + suffix,
                        report_timeout=report_timeout,
                    )
                )
        return _merge_results(results)

    def _build_one(
        self,
        *,
        report_type: str,
        field_names: Sequence[str],
        date_from: Optional[_dt.date],
        date_to: Optional[_dt.date],
        date_range_type: str,
        filters: List[ReportFilter],
        order_by: Optional[Sequence[ReportOrder]],
        goals: Optional[Sequence[str]],
        attribution_models: Optional[Sequence[str]],
        page_limit: Optional[int],
        include_vat: bool,
        include_discount: bool,
        report_name: Optional[str],
        report_timeout: Optional[float] = None,
    ) -> ReportResult:
        """Один HTTP-запрос build (polling/retry — в Transport)."""
        criteria: Dict[str, Any] = {}
        if date_range_type == "CUSTOM_DATE":
            criteria["DateFrom"] = (date_from or _dt.date.today()).isoformat()
            criteria["DateTo"] = (date_to or _dt.date.today()).isoformat()
        if filters:
            criteria["Filter"] = [f.to_payload() for f in filters]

        params: Dict[str, Any] = {
            "SelectionCriteria": criteria,
            "FieldNames": list(field_names),
            "ReportName": report_name or f"ydac-{_datetime_now_str()}",
            "ReportType": report_type,
            "DateRangeType": date_range_type,
            "Format": "TSV",
            "IncludeVAT": "YES" if include_vat else "NO",
            "IncludeDiscount": "YES" if include_discount else "NO",
        }
        if order_by:
            params["OrderBy"] = [o.to_payload() for o in order_by]
        if goals:
            params["Goals"] = [str(g) for g in goals]
        if attribution_models:
            params["AttributionModels"] = list(attribution_models)
        if page_limit is not None:
            params["Page"] = {"Limit": int(page_limit)}

        payload: Dict[str, Any] = {"method": "build", "params": params}
        resp = self._transport.post(
            "reports", payload, report=True, report_timeout=report_timeout
        )
        return parse_report_tsv(resp.text)

    # -------- типизированные обёртки --------
    def account_stats(
        self,
        *,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        date_range_type: Optional[str] = None,
        field_names: Optional[Sequence[str]] = None,
        filters: Optional[Sequence[ReportFilter]] = None,
        order_by: Optional[Sequence[ReportOrder]] = None,
        goals: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> ReportResult:
        """Статистика по аккаунту (ACCOUNT_PERFORMANCE_REPORT)."""
        return self.get(
            report_type="ACCOUNT_PERFORMANCE_REPORT",
            field_names=field_names
            or ["Date", "Impressions", "Clicks", "Cost", "Conversions"],
            date_from=date_from,
            date_to=date_to,
            date_range_type=date_range_type,
            filters=filters,
            order_by=order_by,
            goals=goals,
            **kwargs,
        )

    def campaign_stats(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        date_range_type: Optional[str] = None,
        field_names: Optional[Sequence[str]] = None,
        filters: Optional[Sequence[ReportFilter]] = None,
        order_by: Optional[Sequence[ReportOrder]] = None,
        goals: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> ReportResult:
        """Статистика по кампаниям (CAMPAIGN_PERFORMANCE_REPORT)."""
        return self.get(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            field_names=field_names or _CAMPAIGN_STAT_FIELDS,
            date_from=date_from,
            date_to=date_to,
            date_range_type=date_range_type,
            filters=filters,
            order_by=order_by,
            goals=goals,
            campaign_ids=campaign_ids,
            **kwargs,
        )

    def ad_group_stats(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        date_range_type: Optional[str] = None,
        field_names: Optional[Sequence[str]] = None,
        filters: Optional[Sequence[ReportFilter]] = None,
        order_by: Optional[Sequence[ReportOrder]] = None,
        goals: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> ReportResult:
        """Статистика по группам объявлений (ADGROUP_PERFORMANCE_REPORT)."""
        return self.get(
            report_type="ADGROUP_PERFORMANCE_REPORT",
            field_names=field_names or _ADGROUP_STAT_FIELDS,
            date_from=date_from,
            date_to=date_to,
            date_range_type=date_range_type,
            filters=filters,
            order_by=order_by,
            goals=goals,
            campaign_ids=campaign_ids,
            ad_group_ids=ad_group_ids,
            **kwargs,
        )

    def criteria_stats(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        date_range_type: Optional[str] = None,
        field_names: Optional[Sequence[str]] = None,
        filters: Optional[Sequence[ReportFilter]] = None,
        order_by: Optional[Sequence[ReportOrder]] = None,
        goals: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> ReportResult:
        """Статистика по условиям показа — ключевым фразам и автотаргетингам
        (CRITERIA_PERFORMANCE_REPORT)."""
        return self.get(
            report_type="CRITERIA_PERFORMANCE_REPORT",
            field_names=field_names or _CRITERIA_STAT_FIELDS,
            date_from=date_from,
            date_to=date_to,
            date_range_type=date_range_type,
            filters=filters,
            order_by=order_by,
            goals=goals,
            campaign_ids=campaign_ids,
            ad_group_ids=ad_group_ids,
            **kwargs,
        )

    def search_queries(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        date_range_type: Optional[str] = None,
        field_names: Optional[Sequence[str]] = None,
        filters: Optional[Sequence[ReportFilter]] = None,
        order_by: Optional[Sequence[ReportOrder]] = None,
        **kwargs: Any,
    ) -> ReportResult:
        """Статистика по поисковым запросам (SEARCH_QUERY_PERFORMANCE_REPORT)."""
        return self.get(
            report_type="SEARCH_QUERY_PERFORMANCE_REPORT",
            field_names=field_names or _SEARCH_QUERY_FIELDS,
            date_from=date_from,
            date_to=date_to,
            date_range_type=date_range_type,
            filters=filters,
            order_by=order_by,
            campaign_ids=campaign_ids,
            ad_group_ids=ad_group_ids,
            **kwargs,
        )

    # -------- обратная совместимость --------
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
        """Статистика по объявлениям (AD_PERFORMANCE_REPORT) → List[StatRow].

        Обёртка над `get()` с агрегацией строк по AdId (сохранённый API
        этапа 1). Фильтр по ID передаётся через Filter (спецификация v5),
        а не через поля SelectionCriteria.

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

        result = self.get(
            report_type="AD_PERFORMANCE_REPORT",
            field_names=_AD_STAT_FIELDS,
            date_from=date_from,
            date_to=date_to,
            ad_ids=ad_ids,
            campaign_ids=campaign_ids,
            report_name=report_name,
        )

        aggregated: Dict[int, StatRow] = {}
        for row in result.rows:
            ad_id = row.as_int("AdId", default=-1)
            if ad_id < 0:
                continue
            stat = _stat_row_from_report_row(row)
            prev = aggregated.get(ad_id)
            aggregated[ad_id] = prev.merged_with(stat) if prev else stat
        return list(aggregated.values())


__all__ = [
    "ReportService",
    "parse_report_tsv",
    "parse_stats_tsv",
]
