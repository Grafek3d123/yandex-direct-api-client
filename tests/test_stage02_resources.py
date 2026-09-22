"""Unit-тесты ключевых фраз (criteria) и ретаргетинг-корректировок."""
from __future__ import annotations

import json

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.exceptions import ApiError, ValidationError
from yandex_direct_api_client.models import (
    AdGroupItem,
    AdGroupItemBids,
    RetargetingBidAdjustment,
)

CRITERIA_URL = "https://api.direct.yandex.com/json/v5/criteria/"
RTA_URL = "https://api.direct.yandex.com/json/v5/retargetingadjustments/"


def _body_of(call: responses.Call) -> dict:
    body = call.request.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body)  # type: ignore[arg-type]


# ---------- ad_group_items.list ----------
@responses.activate
def test_ad_group_items_list(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={
            "result": {
                "AdGroupItems": [
                    {
                        "Id": 1,
                        "CampaignId": 10,
                        "AdGroupId": 100,
                        "Item": {"Type": "KEYWORD", "Phrase": "купить кофе"},
                        "Bid": {"Bid": 30.5, "Currency": "RUB"},
                    }
                ]
            }
        },
        status=200,
    )
    items = client.ad_group_items.list(campaign_ids=[10])
    assert len(items) == 1
    assert items[0].phrase == "купить кофе"
    assert items[0].bid == 30.5
    assert items[0].ad_group_id == 100


@responses.activate
def test_ad_group_items_list_pagination(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={
            "result": {
                "AdGroupItems": [{"Id": 1}, {"Id": 2}],
                "LimitedBy": 2,
            }
        },
        status=200,
    )
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={"result": {"AdGroupItems": [{"Id": 3}]}},
        status=200,
    )
    items = client.ad_group_items.list(ad_group_ids=[5], page_limit=2)
    assert len(items) == 3
    assert len(responses.calls) == 2


# ---------- ad_group_items.get ----------
@responses.activate
def test_ad_group_items_get(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={"result": {"AdGroupItems": [{"Id": 7}]}},
        status=200,
    )
    items = client.ad_group_items.get([7])
    assert items[0].id == 7


def test_ad_group_items_get_empty(client: YandexDirectClient) -> None:
    assert client.ad_group_items.get([]) == []


# ---------- ad_group_items.add ----------
@responses.activate
def test_ad_group_items_add_typed(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={"result": {"AddResults": [{"Id": 500}]}},
        status=200,
    )
    item = AdGroupItem(
        id=0,
        type="KEYWORD",
        campaign_id=10,
        ad_group_id=100,
        phrase="чай",
        bid=25.0,
        currency="RUB",
    )
    res = client.ad_group_items.add([item])
    assert res[0]["Id"] == 500
    payload = _body_of(responses.calls[0])
    sent = payload["params"]["AdGroupItems"][0]
    assert sent["Item"]["Phrase"] == "чай"
    assert sent["Bid"]["Bid"] == 25.0


@responses.activate
def test_ad_group_items_add_raw_dict(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={"result": {"AddResults": [{"Id": 501}]}},
        status=200,
    )
    res = client.ad_group_items.add(
        [{"CampaignId": 1, "AdGroupId": 2, "Item": {"Phrase": "x"}}]
    )
    assert res[0]["Id"] == 501


def test_ad_group_items_add_empty(client: YandexDirectClient) -> None:
    assert client.ad_group_items.add([]) == []


# ---------- ad_group_items.set_bids ----------
@responses.activate
def test_ad_group_items_set_bids(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={"result": {"SetBidsResults": [{"Id": 1}, {"Id": 2}]}},
        status=200,
    )
    res = client.ad_group_items.set_bids(
        [
            AdGroupItemBids(id=1, bid=40.0),
            {"Id": 2, "Bids": {"Bid": 50.0}},
        ],
        confirm=True,
    )
    assert len(res) == 2
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "setbids"
    assert payload["params"]["AdGroupItems"][0]["Bids"]["Bid"] == 40.0


@responses.activate
def test_ad_group_items_set_bid_single(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={"result": {"SetBidsResults": [{"Id": 9}]}},
        status=200,
    )
    res = client.ad_group_items.set_bid(9, 77.0)
    assert res["Id"] == 9


def test_ad_group_items_set_bids_requires_confirm(
    client: YandexDirectClient,
) -> None:
    with pytest.raises(ValidationError) as exc:
        client.ad_group_items.set_bids([AdGroupItemBids(id=1, bid=1.0)])
    assert "confirm" in str(exc.value)
    assert len(responses.calls) == 0


# ---------- ad_group_items.delete ----------
@responses.activate
def test_ad_group_items_delete(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={"result": {"DeleteResults": [{"Id": 1}, {"Id": 2}]}},
        status=200,
    )
    res = client.ad_group_items.delete([1, 2], confirm=True)
    assert len(res) == 2


def test_ad_group_items_delete_requires_confirm(
    client: YandexDirectClient,
) -> None:
    with pytest.raises(ValidationError):
        client.ad_group_items.delete([1])
    assert len(responses.calls) == 0


@responses.activate
def test_ad_group_items_delete_item_error(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={
            "result": {
                "DeleteResults": [
                    {"Id": 1, "Errors": [{"Code": 5, "Message": "not found"}]}
                ]
            }
        },
        status=200,
    )
    with pytest.raises(ApiError):
        client.ad_group_items.delete([1], confirm=True)


# ---------- retargeting_adjustments ----------
@responses.activate
def test_rta_list(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        RTA_URL,
        json={
            "result": {
                "RetargetingBidAdjustments": [
                    {
                        "Id": 1,
                        "CampaignId": 10,
                        "SegmentId": 900,
                        "Type": "RETARGETING",
                        "BidDelta": 50.0,
                        "Enabled": "YES",
                    }
                ]
            }
        },
        status=200,
    )
    items = client.retargeting_adjustments.list(campaign_ids=[10])
    assert items[0].segment_id == 900
    assert items[0].bid_delta == 50.0


@responses.activate
def test_rta_get(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        RTA_URL,
        json={"result": {"RetargetingBidAdjustments": [{"Id": 3}]}},
        status=200,
    )
    items = client.retargeting_adjustments.get([3])
    assert items[0].id == 3


@responses.activate
def test_rta_add_typed(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        RTA_URL,
        json={"result": {"AddResults": [{"Id": 77}]}},
        status=200,
    )
    adj = RetargetingBidAdjustment(
        id=0,
        campaign_id=10,
        segment_id=900,
        type="RETARGETING",
        bid_delta=30.0,
    )
    res = client.retargeting_adjustments.add([adj])
    assert res[0]["Id"] == 77
    payload = _body_of(responses.calls[0])
    sent = payload["params"]["RetargetingAdjustments"][0]
    assert sent["SegmentId"] == 900
    assert "Id" not in sent


@responses.activate
def test_rta_update_typed(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        RTA_URL,
        json={"result": {"UpdateResults": [{"Id": 77}]}},
        status=200,
    )
    adj = RetargetingBidAdjustment(
        id=77, campaign_id=10, bid_delta=60.0
    )
    res = client.retargeting_adjustments.update([adj], confirm=True)
    assert res[0]["Id"] == 77
    payload = _body_of(responses.calls[0])
    sent = payload["params"]["RetargetingAdjustments"][0]
    assert sent["Id"] == 77
    assert sent["BidDelta"] == 60.0


def test_rta_update_requires_confirm(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.retargeting_adjustments.update([{"Id": 1}])
    assert len(responses.calls) == 0


@responses.activate
def test_rta_delete(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        RTA_URL,
        json={"result": {"DeleteResults": [{"Id": 77}]}},
        status=200,
    )
    res = client.retargeting_adjustments.delete([77], confirm=True)
    assert res[0]["Id"] == 77


def test_rta_delete_requires_confirm(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.retargeting_adjustments.delete([1])
    assert len(responses.calls) == 0


# ---------- ads.create_with_payload ----------
@responses.activate
def test_ads_create_with_payload(client: YandexDirectClient) -> None:
    from yandex_direct_api_client.models import AdImage, AdText

    responses.add(
        responses.POST,
        "https://api.direct.yandex.com/json/v5/ads/",
        json={"result": {"AddResults": [{"Id": 123}]}},
        status=200,
    )
    res = client.ads.create_with_payload(
        10,
        AdText(title="T", text="B", href="https://x.example"),
        image=AdImage(image_id="img-1"),
        ad_group_id=20,
    )
    assert res["Id"] == 123
    payload = _body_of(responses.calls[0])
    sent = payload["params"]["Ads"][0]
    assert sent["CampaignId"] == 10
    assert sent["AdGroupId"] == 20
    assert sent["TextAd"]["Title"] == "T"
    assert sent["ImageAd"]["ImageId"] == "img-1"


# ---------- readonly ----------
def test_readonly_blocks_ad_group_items(client: YandexDirectClient) -> None:
    ro = YandexDirectClient(
        token="t", client_login="L", readonly=True, rate_limit_rps=1000.0
    )
    try:
        with pytest.raises(ValidationError):
            ro.ad_group_items.add([])
        with pytest.raises(ValidationError):
            ro.ad_group_items.set_bids([], confirm=True)
        with pytest.raises(ValidationError):
            ro.ad_group_items.delete([1], confirm=True)
        with pytest.raises(ValidationError):
            ro.retargeting_adjustments.add([])
        with pytest.raises(ValidationError):
            ro.retargeting_adjustments.update([], confirm=True)
        with pytest.raises(ValidationError):
            ro.retargeting_adjustments.delete([1], confirm=True)
    finally:
        ro.close()
