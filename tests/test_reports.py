"""Тесты Reports API: универсальный get, обёртки, batching, polling."""
from __future__ import annotations

import datetime as dt
import json

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.exceptions import (
    ApiError,
    RateLimitError,
    ReportNotReadyError,
    ValidationError,
)
from yandex_direct_api_client.models import ReportFilter, ReportOrder
from yandex_direct_api_client.services.reports import (
    MAX_FILTER_IDS,
    parse_report_tsv,
)

REPORTS_URL = "https://api.direct.yandex.com/json/v5/reports/"

TSV = (
    "Report title\n"
    "CampaignId\tCampaignName\tClicks\tImpressions\tCost\n"
    "1\tКампания A\t10\t1000\t5000000\n"
    "2\tКампания B\t5\t500\t2500000\n"
    "Total\t\t15\t1500\t7500000\n"
)


def _payload_of(call: responses.Call) -> dict:
    body = call.request.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body)  # type: ignore[arg-type]


# ---------- parse_report_tsv ----------
def test_parse_report_tsv_columns_and_rows() -> None:
    result = parse_report_tsv(TSV)
    assert result.columns[:2] == ["CampaignId", "CampaignName"]
    assert len(result.rows) == 2  # Total пропущен
    assert result.rows[0].as_int("Clicks") == 10
    assert result.rows[0].as_money("Cost") == 5.0
    assert result.rows[1].as_int("Impressions") == 500


def test_parse_report_tsv_no_header() -> None:
    result = parse_report_tsv("no header\njust text")
    assert result.rows == []
    assert result.columns == []


def test_report_row_to_dict_csv_json() -> None:
    result = parse_report_tsv(TSV)
    row = result.rows[0]
    assert row.to_dict()["CampaignId"] == "1"
    csv_text = result.to_csv()
    assert "CampaignId" in csv_text and "Кампания A" in csv_text
    parsed = json.loads(result.to_json())
    assert parsed[0]["Clicks"] == "10"


# ---------- reports.get: обычный отчёт ----------
@responses.activate
def test_get_campaign_report(client: YandexDirectClient) -> None:
    responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    result = client.reports.get(
        report_type="CAMPAIGN_PERFORMANCE_REPORT",
        field_names=["CampaignId", "CampaignName", "Clicks", "Impressions", "Cost"],
        date_from=dt.date(2026, 9, 1),
        date_to=dt.date(2026, 9, 15),
    )
    assert len(result.rows) == 2
    payload = _payload_of(responses.calls[0])
    params = payload["params"]
    assert params["ReportType"] == "CAMPAIGN_PERFORMANCE_REPORT"
    assert params["DateRangeType"] == "CUSTOM_DATE"
    assert params["SelectionCriteria"]["DateFrom"] == "2026-09-01"
    assert params["SelectionCriteria"]["DateTo"] == "2026-09-15"


@responses.activate
def test_get_with_date_range_type(client: YandexDirectClient) -> None:
    responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    client.reports.get(
        report_type="ACCOUNT_PERFORMANCE_REPORT",
        field_names=["Date", "Clicks"],
        date_range_type="LAST_30_DAYS",
    )
    params = _payload_of(responses.calls[0])["params"]
    assert params["DateRangeType"] == "LAST_30_DAYS"
    assert "DateFrom" not in params["SelectionCriteria"]


def test_get_requires_dates(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.reports.get(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            field_names=["Clicks"],
        )
    assert len(responses.calls) == 0


def test_get_rejects_bad_dates(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.reports.get(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            field_names=["Clicks"],
            date_from=dt.date(2026, 9, 10),
            date_to=dt.date(2026, 9, 1),
        )


# ---------- фильтры, сортировка, цели ----------
@responses.activate
def test_get_filters_order_goals(client: YandexDirectClient) -> None:
    responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    client.reports.get(
        report_type="CAMPAIGN_PERFORMANCE_REPORT",
        field_names=["CampaignId", "Clicks"],
        date_range_type="LAST_7_DAYS",
        filters=[ReportFilter("Clicks", "GREATER_THAN", ["5"])],
        order_by=[ReportOrder("Clicks", ascending=False)],
        goals=["123", "456"],
        attribution_models=["LC"],
        include_vat=True,
    )
    params = _payload_of(responses.calls[0])["params"]
    assert params["SelectionCriteria"]["Filter"] == [
        {"Field": "Clicks", "Operator": "GREATER_THAN", "Values": ["5"]}
    ]
    assert params["OrderBy"] == [{"Field": "Clicks", "SortOrder": "DESCENDING"}]
    assert params["Goals"] == ["123", "456"]
    assert params["AttributionModels"] == ["LC"]
    assert params["IncludeVAT"] == "YES"


def test_filter_invalid_operator() -> None:
    with pytest.raises(ValueError):
        ReportFilter("Clicks", "LIKE", ["x"])


def test_get_rejects_too_many_goals(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.reports.get(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            field_names=["Clicks"],
            date_range_type="LAST_7_DAYS",
            goals=[str(i) for i in range(11)],
        )


# ---------- id-фильтры и batching ----------
@responses.activate
def test_get_id_filters_in_payload(client: YandexDirectClient) -> None:
    responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    client.reports.get(
        report_type="AD_PERFORMANCE_REPORT",
        field_names=["AdId", "Clicks"],
        date_range_type="LAST_7_DAYS",
        ad_ids=[1, 2],
        campaign_ids=[10],
    )
    params = _payload_of(responses.calls[0])["params"]
    filt = params["SelectionCriteria"]["Filter"]
    assert {"Field": "AdId", "Operator": "EQUALS", "Values": ["1", "2"]} in filt
    assert {"Field": "CampaignId", "Operator": "EQUALS", "Values": ["10"]} in filt


@responses.activate
def test_get_chunks_large_id_list(client: YandexDirectClient) -> None:
    # 2500 ID → 3 запроса (1000 + 1000 + 500)
    for _ in range(3):
        responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    ids = list(range(1, 2501))
    result = client.reports.get(
        report_type="AD_PERFORMANCE_REPORT",
        field_names=["AdId", "Clicks"],
        date_range_type="LAST_7_DAYS",
        ad_ids=ids,
    )
    assert len(responses.calls) == 3
    assert len(result.rows) == 6  # 2 строки на запрос
    first = _payload_of(responses.calls[0])["params"]
    filt = first["SelectionCriteria"]["Filter"][0]
    assert len(filt["Values"]) == MAX_FILTER_IDS


@responses.activate
def test_get_splits_long_date_range(client: YandexDirectClient) -> None:
    # 10 дней с max_days=4 → 3 окна
    for _ in range(3):
        responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    client.reports.get(
        report_type="CAMPAIGN_PERFORMANCE_REPORT",
        field_names=["CampaignId", "Clicks"],
        date_from=dt.date(2026, 1, 1),
        date_to=dt.date(2026, 1, 10),
        max_days=4,
    )
    assert len(responses.calls) == 3
    p0 = _payload_of(responses.calls[0])["params"]["SelectionCriteria"]
    p1 = _payload_of(responses.calls[1])["params"]["SelectionCriteria"]
    assert p0["DateFrom"] == "2026-01-01" and p0["DateTo"] == "2026-01-04"
    assert p1["DateFrom"] == "2026-01-05" and p1["DateTo"] == "2026-01-08"


# ---------- async: 202 polling, timeout, 429, ошибки ----------
@responses.activate
def test_get_polls_202_until_ready(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST, REPORTS_URL, body="in progress", status=202,
        headers={"Retry-In": "0"},
    )
    responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    result = client.reports.get(
        report_type="CAMPAIGN_PERFORMANCE_REPORT",
        field_names=["CampaignId", "Clicks"],
        date_range_type="LAST_7_DAYS",
    )
    assert len(responses.calls) == 2
    assert len(result.rows) == 2


@responses.activate
def test_get_report_timeout(client: YandexDirectClient) -> None:
    for _ in range(10):
        responses.add(
            responses.POST, REPORTS_URL, body="queued", status=202,
            headers={"Retry-In": "1"},
        )
    with pytest.raises(ReportNotReadyError):
        client.reports.get(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            field_names=["CampaignId", "Clicks"],
            date_range_type="LAST_7_DAYS",
            report_timeout=0.05,
        )


@responses.activate
def test_get_retries_429(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST, REPORTS_URL, body="slow down", status=429,
        headers={"Retry-After": "0"},
    )
    responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    result = client.reports.get(
        report_type="CAMPAIGN_PERFORMANCE_REPORT",
        field_names=["CampaignId", "Clicks"],
        date_range_type="LAST_7_DAYS",
    )
    assert len(responses.calls) == 2
    assert len(result.rows) == 2


@responses.activate
def test_get_429_exhausted(client: YandexDirectClient) -> None:
    for _ in range(3):
        responses.add(
            responses.POST, REPORTS_URL, body="slow down", status=429,
            headers={"Retry-After": "0"},
        )
    with pytest.raises(RateLimitError):
        client.reports.get(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            field_names=["Clicks"],
            date_range_type="LAST_7_DAYS",
        )


@responses.activate
def test_get_api_error_400(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        REPORTS_URL,
        json={"error": {"error_code": 61, "error_string": "Invalid field"}},
        status=400,
    )
    with pytest.raises(ApiError) as exc:
        client.reports.get(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            field_names=["NoSuchField"],
            date_range_type="LAST_7_DAYS",
        )
    assert exc.value.status_code == 400


# ---------- обёртки ----------
@responses.activate
def test_campaign_stats_wrapper(client: YandexDirectClient) -> None:
    responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    result = client.reports.campaign_stats(
        campaign_ids=[1, 2],
        date_from=dt.date(2026, 9, 1),
        date_to=dt.date(2026, 9, 7),
    )
    params = _payload_of(responses.calls[0])["params"]
    assert params["ReportType"] == "CAMPAIGN_PERFORMANCE_REPORT"
    assert "Conversions" in params["FieldNames"]
    assert result.rows[0].as_int("Clicks") == 10


@responses.activate
def test_search_queries_wrapper(client: YandexDirectClient) -> None:
    sq_tsv = (
        "Отчёт\n"
        "AdGroupId\tQuery\tImpressions\tClicks\tCost\tAvgClickPosition\tCtr\n"
        "100\tкупить кофе\t50\t3\t150000\t1.2\t6.0\n"
    )
    responses.add(responses.POST, REPORTS_URL, body=sq_tsv, status=200)
    result = client.reports.search_queries(
        ad_group_ids=[100],
        date_range_type="LAST_14_DAYS",
    )
    params = _payload_of(responses.calls[0])["params"]
    assert params["ReportType"] == "SEARCH_QUERY_PERFORMANCE_REPORT"
    assert "Query" in params["FieldNames"]
    assert result.rows[0].get("Query") == "купить кофе"
    assert result.rows[0].as_float("AvgClickPosition") == 1.2


@responses.activate
def test_criteria_stats_with_conversions(client: YandexDirectClient) -> None:
    cr_tsv = (
        "Отчёт\n"
        "AdGroupId\tCriteriaId\tCriteriaType\tCriteria\tClicks\tConversions\tCost\n"
        "100\t900\tKEYWORD\tкофе\t10\t2\t300000\n"
    )
    responses.add(responses.POST, REPORTS_URL, body=cr_tsv, status=200)
    result = client.reports.criteria_stats(
        date_from=dt.date(2026, 9, 1),
        date_to=dt.date(2026, 9, 7),
        goals=["123"],
    )
    params = _payload_of(responses.calls[0])["params"]
    assert params["Goals"] == ["123"]
    assert params["ReportType"] == "CRITERIA_PERFORMANCE_REPORT"
    row = result.rows[0]
    assert row.get("Criteria") == "кофе"
    assert row.as_int("Conversions") == 2
    assert row.as_money("Cost") == 0.3


@responses.activate
def test_ad_group_stats_wrapper(client: YandexDirectClient) -> None:
    responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    client.reports.ad_group_stats(date_range_type="THIS_MONTH")
    params = _payload_of(responses.calls[0])["params"]
    assert params["ReportType"] == "ADGROUP_PERFORMANCE_REPORT"


@responses.activate
def test_account_stats_wrapper(client: YandexDirectClient) -> None:
    responses.add(responses.POST, REPORTS_URL, body=TSV, status=200)
    client.reports.account_stats(date_range_type="YESTERDAY")
    params = _payload_of(responses.calls[0])["params"]
    assert params["ReportType"] == "ACCOUNT_PERFORMANCE_REPORT"


# ---------- обратная совместимость get_ad_stats ----------
@responses.activate
def test_get_ad_stats_backward_compat(client: YandexDirectClient) -> None:
    ad_tsv = (
        "Отчёт\n"
        "AdId\tImpressions\tClicks\tCtr\tCost\tBounceRate\tBounces\n"
        "100\t1000\t20\t2.0\t1500000\t10.0\t2\n"
        "100\t500\t5\t1.0\t500000\t5.0\t1\n"
        "Total\t1500\t25\t\t2000000\t\t\n"
    )
    responses.add(responses.POST, REPORTS_URL, body=ad_tsv, status=200)
    rows = client.reports.get_ad_stats(
        ad_ids=[100], date_from=dt.date(2026, 9, 1), date_to=dt.date(2026, 9, 7)
    )
    assert len(rows) == 1
    assert rows[0].ad_id == 100
    assert rows[0].impressions == 1500
    assert rows[0].clicks == 25
    assert rows[0].cost == 2.0  # 2000000 микрорублей
    # фильтр теперь через Filter (спецификация v5)
    params = _payload_of(responses.calls[0])["params"]
    filt = params["SelectionCriteria"]["Filter"]
    assert {"Field": "AdId", "Operator": "EQUALS", "Values": ["100"]} in filt


def test_get_ad_stats_period_days_default(client: YandexDirectClient) -> None:
    """Без дат — период 30 дней, валидация не падает (запрос не мокаем)."""
    with pytest.raises(Exception) as exc:
        client.reports.get_ad_stats(ad_ids=[1])
    # responses не активирован → requests.ConnectionError, но не ValidationError
    assert not isinstance(exc.value, ValidationError)
