"""Unit-тесты для `YandexDirectClient` (HTTP мокируется `responses`)."""
from __future__ import annotations

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.client import parse_stats_tsv
from yandex_direct_api_client.exceptions import ApiError, ValidationError

CAMPAIGNS_URL = "https://api.direct.yandex.com/json/v5/campaigns/"
ADS_URL = "https://api.direct.yandex.com/json/v5/ads/"
REPORTS_URL = "https://api.direct.yandex.com/json/v5/reports/"


# ---------- get_campaigns ----------
@responses.activate
def test_get_campaigns_success(client: YandexDirectClient) -> None:
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
    result = client.get_campaigns()
    assert len(result) == 2
    assert result[0].id == 1
    assert result[1].name == "B"


@responses.activate
def test_get_campaigns_error_in_body(client: YandexDirectClient) -> None:
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
        client.get_campaigns()


# ---------- get_ads ----------
@responses.activate
def test_get_ads_by_ids_chunks_requests(
    client: YandexDirectClient,
) -> None:
    # chunk_size=2 → 3 id = 2 запроса
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"Ads": [{"Id": 1}, {"Id": 2}]}},
        status=200,
    )
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"Ads": [{"Id": 3}]}},
        status=200,
    )
    ads = client.get_ads(ad_ids=[1, 2, 3])
    assert len(ads) == 3
    assert len(responses.calls) == 2


@responses.activate
def test_get_ads_requires_filter(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.get_ads()


@responses.activate
def test_get_ads_by_campaign_ids(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"Ads": [{"Id": 10, "CampaignId": 5}]}},
        status=200,
    )
    ads = client.get_ads(campaign_ids=[5])
    assert len(ads) == 1
    assert ads[0].campaign_id == 5


# ---------- get_ads_text_batch ----------
@responses.activate
def test_get_ads_text_batch(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={
            "result": {
                "Ads": [
                    {
                        "Id": 1,
                        "Type": "TEXT_AD",
                        "TextAd": {
                            "Title": "T1",
                            "Text": "B1",
                            "Href": "h1",
                        },
                    },
                    {
                        "Id": 2,
                        "Type": "TEXT_AD",
                        "TextAd": {
                            "Title": "T2",
                            "Text": "B2",
                            "Href": "h2",
                        },
                    },
                ]
            }
        },
        status=200,
    )
    out = client.get_ads_text_batch([1, 2])
    assert set(out.keys()) == {1, 2}
    assert out[1].text_ad.title == "T1"
    assert out[2].text_ad.href == "h2"


# ---------- get_stats ----------
@responses.activate
def test_get_stats_parses_tsv(client: YandexDirectClient) -> None:
    tsv = (
        "Type\tDate\tAdId\tImpressions\tClicks\tCtr\tCost\tBounceRate\tBounces\n"
        "AD_PERFORMANCE\t2026-09-01\t100\t1000\t20\t2.00\t1500000\t10.5\t5\n"
        "AD_PERFORMANCE\t2026-09-02\t100\t500\t5\t1.00\t500000\t5.5\t2\n"
        "Total\t\t\t1500\t25\t\t2000000\t\t\n"
    )
    responses.add(responses.POST, REPORTS_URL, body=tsv, status=200)
    rows = client.get_stats(ad_ids=[100], period_days=7)
    assert len(rows) == 1
    assert rows[0].ad_id == 100
    assert rows[0].impressions == 1500
    assert rows[0].clicks == 25


def test_parse_stats_tsv_no_header() -> None:
    assert parse_stats_tsv("random text\nno header here") == []


# ---------- update_ad ----------
@responses.activate
def test_update_ad_success(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"UpdateResults": [{"Id": 1}]}},
        status=200,
    )
    res = client.update_ad(1, "Заголовок", "Текст объявления")
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
def test_update_ad_clamps_long_strings(
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
    client.update_ad(1, long_title, long_body)
    body = responses.calls[0].request.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    # Ищем фактическую длину через парсинг JSON
    import json as _json

    payload = _json.loads(body)
    sent_title = payload["params"]["Ads"][0]["TextAd"]["Title"]
    sent_text = payload["params"]["Ads"][0]["TextAd"]["Text"]
    assert len(sent_title) <= 56
    assert len(sent_text) <= 81


@responses.activate
def test_update_ad_api_error(client: YandexDirectClient) -> None:
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
        client.update_ad(1, "T", "B")


# ---------- delete_ad ----------
@responses.activate
def test_delete_ad_chunks(client: YandexDirectClient) -> None:
    # chunk_size=2 → 3 id = 2 запроса (лимит mutate 200, но chunk_size = 2)
    responses.add(
        responses.POST,
        ADS_URL,
        json={
            "result": {
                "DeleteResults": [{"Id": 1}, {"Id": 2}]
            }
        },
        status=200,
    )
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"DeleteResults": [{"Id": 3}]}},
        status=200,
    )
    res = client.delete_ad([1, 2, 3])
    assert len(res) == 3
    assert len(responses.calls) == 2


@responses.activate
def test_delete_ad_empty(client: YandexDirectClient) -> None:
    assert client.delete_ad([]) == []
    assert len(responses.calls) == 0


# ---------- context manager ----------
def test_context_manager_closes_session() -> None:
    with YandexDirectClient(
        token="t", client_login="L", rate_limit_rps=1000.0
    ) as c:
        assert c.client_login == "L"
    assert c._closed
