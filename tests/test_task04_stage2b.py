"""Тесты слоя 2Б STAGE_05: ЕПК (UnifiedCampaign, v501) и комбинаторные объявления.

Идентификаторы критериев приёмки:
- F-2B.1 — сериализация `UnifiedCampaign` для add и update;
- F-2B.2 — `ResponsiveAd` и его валидация;
- F-2B.3 — `CounterIds` и `PriorityGoals` (цели по ID, не по названиям);
- F-2B.4 — гео ЕПК в группе через тот же `RegionIds`, что и для v5;
- F-2B.5 — стратегия и недельный бюджет;
- F-2B.6 — `create_unified`/`get_unified`/`update_unified`/`delete_unified`
  маршрутизируются на `v501`, v5-методы остаются на `v5`;
- `readonly` и `confirm` работают на новых методах.

Контракт сверен с документацией (снимок 30.09.2026): campaigns/add-unified-campaign,
campaigns/update-unified-campaign, adgroups/add (`UnifiedAdGroup`), ads/add
(`ResponsiveAd`).
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Dict

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.exceptions import ValidationError
from yandex_direct_api_client.models.ad import ResponsiveAd
from yandex_direct_api_client.models.ad_group_payloads import UnifiedAdGroup
from yandex_direct_api_client.models.campaign_payloads import (
    PriorityGoal,
    UnifiedCampaign,
    UnifiedStrategy,
    build_campaign,
)

CAMPAIGNS_V5_URL = "https://api.direct.yandex.com/json/v5/campaigns/"
CAMPAIGNS_V501_URL = "https://api.direct.yandex.com/json/v501/campaigns/"
ADGROUPS_V501_URL = "https://api.direct.yandex.com/json/v501/adgroups/"
ADS_V501_URL = "https://api.direct.yandex.com/json/v501/ads/"

START = _dt.date(2026, 10, 1)


def _body_of(call: Any) -> Dict[str, Any]:
    """Разобрать JSON-тело исходящего запроса."""
    return json.loads(call.request.body)


def _client(**kwargs: Any) -> YandexDirectClient:
    """Клиент с тестовыми настройками."""
    params: Dict[str, Any] = {
        "token": "test_token",
        "client_login": "TESTLOGIN",
        "rate_limit_rps": 1000.0,
        "max_retries": 1,
    }
    params.update(kwargs)
    return YandexDirectClient(**params)


# ---------------- F-2B.1/F-2B.5: сериализация кампании ----------------


def test_unified_campaign_add_payload_snapshot() -> None:
    campaign = UnifiedCampaign(
        name="ЕПК печатки",
        start_date=START,
        end_date=_dt.date(2026, 12, 31),
        time_zone="Europe/Moscow",
        search=UnifiedStrategy(
            strategy="AVERAGE_CPC", average_cpc=30, weekly_budget=2000
        ),
        network=UnifiedStrategy(strategy="NETWORK_DEFAULT"),
        counter_ids=[1234],
        priority_goals=[PriorityGoal(goal_id=182, value=1)],
        settings=[{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
        attribution_model="AUTO",
        negative_keywords_shared_set_ids=[7],
    )
    assert campaign.to_payload() == {
        "Name": "ЕПК печатки",
        "StartDate": "2026-10-01",
        "EndDate": "2026-12-31",
        "TimeZone": "Europe/Moscow",
        "UnifiedCampaign": {
            "BiddingStrategy": {
                "Search": {
                    "BiddingStrategyType": "AVERAGE_CPC",
                    "AverageCpc": {
                        "AverageCpc": 30_000_000,
                        "WeeklySpendLimit": 2_000_000_000,
                    },
                },
                "Network": {"BiddingStrategyType": "NETWORK_DEFAULT"},
            },
            "CounterIds": {"Items": [1234]},
            "PriorityGoals": {"Items": [{"GoalId": 182, "Value": 1}]},
            "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
            "AttributionModel": "AUTO",
            "NegativeKeywordSharedSetIds": {"Items": [7]},
        },
    }


def test_unified_campaign_update_payload_has_id() -> None:
    campaign = UnifiedCampaign(
        name="ЕПК",
        search=UnifiedStrategy(strategy="AVERAGE_CPA", weekly_budget=5000, goal_id=182),
    )
    payload = campaign.to_update_payload(55)
    assert payload["Id"] == 55
    assert payload["Name"] == "ЕПК"
    assert "StartDate" not in payload
    search = payload["UnifiedCampaign"]["BiddingStrategy"]["Search"]
    assert search["AverageCpa"] == {
        "WeeklySpendLimit": 5_000_000_000,
        "GoalId": 182,
    }


def test_unified_strategy_requirements() -> None:
    with pytest.raises(ValidationError) as goal_exc:
        UnifiedStrategy(strategy="AVERAGE_CPA", weekly_budget=100).to_payload(
            placement="Search"
        )
    assert "goal_id" in str(goal_exc.value)
    with pytest.raises(ValidationError) as budget_exc:
        UnifiedStrategy(strategy="WB_MAXIMUM_CLICKS").to_payload(placement="Search")
    assert "weekly_budget" in str(budget_exc.value)
    with pytest.raises(ValidationError):
        UnifiedStrategy(strategy="AVERAGE_CPC").to_payload(placement="Search")
    with pytest.raises(ValidationError):
        UnifiedStrategy(strategy="NETWORK_DEFAULT").to_payload(placement="Search")
    with pytest.raises(ValidationError):
        UnifiedStrategy(strategy="HIGHEST_POSITION").to_payload(placement="Network")
    with pytest.raises(ValidationError):
        UnifiedStrategy(strategy="MAGIC").to_payload(placement="Search")


def test_unified_strategy_escape_hatch_fields() -> None:
    strategy = UnifiedStrategy(
        strategy="AVERAGE_CPC",
        average_cpc=25,
        bid_ceiling=100,
        extra={"BudgetType": "CUSTOM_PERIOD_BUDGET"},
    )
    block = strategy.to_payload(placement="Search")
    assert block["AverageCpc"]["BidCeiling"] == 100_000_000
    assert block["AverageCpc"]["BudgetType"] == "CUSTOM_PERIOD_BUDGET"


def test_priority_goal_payload() -> None:
    goal = PriorityGoal(
        goal_id=182, value=3, is_metrika_source_of_value=True, operation="SET"
    )
    assert goal.to_payload() == {
        "GoalId": 182,
        "Value": 3,
        "IsMetrikaSourceOfValue": "YES",
        "Operation": "SET",
    }
    with pytest.raises(ValidationError):
        PriorityGoal(goal_id=0).to_payload()
    with pytest.raises(ValidationError):
        PriorityGoal(goal_id=1, value=0).to_payload()
    with pytest.raises(ValidationError):
        PriorityGoal(goal_id=1, operation="DROP").to_payload()


def test_priority_goal_value_default_warns(caplog) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        goal = PriorityGoal(goal_id=182)
    assert goal.value == 1
    assert any("PriorityGoal: value не задан" in r.message for r in caplog.records)


def test_priority_goal_value_explicit_no_warn(caplog) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        goal = PriorityGoal(goal_id=182, value=1)
    assert goal.value == 1
    assert not [r for r in caplog.records if "PriorityGoal: value не задан" in r.message]


def test_unified_campaign_defaults_strategy_with_warning(caplog) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        campaign = UnifiedCampaign(
            name="ЕПК", start_date=START,
            search=UnifiedStrategy(strategy="AVERAGE_CPC", average_cpc=30, weekly_budget=2000),
        )
        payload = campaign.to_payload()
    assert payload["UnifiedCampaign"]["BiddingStrategy"]["Network"]["BiddingStrategyType"] == "NETWORK_DEFAULT"
    assert any("network стратегия не задана" in r.message for r in caplog.records)


def test_unified_campaign_explicit_strategy_no_warn(caplog) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        campaign = UnifiedCampaign(
            name="ЕПК", start_date=START,
            search=UnifiedStrategy(strategy="AVERAGE_CPC", average_cpc=10),
            network=UnifiedStrategy(strategy="NETWORK_DEFAULT"),
        )
        campaign.to_payload()
    assert not [r for r in caplog.records if "стратегия не задана" in r.message]


def test_unified_campaign_rejects_too_many_goals() -> None:
    goals = [PriorityGoal(goal_id=i, value=1) for i in range(1, 32)]
    campaign = UnifiedCampaign(
        name="ЕПК",
        start_date=START,
        search=UnifiedStrategy(strategy="AVERAGE_CPC", average_cpc=10),
        priority_goals=goals,
    )
    with pytest.raises(ValidationError):
        campaign.to_payload()


def test_build_campaign_supports_unified() -> None:
    builder = build_campaign(
        "UNIFIED_CAMPAIGN",
        name="ЕПК",
        start_date=START,
        search=UnifiedStrategy(strategy="AVERAGE_CPC", average_cpc=10),
    )
    assert isinstance(builder, UnifiedCampaign)


def test_unified_campaign_start_date_required() -> None:
    with pytest.raises(ValidationError):
        UnifiedCampaign(name="ЕПК").to_payload()


# ---------------- F-2B.2: ResponsiveAd ----------------


def test_responsive_ad_payload() -> None:
    ad = ResponsiveAd(
        titles=["Печатки", "Гравировка"],
        texts=["Изготовление печаток на заказ"],
        href="https://example.com/jewelry",
        ad_image_hashes=["h1", "h2"],
        display_url_path="/jewelry",
        age_label=18,
    )
    assert ad.to_payload() == {
        "Titles": ["Печатки", "Гравировка"],
        "Texts": ["Изготовление печаток на заказ"],
        "Href": "https://example.com/jewelry",
        "AdImageHashes": ["h1", "h2"],
        "DisplayUrlPath": "/jewelry",
        "AgeLabel": 18,
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"titles": [], "texts": ["т"], "href": "https://e.com"},
        {"titles": ["з"] * 8, "texts": ["т"], "href": "https://e.com"},
        {"titles": ["з" * 57], "texts": ["т"], "href": "https://e.com"},
        {"titles": ["з"], "texts": [], "href": "https://e.com"},
        {"titles": ["з"], "texts": ["т"] * 4, "href": "https://e.com"},
        {"titles": ["з"], "texts": ["т" * 82], "href": "https://e.com"},
        {"titles": ["з"], "texts": ["т"]},
        {"titles": ["з"], "texts": ["т"], "href": "e.com"},
        {
            "titles": ["з"],
            "texts": ["т"],
            "href": "https://e.com",
            "ad_image_hashes": [],
        },
        {
            "titles": ["з"],
            "texts": ["т"],
            "href": "https://e.com",
            "video_extension_ids": [1] * 7,
        },
        {
            "titles": ["з"],
            "texts": ["т"],
            "href": "https://e.com",
            "display_url_path": "u" * 21,
        },
        {"titles": ["з"], "texts": ["т"], "href": "https://e.com", "age_label": 17},
    ],
)
def test_responsive_ad_validation(kwargs: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ResponsiveAd(**kwargs).to_payload()


def test_responsive_ad_allows_business_id_without_href() -> None:
    payload = ResponsiveAd(titles=["з"], texts=["т"], business_id=42).to_payload()
    assert payload["BusinessId"] == 42
    assert "Href" not in payload


# ---------------- F-2B.4: группа ЕПК ----------------


def test_unified_ad_group_payload_and_geo() -> None:
    group = UnifiedAdGroup(
        name="ЕПК группа",
        campaign_id=100,
        region_ids=[225, 1030],
        offer_retargeting="YES",
        tracking_params="utm_source=epk",
    )
    assert group.to_payload() == {
        "CampaignId": 100,
        "Name": "ЕПК группа",
        "RegionIds": [225, 1030],
        "TrackingParams": "utm_source=epk",
        "UnifiedAdGroup": {"OfferRetargeting": "YES"},
    }
    with pytest.raises(ValidationError):
        UnifiedAdGroup(
            name="g", campaign_id=1, region_ids=[0]
        ).to_payload()
    with pytest.raises(ValidationError):
        UnifiedAdGroup(
            name="g", campaign_id=1, region_ids=[225], offer_retargeting="MAYBE"
        ).to_payload()


# ---------------- F-2B.6: маршрутизация v5/v501 ----------------


@responses.activate
def test_create_unified_routes_to_v501() -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_V501_URL,
        json={"result": {"AddResults": [{"Id": 501}]}},
    )
    with _client() as c:
        result = c.campaigns.create_unified(
            UnifiedCampaign(
                name="ЕПК",
                start_date=START,
                search=UnifiedStrategy(strategy="AVERAGE_CPC", average_cpc=10),
            )
        )
    assert result["Id"] == 501
    assert responses.calls[0].request.url == CAMPAIGNS_V501_URL


@responses.activate
def test_create_with_unified_builder_routes_to_v501() -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_V501_URL,
        json={"result": {"AddResults": [{"Id": 502}]}},
    )
    with _client() as c:
        result = c.campaigns.create(
            UnifiedCampaign(
                name="ЕПК",
                start_date=START,
                search=UnifiedStrategy(strategy="AVERAGE_CPC", average_cpc=10),
            )
        )
    assert result["Id"] == 502
    assert responses.calls[0].request.url == CAMPAIGNS_V501_URL


@responses.activate
def test_v5_campaigns_stay_on_v5() -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={"result": {"AddResults": [{"Id": 1}]}},
    )
    with _client() as c:
        c.campaigns.create(
            {
                "Name": "Классика",
                "StartDate": "2026-10-01",
                "CpmBannerCampaign": {
                    "BiddingStrategy": {
                        "Search": {"BiddingStrategyType": "SERVING_OFF"},
                        "Network": {
                            "BiddingStrategyType": "MANUAL_CPM",
                            "ManualCpm": {"WeeklySpendLimit": 100},
                        },
                    }
                },
            }
        )
    assert responses.calls[0].request.url == CAMPAIGNS_V5_URL


@responses.activate
def test_update_and_get_unified_use_v501() -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_V501_URL,
        json={"result": {"UpdateResults": [{"Id": 501}]}},
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V501_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 501,
                        "Name": "ЕПК",
                        "UnifiedCampaign": {
                            "BiddingStrategy": {
                                "Search": {
                                    "BiddingStrategyType": "AVERAGE_CPA",
                                    "AverageCpa": {"WeeklySpendLimit": 1},
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as c:
        updated = c.campaigns.update_unified(
            UnifiedCampaign(
                name="ЕПК",
                search=UnifiedStrategy(
                    strategy="AVERAGE_CPA", weekly_budget=1, goal_id=182
                ),
            ).to_update_payload(501)
        )
        read = c.campaigns.get_unified([501])
    assert updated["Id"] == 501
    assert read[0].id == 501
    assert "UnifiedCampaign" in _body_of(responses.calls[1])["params"]["FieldNames"]


@responses.activate
def test_delete_unified_requires_confirm() -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.campaigns.delete_unified([501])
    assert len(responses.calls) == 0


@responses.activate
def test_delete_unified_routes_to_v501() -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_V501_URL,
        json={"result": {"DeleteResults": [{"Id": 501}]}},
    )
    with _client() as c:
        removed = c.campaigns.delete_unified([501], confirm=True)
    assert removed[0]["Id"] == 501
    assert responses.calls[0].request.url == CAMPAIGNS_V501_URL


@responses.activate
def test_unified_ad_group_create_routes_to_v501() -> None:
    responses.add(
        responses.POST,
        ADGROUPS_V501_URL,
        json={"result": {"AddResults": [{"Id": 77}]}},
    )
    with _client() as c:
        res = c.ad_groups.create(
            [UnifiedAdGroup(name="ЕПК", campaign_id=501, region_ids=[225])]
        )
    assert res[0]["Id"] == 77
    assert responses.calls[0].request.url == ADGROUPS_V501_URL


@responses.activate
def test_create_responsive_ad_routes_to_v501() -> None:
    responses.add(
        responses.POST, ADS_V501_URL, json={"result": {"AddResults": [{"Id": 31}]}}
    )
    with _client() as c:
        result = c.ads.create_responsive_ad(
            77,
            ["Печатки на заказ"],
            ["Изготовление печаток из золота"],
            href="https://example.com",
            ad_image_hashes=["h1"],
        )
    assert result["Id"] == 31
    assert responses.calls[0].request.url == ADS_V501_URL
    sent = _body_of(responses.calls[0])["params"]["Ads"][0]
    assert sent["ResponsiveAd"]["AdImageHashes"] == ["h1"]


@responses.activate
def test_responsive_ad_validation_sends_nothing() -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.ads.create_responsive_ad(77, ["з" * 60], ["т"], href="https://e.com")
    assert len(responses.calls) == 0


# ---------------- D11: полная автоматизация через ЕПК ----------------

ADIMAGES_V5_URL = "https://api.direct.yandex.com/json/v5/adimages/"

#: Минимальный валидный base64 (1x1 PNG).
PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


@responses.activate
def test_epk_image_flow_is_fully_automatic() -> None:
    """Plan Б (D11): картинка загружается через API и уходит в объявление ЕПК.

    Сценарий целиком: `adimages/add` → `AdImageHash` → `ResponsiveAd.AdImageHashes`.
    Ручных шагов (веб-интерфейс) не требуется — в отличие от классической
    CPM-РСЯ, которой нужен `CreativeId` из конструктора креативов.
    """
    responses.add(
        responses.POST,
        ADIMAGES_V5_URL,
        json={"result": {"AddResults": [{"AdImageHash": "hash-abc"}]}},
    )
    responses.add(
        responses.POST,
        ADS_V501_URL,
        json={"result": {"AddResults": [{"Id": 32}]}},
    )
    with _client() as c:
        image = c.ad_images.add("Баннер", PNG_BASE64)
        ad = c.ads.create_responsive_ad(
            77,
            ["Печатки на заказ"],
            ["Изготовление печаток из золота"],
            href="https://example.com",
            ad_image_hashes=[image["AdImageHash"]],
        )
    assert ad["Id"] == 32
    uploaded = _body_of(responses.calls[0])["params"]["AdImages"][0]
    assert uploaded["ImageData"] == PNG_BASE64
    sent = _body_of(responses.calls[1])["params"]["Ads"][0]
    assert sent["ResponsiveAd"]["AdImageHashes"] == ["hash-abc"]
    assert responses.calls[1].request.url == ADS_V501_URL


# ---------------- readonly / confirm ----------------


def test_2b_readonly_blocks_unified_methods() -> None:
    with _client(readonly=True) as c:
        with pytest.raises(ValidationError):
            c.campaigns.create_unified(
                UnifiedCampaign(
                    name="ЕПК",
                    start_date=START,
                    search=UnifiedStrategy(strategy="AVERAGE_CPC", average_cpc=10),
                )
            )
        with pytest.raises(ValidationError):
            c.campaigns.update_unified({"Id": 1, "Name": "x"})
        with pytest.raises(ValidationError):
            c.campaigns.delete_unified([1], confirm=True)
        with pytest.raises(ValidationError):
            c.ads.create_responsive_ad(1, ["з"], ["т"], href="https://e.com")
    assert len(responses.calls) == 0
