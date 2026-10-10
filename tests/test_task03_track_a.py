"""Unit-тесты трека A: ad_groups CRUD, campaigns/ads управление состоянием."""
from __future__ import annotations

import json

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.exceptions import ApiError, ValidationError
from yandex_direct_api_client.models import AdGroup

ADGROUPS_URL = "https://api.direct.yandex.com/json/v5/adgroups/"
CAMPAIGNS_URL = "https://api.direct.yandex.com/json/v5/campaigns/"
ADS_URL = "https://api.direct.yandex.com/json/v5/ads/"


def _body_of(call: responses.Call) -> dict:
    body = call.request.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body)  # type: ignore[arg-type]


# ---------- AdGroup.to_new_payload / to_update_payload ----------
def test_adgroup_to_new_payload_items_wrapper() -> None:
    g = AdGroup(
        id=0,
        campaign_id=10,
        name="group",
        region_ids=[0],
        negative_keywords_shared_set_ids=[1, 2],
    )
    body = g.to_new_payload()
    assert body["CampaignId"] == 10
    assert body["Name"] == "group"
    assert body["RegionIds"] == [0]
    # ArrayOfLong приходит/уходит через обёртку {Items: [...]}
    assert body["NegativeKeywordSharedSetIds"] == {"Items": [1, 2]}
    assert "Id" not in body


def test_adgroup_to_update_payload_has_id() -> None:
    g = AdGroup(id=55, campaign_id=10, name="g", region_ids=[0])
    body = g.to_update_payload()
    assert body["Id"] == 55
    assert body["RegionIds"] == [0]
    # adgroups/update не принимает CampaignId (иначе ошибка 8000)
    assert "CampaignId" not in body


def test_adgroup_from_dict_unwraps_items() -> None:
    g = AdGroup.from_dict(
        {
            "Id": 7,
            "CampaignId": 10,
            "Name": "g",
            "RegionIds": [0, -219],
            "NegativeKeywordSharedSetIds": {"Items": [3, 4]},
        }
    )
    assert g.region_ids == [0, -219]
    assert g.negative_keywords_shared_set_ids == [3, 4]


# ---------- ad_groups.create ----------
@responses.activate
def test_ad_groups_create_typed(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADGROUPS_URL,
        json={"result": {"AddResults": [{"Id": 100}]}},
        status=200,
    )
    res = client.ad_groups.create(
        [AdGroup(id=0, campaign_id=10, name="g", region_ids=[225])]
    )
    assert res[0]["Id"] == 100
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "add"
    sent = payload["params"]["AdGroups"][0]
    assert sent["CampaignId"] == 10
    assert sent["Name"] == "g"
    assert sent["RegionIds"] == [225]


@responses.activate
def test_ad_groups_create_raw_dict(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADGROUPS_URL,
        json={"result": {"AddResults": [{"Id": 101}]}},
        status=200,
    )
    res = client.ad_groups.create(
        [{"CampaignId": 1, "Name": "x", "RegionIds": [225]}]
    )
    assert res[0]["Id"] == 101


def test_ad_groups_create_empty(client: YandexDirectClient) -> None:
    assert client.ad_groups.create([]) == []


@responses.activate
def test_ad_groups_create_item_error(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADGROUPS_URL,
        json={
            "result": {
                "AddResults": [
                    {"Errors": [{"Code": 5, "Message": "bad campaign"}]}
                ]
            }
        },
        status=200,
    )
    with pytest.raises(ApiError):
        client.ad_groups.create(
            [AdGroup(id=0, campaign_id=10, name="g", region_ids=[225])]
        )


# ---------- ad_groups.update ----------
@responses.activate
def test_ad_groups_update_typed(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADGROUPS_URL,
        json={"result": {"UpdateResults": [{"Id": 100}]}},
        status=200,
    )
    res = client.ad_groups.update(
        [AdGroup(id=100, campaign_id=10, name="renamed", region_ids=[225])]
    )
    assert res[0]["Id"] == 100
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "update"
    sent = payload["params"]["AdGroups"][0]
    assert sent["Id"] == 100
    assert sent["Name"] == "renamed"
    assert "CampaignId" not in sent  # live-баг: update не принимает CampaignId


# ---------- ad_groups.delete ----------
@responses.activate
def test_ad_groups_delete(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADGROUPS_URL,
        json={"result": {"DeleteResults": [{"Id": 1}, {"Id": 2}]}},
        status=200,
    )
    res = client.ad_groups.delete([1, 2], confirm=True)
    assert len(res) == 2
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "delete"
    assert payload["params"]["SelectionCriteria"]["Ids"] == [1, 2]


def test_ad_groups_delete_requires_confirm(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.ad_groups.delete([1])
    assert len(responses.calls) == 0


# ---------- ad_groups.list / get (регресс живого теста) ----------
@responses.activate
def test_ad_groups_list_fieldnames_have_no_state(client: YandexDirectClient) -> None:
    """У группы НЕТ поля State — его запрос давал 8000 на живом API."""
    responses.add(
        responses.POST,
        ADGROUPS_URL,
        json={
            "result": {
                "AdGroups": [
                    {
                        "Id": 1,
                        "Name": "g1",
                        "CampaignId": 10,
                        "Status": "ACCEPTED",
                        "Type": "TEXT_AD_GROUP",
                        "RegionIds": [225],
                    }
                ]
            }
        },
        status=200,
    )
    groups = client.ad_groups.list(campaign_ids=[10])
    assert groups[0].id == 1
    assert groups[0].region_ids == [225]
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "get"
    fields = payload["params"]["FieldNames"]
    assert "State" not in fields
    assert "RegionIds" in fields


@responses.activate
def test_ad_groups_list_criteria_valid(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST, ADGROUPS_URL, json={"result": {"AdGroups": []}}, status=200
    )
    client.ad_groups.list(
        campaign_ids=[10], statuses=["DRAFT"], serving_statuses=["ELIGIBLE"]
    )
    payload = _body_of(responses.calls[0])
    crit = payload["params"]["SelectionCriteria"]
    assert crit["CampaignIds"] == [10]
    assert crit["Statuses"] == ["DRAFT"]
    assert crit["ServingStatuses"] == ["ELIGIBLE"]
    assert "States" not in crit  # у adgroups нет SelectionCriteria.States


@responses.activate
def test_ad_groups_get_by_ids(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADGROUPS_URL,
        json={
            "result": {
                "AdGroups": [
                    {"Id": 5, "Name": "g", "CampaignId": 10, "Status": "DRAFT"}
                ]
            }
        },
        status=200,
    )
    groups = client.ad_groups.get([5])
    assert groups[0].id == 5
    payload = _body_of(responses.calls[0])
    assert payload["params"]["SelectionCriteria"]["Ids"] == [5]
    assert "State" not in payload["params"]["FieldNames"]


def test_ad_groups_list_requires_campaign_ids(client: YandexDirectClient) -> None:
    """adgroups/get требует CampaignIds/Ids — list() без фильтра отклоняется."""
    with pytest.raises(ValidationError):
        client.ad_groups.list()
    assert len(responses.calls) == 0


# ---------- campaigns state actions ----------
@responses.activate
def test_campaigns_suspend(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={"result": {"SuspendResults": [{"Id": 1}]}},
        status=200,
    )
    res = client.campaigns.suspend([1])
    assert res[0]["Id"] == 1
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "suspend"
    assert payload["params"]["SelectionCriteria"]["Ids"] == [1]


@responses.activate
def test_campaigns_resume(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={"result": {"ResumeResults": [{"Id": 1}]}},
        status=200,
    )
    res = client.campaigns.resume([1])
    assert res[0]["Id"] == 1
    assert _body_of(responses.calls[0])["method"] == "resume"


@responses.activate
def test_campaigns_archive(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={"result": {"ArchiveResults": [{"Id": 1}]}},
        status=200,
    )
    res = client.campaigns.archive([1], confirm=True)
    assert res[0]["Id"] == 1
    assert _body_of(responses.calls[0])["method"] == "archive"


def test_campaigns_archive_requires_confirm(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.campaigns.archive([1])
    assert len(responses.calls) == 0


@responses.activate
def test_campaigns_unarchive(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={"result": {"UnarchiveResults": [{"Id": 1}]}},
        status=200,
    )
    res = client.campaigns.unarchive([1])
    assert res[0]["Id"] == 1
    assert _body_of(responses.calls[0])["method"] == "unarchive"


@responses.activate
def test_campaigns_suspend_item_error(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={
            "result": {
                "SuspendResults": [
                    {"Id": 1, "Errors": [{"Code": 9, "Message": "archived"}]}
                ]
            }
        },
        status=200,
    )
    with pytest.raises(ApiError):
        client.campaigns.suspend([1])


# ---------- ads state actions ----------
@responses.activate
def test_ads_suspend(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"SuspendResults": [{"Id": 5}]}},
        status=200,
    )
    res = client.ads.suspend([5])
    assert res[0]["Id"] == 5
    assert _body_of(responses.calls[0])["method"] == "suspend"


@responses.activate
def test_ads_resume(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"ResumeResults": [{"Id": 5}]}},
        status=200,
    )
    res = client.ads.resume([5])
    assert res[0]["Id"] == 5
    assert _body_of(responses.calls[0])["method"] == "resume"


@responses.activate
def test_ads_archive(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"ArchiveResults": [{"Id": 5}]}},
        status=200,
    )
    res = client.ads.archive([5], confirm=True)
    assert res[0]["Id"] == 5
    assert _body_of(responses.calls[0])["method"] == "archive"


def test_ads_archive_requires_confirm(client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        client.ads.archive([5])
    assert len(responses.calls) == 0


@responses.activate
def test_ads_unarchive(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"UnarchiveResults": [{"Id": 5}]}},
        status=200,
    )
    res = client.ads.unarchive([5])
    assert res[0]["Id"] == 5
    assert _body_of(responses.calls[0])["method"] == "unarchive"


@responses.activate
def test_ads_moderate(client: YandexDirectClient) -> None:
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"ModerateResults": [{"Id": 5}, {"Id": 6}]}},
        status=200,
    )
    res = client.ads.moderate([5, 6])
    assert len(res) == 2
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "moderate"
    assert payload["params"]["SelectionCriteria"]["Ids"] == [5, 6]


# ---------- readonly guards ----------
def test_readonly_blocks_track_a(client: YandexDirectClient) -> None:
    ro = YandexDirectClient(
        token="t", client_login="L", readonly=True, rate_limit_rps=1000.0
    )
    try:
        with pytest.raises(ValidationError):
            ro.ad_groups.create([])
        with pytest.raises(ValidationError):
            ro.ad_groups.update([])
        with pytest.raises(ValidationError):
            ro.ad_groups.delete([1], confirm=True)
        with pytest.raises(ValidationError):
            ro.campaigns.suspend([1])
        with pytest.raises(ValidationError):
            ro.campaigns.archive([1], confirm=True)
        with pytest.raises(ValidationError):
            ro.ads.moderate([1])
        with pytest.raises(ValidationError):
            ro.ads.archive([1], confirm=True)
    finally:
        ro.close()
