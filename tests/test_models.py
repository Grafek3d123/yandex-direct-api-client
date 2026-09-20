"""Unit-тесты для `yandex_direct_api_client.models`."""
from __future__ import annotations

from yandex_direct_api_client.models import (
    Ad,
    AdText,
    AdTextEntry,
    Campaign,
    StatRow,
    TokenResponse,
)


def test_campaign_from_dict() -> None:
    c = Campaign.from_dict(
        {"Id": 123, "Name": "Моя кампания", "Status": "DRAFT", "State": "ON"}
    )
    assert c.id == 123
    assert c.name == "Моя кампания"
    assert c.status == "DRAFT"
    assert c.state == "ON"


def test_campaign_from_dict_with_missing_fields() -> None:
    c = Campaign.from_dict({"Id": "456", "Name": "X"})
    assert c.id == 456  # строка конвертируется
    assert c.status is None
    assert c.state is None


def test_ad_from_dict_with_text() -> None:
    raw = {
        "Id": 100500,
        "AdGroupId": 42,
        "CampaignId": 7,
        "Status": "ACCEPTED",
        "State": "ON",
        "Type": "TEXT_AD",
        "TextAd": {"Title": "Заголовок", "Text": "Текст", "Href": "site.ru"},
    }
    ad = Ad.from_dict(raw)
    assert ad.id == 100500
    assert ad.campaign_id == 7
    assert ad.text_ad is not None
    assert isinstance(ad.text_ad, AdText)
    assert ad.text_ad.title == "Заголовок"
    assert ad.text_ad.text == "Текст"
    assert ad.text_ad.href == "site.ru"


def test_ad_text_from_none() -> None:
    ad_text = AdText.from_dict(None)
    assert ad_text.title == ""
    assert ad_text.text == ""
    assert ad_text.href == ""


def test_ad_text_entry_from_dict() -> None:
    e = AdTextEntry.from_dict(
        {"Id": 5, "TextAd": {"Title": "T", "Text": "B", "Href": "H"}}
    )
    assert e.id == 5
    assert e.text_ad.title == "T"
    assert e.text_ad.text == "B"


def test_stat_row_from_tsv_row_full() -> None:
    parts = ["123", "1000", "20", "2.00", "1500000", "10.5", "5"]
    row = StatRow.from_tsv_row(parts)
    assert row is not None
    assert row.ad_id == 123
    assert row.impressions == 1000
    assert row.clicks == 20
    assert row.ctr == 2.0
    # Cost из микрорублей
    assert row.cost == 1.5
    assert row.bounce_rate == 10.5
    assert row.bounces == 5


def test_stat_row_from_tsv_row_minimal() -> None:
    parts = ["999", "100", "1", "1.0", "50000"]
    row = StatRow.from_tsv_row(parts)
    assert row is not None
    assert row.ad_id == 999
    assert row.bounce_rate == 0.0
    assert row.bounces == 0


def test_stat_row_from_tsv_row_invalid() -> None:
    assert StatRow.from_tsv_row(["abc", "1", "2", "3", "4"]) is None
    assert StatRow.from_tsv_row(["1", "2"]) is None


def test_stat_row_merged_with() -> None:
    a = StatRow(ad_id=1, impressions=100, clicks=1, cost=1.0, bounces=0)
    b = StatRow(ad_id=1, impressions=100, clicks=3, cost=2.0, bounces=1)
    m = a.merged_with(b)
    assert m.impressions == 200
    assert m.clicks == 4
    assert m.ctr == 2.0
    assert m.cost == 3.0
    assert m.bounces == 1


def test_token_response_from_dict() -> None:
    t = TokenResponse.from_dict(
        {
            "access_token": "AAA",
            "refresh_token": "BBB",
            "expires_in": "31536000",
            "token_type": "bearer",
        }
    )
    assert t.access_token == "AAA"
    assert t.refresh_token == "BBB"
    assert t.expires_in == 31536000
    assert t.token_type == "bearer"


def test_token_response_from_dict_no_refresh() -> None:
    t = TokenResponse.from_dict({"access_token": "AAA"})
    assert t.access_token == "AAA"
    assert t.refresh_token is None
    assert t.token_type == "bearer"  # default
