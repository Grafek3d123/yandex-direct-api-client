"""Unit-тесты для `YandexDirectClient` (HTTP мокируется `responses`)."""
from __future__ import annotations

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.exceptions import ApiError, ValidationError
from yandex_direct_api_client.services.reports import parse_stats_tsv

CAMPAIGNS_URL = "https://api.direct.yandex.com/json/v5/campaigns/"
ADS_URL = "https://api.direct.yandex.com/json/v5/ads/"
REPORTS_URL = "https://api.direct.yandex.com/json/v5/reports/"


# ---------- campaigns.list ----------
@responses.activate
def test_campaigns_list_success(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={
            "result": {
                "Campaigns": [
                    {"Id": 1, "Name": "A", "Status": "DRAFT", "State": "ON"},
                    {"Id": 2, "Name": "B", "Status": "READY", "State": "OFF"},
                ]
            }
        },
        status=200,
    )
    result = client.campaigns.list()
    assert len(result) == 2
    assert result[0].id == 1
    assert result[1].name == "B"


@responses.activate
def test_campaigns_list_error_in_body(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={
            "error": {
                "error_code": 50,
                "error_string": "Authorization failed",
            }
        },
        status=200,
    )
    with pytest.raises(ApiError):
        client.campaigns.list()


@responses.activate
def test_campaigns_list_pagination(client: YandexDirectClient) -> None:
    """Проверяем, что LimitedBy корректно обрабатывается."""
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={
            "result": {
                "Campaigns": [
                    {"Id": 1, "Name": "A"},
                    {"Id": 2, "Name": "B"},
                ],
                "LimitedBy": 2,
            }
        },
        status=200,
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={
            "result": {
                "Campaigns": [{"Id": 3, "Name": "C"}],
            }
        },
        status=200,
    )
    result = client.campaigns.list(page_limit=2)
    assert len(result) == 3
    assert len(responses.calls) == 2


# ---------- campaigns.get ----------
@responses.activate
def test_campaigns_get_by_ids(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={"result": {"Campaigns": [{"Id": 10, "Name": "X"}]}},
        status=200,
    )
    result = client.campaigns.get([10])
    assert len(result) == 1
    assert result[0].id == 10


def test_campaigns_get_empty(client: YandexDirectClient) -> None:
    assert client.campaigns.get([]) == []


# ---------- ads.list ----------
@responses.activate
def test_ads_list_by_campaign_ids(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"Ads": [{"Id": 10, "CampaignId": 5}]}},
        status=200,
    )
    ads = client.ads.list(campaign_ids=[5])
    assert len(ads) == 1
    assert ads[0].campaign_id == 5


@responses.activate
def test_ads_list_pagination(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={
            "result": {
                "Ads": [{"Id": 1}, {"Id": 2}],
                "LimitedBy": 2,
            }
        },
        status=200,
    )
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"Ads": [{"Id": 3}]}},
        status=200,
    )
    ads = client.ads.list(campaign_ids=[1], page_limit=2)
    assert len(ads) == 3
    assert len(responses.calls) == 2


# ---------- ads.get ----------
@responses.activate
def test_ads_get_by_ids(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"Ads": [{"Id": 1}, {"Id": 2}]}},
        status=200,
    )
    ads = client.ads.get([1, 2])
    assert len(ads) == 2


def test_ads_get_empty(client: YandexDirectClient) -> None:
    assert client.ads.get([]) == []


# ---------- ads.update_text ----------
@responses.activate
def test_ads_update_text_success(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"UpdateResults": [{"Id": 1}]}},
        status=200,
    )
    res = client.ads.update_text(1, "Заголовок", "Текст объявления")
    assert res["Id"] == 1
    body = responses.calls[0].request.body
    assert body is not None
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    import json as _json

    payload = _json.loads(body)
    text_ad = payload["params"]["Ads"][0]["TextAd"]
    assert text_ad["Title"] == "Заголовок"
    assert text_ad["Text"] == "Текст объявления"


@responses.activate
def test_ads_update_text_clamps_long_strings(
    client: YandexDirectClient,
) -> None:
    long_title = "A" * 200
    long_body = "B" * 500
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"UpdateResults": [{"Id": 1}]}},
        status=200,
    )
    client.ads.update_text(1, long_title, long_body)
    body = responses.calls[0].request.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    import json as _json

    payload = _json.loads(body)
    sent_title = payload["params"]["Ads"][0]["TextAd"]["Title"]
    sent_text = payload["params"]["Ads"][0]["TextAd"]["Text"]
    assert len(sent_title) <= 56
    assert len(sent_text) <= 81


@responses.activate
def test_ads_update_text_api_error(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={
            "result": {
                "UpdateResults": [
                    {"Id": 1, "Errors": [{"Code": 100, "Message": "oops"}]}
                ]
            }
        },
        status=200,
    )
    with pytest.raises(ApiError):
        client.ads.update_text(1, "T", "B")


# ---------- ads.delete ----------
@responses.activate
def test_ads_delete_chunks(client: YandexDirectClient) -> None:
    # 3 ids fit in one chunk (MAX_MUTATE_IDS=200) → 1 request
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"DeleteResults": [{"Id": 1}, {"Id": 2}, {"Id": 3}]}},
        status=200,
    )
    res = client.ads.delete([1, 2, 3], confirm=True)
    assert len(res) == 3
    assert len(responses.calls) == 1


@responses.activate
def test_ads_delete_empty(client: YandexDirectClient) -> None:
    assert client.ads.delete([], confirm=True) == []
    assert len(responses.calls) == 0


# ---------- ads.create ----------
@responses.activate
def test_ads_create_batch(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"AddResults": [{"Id": 100}, {"Id": 101}]}},
        status=200,
    )
    res = client.ads.create([
        {"CampaignId": 1, "AdGroupId": 2, "TextAd": {"Title": "T", "Text": "B"}},
        {"CampaignId": 1, "AdGroupId": 2, "TextAd": {"Title": "T2", "Text": "B2"}},
    ])
    assert len(res) == 2
    assert res[0]["Id"] == 100


# ---------- ads.update (batch) ----------
@responses.activate
def test_ads_update_batch(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"UpdateResults": [{"Id": 1}, {"Id": 2}]}},
        status=200,
    )
    res = client.ads.update([
        {"Id": 1, "TextAd": {"Title": "T1", "Text": "B1"}},
        {"Id": 2, "TextAd": {"Title": "T2", "Text": "B2"}},
    ], confirm=True)
    assert len(res) == 2


# ---------- campaigns.create ----------
@responses.activate
def test_campaigns_create(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={"result": {"AddResults": [{"Id": 999}]}},
        status=200,
    )
    res = client.campaigns.create({"Name": "Новая кампания"})
    assert res["Id"] == 999


# ---------- campaigns.update ----------
@responses.activate
def test_campaigns_update(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={"result": {"UpdateResults": [{"Id": 999}]}},
        status=200,
    )
    res = client.campaigns.update({"Id": 999, "Name": "Обновлённая"})
    assert res["Id"] == 999


# ---------- campaigns.delete ----------
@responses.activate
def test_campaigns_delete(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={"result": {"DeleteResults": [{"Id": 1}]}},
        status=200,
    )
    res = client.campaigns.delete([1], confirm=True)
    assert len(res) == 1


# ---------- reports.get_ad_stats ----------
@responses.activate
def test_reports_get_ad_stats(client: YandexDirectClient) -> None:
    tsv = (
        "Type	Date	AdId	Impressions	Clicks	Ctr	Cost	BounceRate	Bounces\n"
        "AD_PERFORMANCE	2026-09-01	100	1000	20	2.00	1500000	10.5	5\n"
        "AD_PERFORMANCE	2026-09-02	100	500	5	1.00	500000	5.5	2\n"
        "Total			1500	25		2000000		\n"
    )
    responses.add(responses.POST, REPORTS_URL, body=tsv, status=200)
    rows = client.reports.get_ad_stats(ad_ids=[100], period_days=7)
    assert len(rows) == 1
    assert rows[0].ad_id == 100
    assert rows[0].impressions == 1500
    assert rows[0].clicks == 25


def test_parse_stats_tsv_no_header() -> None:
    assert parse_stats_tsv("random text\nno header here") == []


# ---------- confirm guard ----------
def test_ads_delete_requires_confirm(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError) as exc:
        client.ads.delete([1, 2, 3])
    assert "confirm" in str(exc.value)
    assert len(responses.calls) == 0


def test_campaigns_delete_requires_confirm(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.campaigns.delete([1])
    assert len(responses.calls) == 0


def test_ads_update_batch_requires_confirm(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.ads.update([{"Id": 1, "TextAd": {"Title": "T", "Text": "B"}}])
    assert len(responses.calls) == 0


@responses.activate
def test_ads_update_text_no_confirm_needed(client: YandexDirectClient) -> None:
    """update_text — одиночная операция, confirm не требуется."""
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"UpdateResults": [{"Id": 1}]}},
        status=200,
    )
    res = client.ads.update_text(1, "T", "B")
    assert res["Id"] == 1
    assert len(responses.calls) == 1


@responses.activate
def test_ads_delete_with_confirm_succeeds(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"DeleteResults": [{"Id": 1}]}},
        status=200,
    )
    res = client.ads.delete([1], confirm=True)
    assert res[0]["Id"] == 1


# ---------- context manager ----------
def test_context_manager_closes_session() -> None:
    with YandexDirectClient(
        token="t", client_login="L", rate_limit_rps=1000.0
    ) as c:
        assert c.client_login == "L"
    assert c._transport.closed
