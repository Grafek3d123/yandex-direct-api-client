"""Unit-тесты трека B: negative keywords, audience targets,
retargeting conditions, ad extensions (sitelinks + callouts)."""
from __future__ import annotations

import json

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.exceptions import ApiError, ValidationError
from yandex_direct_api_client.models import (
    AudienceTarget,
    Callout,
    NegativeKeywordSharedSet,
    RetargetingCondition,
    Sitelink,
    SitelinksSet,
)

NK_URL = "https://api.direct.yandex.com/json/v5/negativekeywordsharedsets/"
AT_URL = "https://api.direct.yandex.com/json/v5/audiencetargets/"
SL_URL = "https://api.direct.yandex.com/json/v5/sitelinks/"
AE_URL = "https://api.direct.yandex.com/json/v5/adextensions/"


def _body_of(call: responses.Call) -> dict:
    body = call.request.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body)  # type: ignore[arg-type]


# =============== negative_keywords ===============
@responses.activate
def test_negative_keywords_list(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        NK_URL,
        json={
            "result": {
                "NegativeKeywordSharedSets": [
                    {
                        "Id": 1,
                        "Name": "set1",
                        "NegativeKeywords": ["дешево", "б/у"],
                        "Associated": "YES",
                    }
                ]
            }
        },
        status=200,
    )
    items = client.negative_keywords.list()
    assert items[0].name == "set1"
    assert items[0].negative_keywords == ["дешево", "б/у"]
    assert items[0].associated == "YES"


@responses.activate
def test_negative_keywords_get(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        NK_URL,
        json={"result": {"NegativeKeywordSharedSets": [{"Id": 3}]}},
        status=200,
    )
    items = client.negative_keywords.get([3])
    assert items[0].id == 3
    payload = _body_of(responses.calls[0])
    assert payload["params"]["SelectionCriteria"]["Ids"] == [3]


def test_negative_keywords_get_empty(client: YandexDirectClient) -> None:
    assert client.negative_keywords.get([]) == []


@responses.activate
def test_negative_keywords_create_typed(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        NK_URL,
        json={"result": {"AddResults": [{"Id": 10}]}},
        status=200,
    )
    res = client.negative_keywords.create(
        [
            NegativeKeywordSharedSet(
                id=0, name="s", negative_keywords=["x", "y"]
            )
        ]
    )
    assert res[0]["Id"] == 10
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "add"
    sent = payload["params"]["NegativeKeywordSharedSets"][0]
    assert sent["Name"] == "s"
    assert sent["NegativeKeywords"] == ["x", "y"]


@responses.activate
def test_negative_keywords_update(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        NK_URL,
        json={"result": {"UpdateResults": [{"Id": 10}]}},
        status=200,
    )
    res = client.negative_keywords.update(
        [NegativeKeywordSharedSet(id=10, name="renamed")]
    )
    assert res[0]["Id"] == 10
    payload = _body_of(responses.calls[0])
    sent = payload["params"]["NegativeKeywordSharedSets"][0]
    assert sent["Id"] == 10
    assert sent["Name"] == "renamed"


@responses.activate
def test_negative_keywords_delete(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        NK_URL,
        json={"result": {"DeleteResults": [{"Id": 10}]}},
        status=200,
    )
    res = client.negative_keywords.delete([10], confirm=True)
    assert res[0]["Id"] == 10


def test_negative_keywords_delete_requires_confirm(
    client: YandexDirectClient,
) -> None:
    with pytest.raises(ValidationError):
        client.negative_keywords.delete([1])
    assert len(responses.calls) == 0


@responses.activate
def test_negative_keywords_item_error(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        NK_URL,
        json={
            "result": {
                "AddResults": [{"Errors": [{"Code": 5, "Message": "dup"}]}]
            }
        },
        status=200,
    )
    with pytest.raises(ApiError):
        client.negative_keywords.create(
            [NegativeKeywordSharedSet(id=0, name="s", negative_keywords=["x"])]
        )


# =============== audience_targets ===============
@responses.activate
def test_audience_targets_list(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AT_URL,
        json={
            "result": {
                "AudienceTargets": [
                    {
                        "Id": 1,
                        "AdGroupId": 100,
                        "CampaignId": 10,
                        "RetargetingListId": 900,
                        "ContextBid": 30000000,
                        "StrategyPriority": "NORMAL",
                        "State": "ON",
                    }
                ]
            }
        },
        status=200,
    )
    items = client.audience_targets.list(campaign_ids=[10])
    assert items[0].retargeting_list_id == 900
    assert items[0].context_bid == 30000000
    assert items[0].state == "ON"


@responses.activate
def test_audience_targets_create_typed(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AT_URL,
        json={"result": {"AddResults": [{"Id": 5}]}},
        status=200,
    )
    res = client.audience_targets.create(
        [
            AudienceTarget(
                id=0, ad_group_id=100, retargeting_list_id=900, context_bid=1000
            )
        ]
    )
    assert res[0]["Id"] == 5
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "add"
    sent = payload["params"]["AudienceTargets"][0]
    assert sent["AdGroupId"] == 100
    assert sent["RetargetingListId"] == 900


@responses.activate
def test_audience_targets_set_bids(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AT_URL,
        json={"result": {"SetBidsResults": [{"Id": 5}]}},
        status=200,
    )
    res = client.audience_targets.set_bids(
        [AudienceTarget(id=5, context_bid=5000)]
    )
    assert res[0]["Id"] == 5
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "setBids"
    assert payload["params"]["Bids"][0]["ContextBid"] == 5000


@responses.activate
def test_audience_targets_suspend(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AT_URL,
        json={"result": {"SuspendResults": [{"Id": 5}]}},
        status=200,
    )
    res = client.audience_targets.suspend([5])
    assert res[0]["Id"] == 5
    assert _body_of(responses.calls[0])["method"] == "suspend"


@responses.activate
def test_audience_targets_delete(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AT_URL,
        json={"result": {"DeleteResults": [{"Id": 5}]}},
        status=200,
    )
    res = client.audience_targets.delete([5], confirm=True)
    assert res[0]["Id"] == 5


def test_audience_targets_delete_requires_confirm(
    client: YandexDirectClient,
) -> None:
    with pytest.raises(ValidationError):
        client.audience_targets.delete([5])
    assert len(responses.calls) == 0


# =============== retargeting_conditions ===============
@responses.activate
def test_retargeting_conditions_list(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AT_URL,
        json={
            "result": {
                "AudienceTargets": [
                    {
                        "Id": 1,
                        "AdGroupId": 100,
                        "RetargetingListId": 900,
                        "State": "ON",
                    }
                ]
            }
        },
        status=200,
    )
    items = client.retargeting_conditions.list(retargeting_list_ids=[900])
    assert items[0].retargeting_list_id == 900
    payload = _body_of(responses.calls[0])
    assert payload["params"]["SelectionCriteria"]["RetargetingListIds"] == [900]


@responses.activate
def test_retargeting_conditions_create(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AT_URL,
        json={"result": {"AddResults": [{"Id": 7}]}},
        status=200,
    )
    res = client.retargeting_conditions.create(
        [
            RetargetingCondition(
                id=0, ad_group_id=100, retargeting_list_id=900
            )
        ]
    )
    assert res[0]["Id"] == 7
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "add"
    sent = payload["params"]["AudienceTargets"][0]
    assert sent["RetargetingListId"] == 900


@responses.activate
def test_retargeting_conditions_delete(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AT_URL,
        json={"result": {"DeleteResults": [{"Id": 7}]}},
        status=200,
    )
    res = client.retargeting_conditions.delete([7], confirm=True)
    assert res[0]["Id"] == 7


def test_retargeting_conditions_delete_requires_confirm(
    client: YandexDirectClient,
) -> None:
    with pytest.raises(ValidationError):
        client.retargeting_conditions.delete([7])
    assert len(responses.calls) == 0


# =============== ad_extensions: sitelinks ===============
@responses.activate
def test_sitelinks_list(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        SL_URL,
        json={
            "result": {
                "SitelinksSets": [
                    {
                        "Id": 1,
                        "Sitelinks": [
                            {"Title": "T1", "Href": "https://a.example"},
                            {"Title": "T2", "Href": "https://b.example"},
                        ],
                    }
                ]
            }
        },
        status=200,
    )
    items = client.ad_extensions.list_sitelinks()
    assert items[0].id == 1
    assert len(items[0].sitelinks) == 2
    assert items[0].sitelinks[0].title == "T1"


@responses.activate
def test_sitelinks_create_typed(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        SL_URL,
        json={"result": {"AddResults": [{"Id": 20}]}},
        status=200,
    )
    res = client.ad_extensions.create_sitelinks(
        [
            SitelinksSet(
                id=0,
                sitelinks=[
                    Sitelink(title="T1", href="https://a.example"),
                    Sitelink(title="T2", href="https://b.example"),
                ],
            )
        ]
    )
    assert res[0]["Id"] == 20
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "add"
    sent = payload["params"]["SitelinksSets"][0]
    assert len(sent["Sitelinks"]) == 2
    assert sent["Sitelinks"][0]["Title"] == "T1"


@responses.activate
def test_sitelinks_delete(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        SL_URL,
        json={"result": {"DeleteResults": [{"Id": 20}]}},
        status=200,
    )
    res = client.ad_extensions.delete_sitelinks([20], confirm=True)
    assert res[0]["Id"] == 20


def test_sitelinks_delete_requires_confirm(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.ad_extensions.delete_sitelinks([20])
    assert len(responses.calls) == 0


# =============== ad_extensions: callouts ===============
@responses.activate
def test_callouts_list(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AE_URL,
        json={
            "result": {
                "AdExtensions": [
                    {
                        "Id": 1,
                        "Type": "CALLOUT",
                        "Callout": {"CalloutText": "Быстрая доставка"},
                        "Associated": "NO",
                        "Status": "ACCEPTED",
                    }
                ]
            }
        },
        status=200,
    )
    items = client.ad_extensions.list_callouts()
    assert items[0].callout_text == "Быстрая доставка"
    assert items[0].type == "CALLOUT"


@responses.activate
def test_callouts_create_typed(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AE_URL,
        json={"result": {"AddResults": [{"Id": 30}]}},
        status=200,
    )
    res = client.ad_extensions.create_callouts(
        [Callout(id=0, callout_text="Гарантия")]
    )
    assert res[0]["Id"] == 30
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "add"
    sent = payload["params"]["AdExtensions"][0]
    assert sent["Callout"]["CalloutText"] == "Гарантия"


@responses.activate
def test_callouts_delete(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AE_URL,
        json={"result": {"DeleteResults": [{"Id": 30}]}},
        status=200,
    )
    res = client.ad_extensions.delete_callouts([30], confirm=True)
    assert res[0]["Id"] == 30


def test_callouts_delete_requires_confirm(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.ad_extensions.delete_callouts([30])
    assert len(responses.calls) == 0


@responses.activate
def test_callouts_create_item_error(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        AE_URL,
        json={
            "result": {
                "AddResults": [{"Errors": [{"Code": 5, "Message": "dup"}]}]
            }
        },
        status=200,
    )
    with pytest.raises(ApiError):
        client.ad_extensions.create_callouts([Callout(id=0, callout_text="x")])


# =============== readonly guards ===============
def test_readonly_blocks_track_b(client: YandexDirectClient) -> None:
    ro = YandexDirectClient(
        token="t", client_login="L", readonly=True, rate_limit_rps=1000.0
    )
    try:
        with pytest.raises(ValidationError):
            ro.negative_keywords.create([])
        with pytest.raises(ValidationError):
            ro.negative_keywords.delete([1], confirm=True)
        with pytest.raises(ValidationError):
            ro.audience_targets.create([])
        with pytest.raises(ValidationError):
            ro.audience_targets.set_bids([])
        with pytest.raises(ValidationError):
            ro.retargeting_conditions.create([])
        with pytest.raises(ValidationError):
            ro.ad_extensions.create_sitelinks([])
        with pytest.raises(ValidationError):
            ro.ad_extensions.delete_callouts([1], confirm=True)
    finally:
        ro.close()
