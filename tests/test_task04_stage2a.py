"""Тесты слоя 2А STAGE_05: классическая РСЯ (v5) — кампании, группы, объявления, креативы.

Идентификаторы критериев приёмки:
- F-2A.1 — билдеры кампаний по фактическому контракту `campaigns/add`
  (вложенный блок типа, недельный бюджет в стратегии), деньги в единицах
  ×1 000 000, валидация;
- F-2A.2 — билдеры групп: тип задаётся пустой структурой, `Type` в add не
  отправляется, `region_ids=[0]` → ошибка;
- F-2A.3 — `CpmBannerAdBuilderAd` (медийное объявление по креативу),
  `AdImageService` по `AdImageHash`, `CreativesService`;
- D2 — `AdImage` → `ImageAdRef` (алиас сохранён).

Все payload'ы сверены с документацией (снимок 30.09.2026):
campaigns/add-cpm-banner-campaign, adgroups/add, ads/add, adimages/add|get|delete,
creatives/get.
"""
from __future__ import annotations

import base64
import datetime as _dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.exceptions import ValidationError
from yandex_direct_api_client.models.ad import (
    AdImage,
    CpmBannerAdBuilderAd,
    ImageAdRef,
)
from yandex_direct_api_client.models.ad_group import AdGroup
from yandex_direct_api_client.models.ad_group_payloads import (
    CpmBannerAdGroup,
    SmartAdGroup,
    TextAdGroup,
    build_ad_group,
)
from yandex_direct_api_client.models.batch import BatchResult
from yandex_direct_api_client.models.campaign_payloads import (
    CpmBannerCampaign,
    FrequencyCap,
    TextCampaign,
    build_campaign,
)
from yandex_direct_api_client.money import (
    from_money_units,
    monthly_to_weekly,
    to_money_units,
)

CAMPAIGNS_URL = "https://api.direct.yandex.com/json/v5/campaigns/"
ADGROUPS_URL = "https://api.direct.yandex.com/json/v5/adgroups/"
ADS_URL = "https://api.direct.yandex.com/json/v5/ads/"
ADIMAGES_URL = "https://api.direct.yandex.com/json/v5/adimages/"
CREATIVES_URL = "https://api.direct.yandex.com/json/v5/creatives/"

#: Минимальный валидный base64 (1x1 PNG).
PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)

#: Дата старта по умолчанию для тестов (StartDate обязателен при add).
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


# ---------------- F-3.1: деньги ----------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, 1_000_000),
        (5.5, 5_500_000),
        ("12.34", 12_340_000),
        (0.1, 100_000),
        (0.0000015, 2),
    ],
)
def test_money_to_units(value: Any, expected: int) -> None:
    assert to_money_units(value) == expected


def test_money_roundtrip() -> None:
    assert from_money_units(to_money_units(1234.56)) == Decimal("1234.56")
    assert from_money_units(None) == 0


def test_money_rejects_garbage() -> None:
    for bad in ("abc", None, True, float("nan")):
        with pytest.raises(ValidationError):
            to_money_units(bad)  # type: ignore[arg-type]


def test_monthly_to_weekly_is_explicit() -> None:
    weekly = monthly_to_weekly(20_000)
    assert weekly == Decimal("4599.59")
    with pytest.raises(ValidationError):
        monthly_to_weekly(0)


# ---------------- F-2A.1: билдеры кампаний ----------------


def test_cpm_banner_payload_snapshot() -> None:
    """РСЯ-кампания: типовой блок вложен, бюджет недельный и внутри стратегии."""
    campaign = CpmBannerCampaign(
        name="РСЯ печатки",
        weekly_budget=5_000,
        start_date=START,
        end_date=_dt.date(2026, 12, 31),
        time_zone="Europe/Moscow",
        tracking_params="utm_source=test",
        counter_ids=[1234],
    )
    assert campaign.to_payload() == {
        "Name": "РСЯ печатки",
        "StartDate": "2026-10-01",
        "EndDate": "2026-12-31",
        "TimeZone": "Europe/Moscow",
        "TrackingParams": "utm_source=test",
        "CpmBannerCampaign": {
            "BiddingStrategy": {
                "Search": {"BiddingStrategyType": "SERVING_OFF"},
                "Network": {
                    "BiddingStrategyType": "MANUAL_CPM",
                    "ManualCpm": {"WeeklySpendLimit": 5_000_000_000},
                },
            },
            "CounterIds": {"Items": [1234]},
        },
    }


def test_cpm_banner_requires_weekly_budget() -> None:
    with pytest.raises(ValidationError) as exc:
        CpmBannerCampaign(name="x", start_date=START).to_payload()
    assert "weekly_budget" in str(exc.value)
    with pytest.raises(ValidationError):
        CpmBannerCampaign(name="x", weekly_budget=-1, start_date=START).to_payload()


def test_cpm_banner_strategy_escape_hatch_is_exclusive() -> None:
    campaign = CpmBannerCampaign(
        name="РСЯ",
        start_date=START,
        bidding_strategy={
            "BiddingStrategyType": "WB_MAXIMUM_IMPRESSIONS",
            "WbMaximumImpressions": {"AverageCpm": 5_000_000, "SpendLimit": 900_000_000},
        },
    )
    block = campaign.to_payload()["CpmBannerCampaign"]["BiddingStrategy"]["Network"]
    assert block["BiddingStrategyType"] == "WB_MAXIMUM_IMPRESSIONS"
    with pytest.raises(ValidationError):
        CpmBannerCampaign(
            name="РСЯ",
            start_date=START,
            weekly_budget=100,
            bidding_strategy={"BiddingStrategyType": "MANUAL_CPM"},
        ).to_payload()


def test_cpm_banner_optional_blocks() -> None:
    campaign = CpmBannerCampaign(
        name="РСЯ",
        start_date=START,
        weekly_budget=100,
        settings=[{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
        frequency_cap=FrequencyCap(impressions=1, period_days=7),
        video_target="VIEWS",
        excluded_sites_for_video_ads=["example.com"],
    )
    block = campaign.to_payload()["CpmBannerCampaign"]
    assert block["Settings"] == [{"Option": "ADD_METRICA_TAG", "Value": "YES"}]
    assert block["FrequencyCap"] == {"Impressions": 1, "PeriodDays": 7}
    assert block["VideoTarget"] == "VIEWS"
    assert block["ExcludedSitesForVideoAds"] == {"Items": ["example.com"]}


def test_cpm_banner_defaults_strategy_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        campaign = CpmBannerCampaign(
            name="РСЯ", start_date=START, weekly_budget=100
        )
        network = campaign.to_payload()["CpmBannerCampaign"]["BiddingStrategy"]["Network"]
    assert network["BiddingStrategyType"] == "MANUAL_CPM"
    assert any("MANUAL_CPM за бизнес" in r.message for r in caplog.records)


def test_cpm_banner_no_warning_when_strategy_given(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        campaign = CpmBannerCampaign(
            name="РСЯ", start_date=START,
            bidding_strategy={"BiddingStrategyType": "MAXIMUM_REACH", "MaximumReach": {}},
        )
        campaign.to_payload()
    assert not [r for r in caplog.records if "MANUAL_CPM за бизнес" in r.message]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"video_target": "SOUND"},
        {"settings": [{"Option": "UNKNOWN", "Value": "YES"}]},
        {"counter_ids": [0]},
        {"frequency_cap": FrequencyCap(impressions=1, period_days=31)},
    ],
)
def test_cpm_banner_validates_blocks(kwargs: Dict[str, Any]) -> None:
    campaign = CpmBannerCampaign(
        name="РСЯ", start_date=START, weekly_budget=100, **kwargs
    )
    with pytest.raises(ValidationError):
        campaign.to_payload()


def test_cpm_banner_start_date_required_on_add() -> None:
    with pytest.raises(ValidationError) as exc:
        CpmBannerCampaign(name="РСЯ", weekly_budget=100).to_payload()
    assert "StartDate" in str(exc.value)


def test_campaign_name_and_dates_validated() -> None:
    with pytest.raises(ValidationError):
        CpmBannerCampaign(name="").validate()
    with pytest.raises(ValidationError):
        CpmBannerCampaign(name="x" * 256).validate()
    with pytest.raises(ValidationError):
        CpmBannerCampaign(
            name="x",
            start_date=_dt.date(2026, 10, 2),
            end_date=_dt.date(2026, 10, 1),
        ).validate()


def test_daily_budget_escape_hatch_is_structured() -> None:
    campaign = CpmBannerCampaign(
        name="РСЯ", start_date=START, weekly_budget=100, daily_budget=50
    )
    assert campaign.to_payload()["DailyBudget"] == {
        "Amount": 50_000_000,
        "Mode": "STANDARD",
    }
    with pytest.raises(ValidationError):
        CpmBannerCampaign(
            name="РСЯ", start_date=START, weekly_budget=1, daily_budget_mode="HOURS"
        ).validate()


def test_text_campaign_payload_snapshot() -> None:
    campaign = TextCampaign(name="Поиск", start_date=START, weekly_budget=700)
    assert campaign.to_payload()["TextCampaign"] == {
        "BiddingStrategy": {
            "Search": {
                "BiddingStrategyType": "AVERAGE_CPC",
                "AverageCpc": {"WeeklySpendLimit": 700_000_000},
            },
            "Network": {"BiddingStrategyType": "SERVING_OFF"},
        }
    }


def test_text_campaign_defaults_strategy_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        campaign = TextCampaign(name="Поиск", start_date=START, weekly_budget=700)
        search = campaign.to_payload()["TextCampaign"]["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPC"
    assert any("AVERAGE_CPC за бизнес" in r.message for r in caplog.records)


def test_text_campaign_no_warning_when_strategy_given(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        campaign = TextCampaign(
            name="Поиск", start_date=START,
            bidding_strategy={"BiddingStrategyType": "AVERAGE_CPA", "AverageCpa": {}},
        )
        campaign.to_payload()
    assert not [r for r in caplog.records if "AVERAGE_CPC за бизнес" in r.message]


def test_build_campaign_dispatch_and_unknown_kind() -> None:
    assert isinstance(
        build_campaign(
            "CPM_BANNER_CAMPAIGN", name="c", weekly_budget=10, start_date=START
        ),
        CpmBannerCampaign,
    )
    with pytest.raises(ValidationError) as exc:
        build_campaign("SMART_CAMPAIGN", name="c", weekly_budget=10)
    assert "SMART_CAMPAIGN" in str(exc.value)


def test_campaign_update_payload_has_id_and_strategy() -> None:
    campaign = CpmBannerCampaign(name="new", weekly_budget=200)
    payload = campaign.to_update_payload(42)
    assert payload["Id"] == 42
    assert payload["Name"] == "new"
    assert "StartDate" not in payload
    network = payload["CpmBannerCampaign"]["BiddingStrategy"]["Network"]
    assert network["ManualCpm"] == {"WeeklySpendLimit": 200_000_000}


@responses.activate
def test_campaigns_create_sends_nested_block() -> None:
    responses.add(
        responses.POST, CAMPAIGNS_URL, json={"result": {"AddResults": [{"Id": 77}]}}
    )
    with _client() as c:
        result = c.campaigns.create(
            CpmBannerCampaign(name="РСЯ", start_date=START, weekly_budget=1000)
        )
    assert result["Id"] == 77
    sent = _body_of(responses.calls[0])["params"]["Campaigns"][0]
    assert sent["CpmBannerCampaign"]["BiddingStrategy"]["Network"]["ManualCpm"] == {
        "WeeklySpendLimit": 1_000_000_000
    }


# ---------------- F-2A.2: группы объявлений ----------------


def test_cpm_banner_ad_group_payload_snapshot() -> None:
    group = CpmBannerAdGroup(name="РСЯ группа", campaign_id=100, region_ids=[225, 1030])
    assert group.to_payload() == {
        "CampaignId": 100,
        "Name": "РСЯ группа",
        "RegionIds": [225, 1030],
        "CpmBannerKeywordsAdGroup": {},
    }


def test_cpm_banner_user_profile_subtype() -> None:
    group = CpmBannerAdGroup(
        name="Профиль",
        campaign_id=1,
        region_ids=[225],
        subtype="USER_PROFILE",
    )
    assert group.to_payload()["CpmBannerUserProfileAdGroup"] == {}
    with pytest.raises(ValidationError):
        CpmBannerAdGroup(
            name="Профиль",
            campaign_id=1,
            region_ids=[225],
            subtype="USER_PROFILE",
            negative_keywords=["купить"],
        ).to_payload()
    with pytest.raises(ValidationError):
        CpmBannerAdGroup(
            name="x", campaign_id=1, region_ids=[225], subtype="NOPE"
        ).to_payload()


def test_ad_group_model_does_not_send_type() -> None:
    """G4: тип задаётся структурой, `Type` в add не отправляется."""
    model = AdGroup(
        id=0,
        campaign_id=1,
        name="g",
        type="CPM_BANNER_AD_GROUP",
        region_ids=[225],
    )
    assert "Type" not in model.to_new_payload()
    assert "Type" not in model.to_update_payload()


def test_group_region_zero_rejected() -> None:
    with pytest.raises(ValidationError):
        CpmBannerAdGroup(name="g", campaign_id=1, region_ids=[0]).to_payload()
    with pytest.raises(ValidationError):
        CpmBannerAdGroup(name="g", campaign_id=1, region_ids=[]).to_payload()


def test_group_shared_sets_and_tracking_limits() -> None:
    with pytest.raises(ValidationError):
        CpmBannerAdGroup(
            name="g", campaign_id=1, region_ids=[225],
            negative_keywords_shared_set_ids=[1, 2, 3, 4],
        ).to_payload()
    with pytest.raises(ValidationError):
        CpmBannerAdGroup(
            name="g", campaign_id=1, region_ids=[225], tracking_params="u" * 1025
        ).to_payload()


def test_smart_ad_group_optional_feed() -> None:
    assert SmartAdGroup(name="s", campaign_id=1, region_ids=[225]).to_payload() == {
        "CampaignId": 1,
        "Name": "s",
        "RegionIds": [225],
    }
    group = SmartAdGroup(name="s", campaign_id=1, region_ids=[225], feed_id=42)
    assert group.to_payload()["SmartAdGroup"] == {"FeedId": 42}
    with pytest.raises(ValidationError):
        SmartAdGroup(name="s", campaign_id=1, region_ids=[225], feed_id=0).to_payload()


def test_build_ad_group_and_update_payload() -> None:
    group = build_ad_group(
        "TEXT_AD_GROUP", name="t", campaign_id=1, region_ids=[225]
    )
    assert isinstance(group, TextAdGroup)
    assert group.to_update_payload(7) == {
        "Name": "t",
        "RegionIds": [225],
        "Id": 7,
    }
    with pytest.raises(ValidationError):
        build_ad_group("NOPE", name="t", campaign_id=1, region_ids=[225])


@responses.activate
def test_ad_groups_create_accepts_builder() -> None:
    responses.add(
        responses.POST, ADGROUPS_URL, json={"result": {"AddResults": [{"Id": 5}]}}
    )
    with _client() as c:
        res = c.ad_groups.create(
            [CpmBannerAdGroup(name="РСЯ", campaign_id=100, region_ids=[225])]
        )
    assert res[0]["Id"] == 5
    sent = _body_of(responses.calls[0])["params"]["AdGroups"][0]
    assert sent["CpmBannerKeywordsAdGroup"] == {}
    assert sent["RegionIds"] == [225]
    assert "Type" not in sent


@responses.activate
def test_ad_groups_create_rejects_bad_regions_without_request() -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.ad_groups.create(
                [CpmBannerAdGroup(name="РСЯ", campaign_id=100, region_ids=[0])]
            )
    assert len(responses.calls) == 0


# ---------------- F-2A.3: объявления РСЯ ----------------


def test_cpm_banner_ad_payload_and_validation() -> None:
    ad = CpmBannerAdBuilderAd(creative_id=1234, href="https://example.com/jewelry")
    assert ad.to_payload() == {
        "Creative": {"CreativeId": 1234},
        "Href": "https://example.com/jewelry",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"creative_id": 0, "href": "https://e.com"},
        {"creative_id": 1},
        {"creative_id": 1, "href": "e.com"},
        {"creative_id": 1, "turbo_page_id": 1, "tracking_pixels": ["a", "b", "c"]},
    ],
)
def test_cpm_banner_ad_validation(kwargs: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CpmBannerAdBuilderAd(**kwargs).to_payload()


@responses.activate
def test_create_rsya_banner_body() -> None:
    responses.add(responses.POST, ADS_URL, json={"result": {"AddResults": [{"Id": 9}]}})
    with _client() as c:
        res = c.ads.create_rsya_banner(55, 1234, href="https://example.com")
    assert res["Id"] == 9
    sent = _body_of(responses.calls[0])["params"]["Ads"][0]
    assert sent["AdGroupId"] == 55
    assert sent["CpmBannerAdBuilderAd"]["Creative"] == {"CreativeId": 1234}


@responses.activate
def test_create_rsya_banner_without_creative_sends_nothing() -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.ads.create_rsya_banner(55, 0, href="https://e.com")
    assert len(responses.calls) == 0


def test_ad_image_alias_is_preserved() -> None:
    """D2: `AdImage` остаётся алиасом `ImageAdRef`."""
    assert AdImage is ImageAdRef
    assert AdImage(image_hash="x").to_payload() == {"AdImageHash": "x"}
    with pytest.raises(ValidationError):
        AdImage().to_payload()


# ---------------- F-2A.3: AdImageService ----------------


@responses.activate
def test_ad_images_add_base64() -> None:
    responses.add(
        responses.POST,
        ADIMAGES_URL,
        json={"result": {"AddResults": [{"AdImageHash": "abc123"}]}},
    )
    with _client() as c:
        res = c.ad_images.add("Картинка 1", PNG_BASE64, type_="WIDE")
    assert res["AdImageHash"] == "abc123"
    sent = _body_of(responses.calls[0])["params"]["AdImages"][0]
    assert sent == {"Name": "Картинка 1", "ImageData": PNG_BASE64, "Type": "WIDE"}


@responses.activate
def test_ad_images_add_collect_mode() -> None:
    responses.add(
        responses.POST,
        ADIMAGES_URL,
        json={"result": {"AddResults": [{"Errors": [{"Code": 3, "Message": "bad"}]}]}},
    )
    with _client() as c:
        result = c.ad_images.add("Картинка", PNG_BASE64, on_item_error="collect")
    assert isinstance(result, BatchResult)
    assert result.failed[0].code == 3


def test_ad_images_rejects_invalid_base64() -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.ad_images.add("Картинка", "не base64 !!!")
    assert len(responses.calls) == 0


def test_ad_images_rejects_empty_name_and_data() -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.ad_images.add("", PNG_BASE64)
        with pytest.raises(ValidationError):
            c.ad_images.add("Имя", "   ")
        with pytest.raises(ValidationError):
            c.ad_images.add("Имя", PNG_BASE64, type_="HUGO")


@responses.activate
def test_ad_images_add_from_file(tmp_path: Path) -> None:
    path = tmp_path / "creative.png"
    path.write_bytes(base64.b64decode(PNG_BASE64))
    responses.add(
        responses.POST,
        ADIMAGES_URL,
        json={"result": {"AddResults": [{"AdImageHash": "h1"}]}},
    )
    with _client() as c:
        res = c.ad_images.add_from_file(path)
    assert res["AdImageHash"] == "h1"
    sent = _body_of(responses.calls[0])["params"]["AdImages"][0]
    assert sent == {"Name": "creative", "ImageData": PNG_BASE64}


def test_ad_images_add_from_file_bad_format(tmp_path: Path) -> None:
    path = tmp_path / "creative.bmp"
    path.write_bytes(b"BM")
    with _client() as c:
        with pytest.raises(ValidationError) as exc:
            c.ad_images.add_from_file(path)
    assert "Неподдерживаемый формат" in str(exc.value)
    assert len(responses.calls) == 0


def test_ad_images_add_from_file_missing(tmp_path: Path) -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.ad_images.add_from_file(tmp_path / "нет-такого.png")


@responses.activate
def test_ad_images_get_and_list() -> None:
    responses.add(
        responses.POST,
        ADIMAGES_URL,
        json={"result": {"AdImages": [{"AdImageHash": "h1", "Name": "n"}]}},
    )
    responses.add(
        responses.POST,
        ADIMAGES_URL,
        json={"result": {"AdImages": [{"AdImageHash": "h2", "Name": "m"}]}},
    )
    with _client() as c:
        one = c.ad_images.get(["h1"])
        page = c.ad_images.list()
    assert one[0]["AdImageHash"] == "h1"
    assert _body_of(responses.calls[0])["params"]["SelectionCriteria"] == {
        "AdImageHashes": ["h1"]
    }
    assert page[0]["AdImageHash"] == "h2"
    assert _body_of(responses.calls[1])["params"]["SelectionCriteria"] == {}


@responses.activate
def test_ad_images_delete_requires_confirm_and_sends_hashes() -> None:
    responses.add(
        responses.POST, ADIMAGES_URL, json={"result": {"DeleteResults": [{"AdImageHash": "h1"}]}}
    )
    with _client() as c:
        removed = c.ad_images.delete(["h1"], confirm=True)
    assert removed[0]["AdImageHash"] == "h1"
    assert _body_of(responses.calls[0])["method"] == "delete"
    assert _body_of(responses.calls[0])["params"] == {
        "SelectionCriteria": {"AdImageHashes": ["h1"]}
    }


def test_ad_images_delete_requires_confirm() -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.ad_images.delete(["h1"])
    assert len(responses.calls) == 0


def test_ad_images_rejects_non_string_hash() -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.ad_images.get([123])


@responses.activate
def test_ad_images_readonly_blocks_mutations() -> None:
    with _client(readonly=True) as c:
        with pytest.raises(ValidationError):
            c.ad_images.add("Картинка", PNG_BASE64)
        with pytest.raises(ValidationError):
            c.ad_images.delete(["h1"], confirm=True)
    assert len(responses.calls) == 0


# ---------------- F-2A.3: CreativesService ----------------


@responses.activate
def test_creatives_get_and_image_ids() -> None:
    responses.add(
        responses.POST,
        CREATIVES_URL,
        json={
            "result": {
                "Creatives": [
                    {"Id": 11, "Type": "IMAGE_CREATIVE", "Name": "Печатки"},
                    {"Id": 12, "Type": "IMAGE_CREATIVE", "Name": "Другое"},
                ]
            }
        },
    )
    with _client() as c:
        all_creatives = c.creatives.get()
        ids = c.creatives.image_creative_ids(names=["Печатки"])
    assert [item["Id"] for item in all_creatives] == [11, 12]
    assert ids == [11]
    assert _body_of(responses.calls[0])["params"]["SelectionCriteria"] == {}
    assert _body_of(responses.calls[1])["params"]["SelectionCriteria"] == {
        "Types": ["IMAGE_CREATIVE"]
    }


def test_creatives_rejects_unknown_type() -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.creatives.get(types=["POSTER_CREATIVE"])
    assert len(responses.calls) == 0


# ---------------- readonly для новых методов ----------------


def test_2a_readonly_blocks_rsya_helpers() -> None:
    with _client(readonly=True) as c:
        with pytest.raises(ValidationError):
            c.ads.create_rsya_banner(1, 1, href="https://e.com")
        with pytest.raises(ValidationError):
            c.campaigns.create(
                CpmBannerCampaign(name="c", start_date=START, weekly_budget=100)
            )
    assert len(responses.calls) == 0
