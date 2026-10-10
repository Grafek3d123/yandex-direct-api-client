"""Тесты этапа 0 STAGE_05 (tasks/task04.md): транспорт, ошибки, batch, логи, валидация.

Идентификаторы критериев приёмки:
- F-0.1 — версии API v5/v501 и необязательный `Client-Login`;
- F-0.2 — централизованные лимиты и авто-чанкинг;
- F-0.3 — частичные результаты batch-операций;
- F-0.4 — классификация ошибок и `request_id`;
- F-0.5 — structured logging без утечки секретов;
- F-0.6 — redactor токенов;
- F-0.7 — pre-send validation.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

import pytest
import responses

from yandex_direct_api_client import AdText, YandexDirectClient
from yandex_direct_api_client.exceptions import (
    KIND_AUTH,
    KIND_FATAL,
    KIND_RATE_LIMIT,
    KIND_RETRYABLE,
    KIND_VALIDATION,
    ApiError,
    ValidationError,
    classify_error,
)
from yandex_direct_api_client.limits import CAMPAIGNS_ADD_MAX, MUTATE_MAX
from yandex_direct_api_client.logs import MASK, redact, redact_text
from yandex_direct_api_client.models.batch import BatchResult
from yandex_direct_api_client.models.targeting import DemographicsTarget
from yandex_direct_api_client.validation import Validator

V5_CAMPAIGNS = "https://api.direct.yandex.com/json/v5/campaigns/"
V501_CAMPAIGNS = "https://api.direct.yandex.com/json/v501/campaigns/"
V5_ADGROUPS = "https://api.direct.yandex.com/json/v5/adgroups/"
V5_ADS = "https://api.direct.yandex.com/json/v5/ads/"

_REAL_TOKEN = "t1.9AAAAAAAABBBBBBBBCCCCCCCCDDDDDDDD"


def _body_of(call: Any) -> Dict[str, Any]:
    """Разобрать JSON-тело исходящего запроса."""
    return json.loads(call.request.body)


def _client(**kwargs: Any) -> YandexDirectClient:
    """Клиент с тестовыми настройками (env очищается фикстурой конусного теста)."""
    params: Dict[str, Any] = {
        "token": "test_token",
        "rate_limit_rps": 1000.0,
        "max_retries": 1,
    }
    params.update(kwargs)
    return YandexDirectClient(**params)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убрать влияние реального окружения на тесты."""
    for var in (
        "YANDEX_DIRECT_TOKEN",
        "YANDEX_DIRECT_CLIENT_LOGIN",
        "YANDEX_DIRECT_API_URL",
        "YANDEX_DIRECT_API_VERSION",
        "YANDEX_DIRECT_READONLY",
        "YANDEX_DIRECT_VALIDATE",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------- G16: readonly блокирует все мутации ----------------


_MUTATIONS = [
    ("campaigns.create", lambda c: c.campaigns.create({"Name": "n"})),
    ("campaigns.create_many", lambda c: c.campaigns.create_many([{"Name": "n"}])),
    (
        "campaigns.update",
        lambda c: c.campaigns.update({"Id": 1, "Name": "n"}),
    ),
    ("campaigns.delete", lambda c: c.campaigns.delete([1], confirm=True)),
    ("campaigns.suspend", lambda c: c.campaigns.suspend([1])),
    ("campaigns.resume", lambda c: c.campaigns.resume([1])),
    ("campaigns.archive", lambda c: c.campaigns.archive([1], confirm=True)),
    ("campaigns.unarchive", lambda c: c.campaigns.unarchive([1])),
    ("ads.create", lambda c: c.ads.create([{"AdGroupId": 1}])),
    ("ads.create_with_payload", lambda c: c.ads.create_with_payload(1, AdText(title="t", text="b"), ad_group_id=1)),
    (
        "ads.update",
        lambda c: c.ads.update([{"Id": 1, "TextAd": {"Title": "t", "Text": "b"}}], confirm=True),
    ),
    ("ads.update_text", lambda c: c.ads.update_text(1, "t", "b")),
    ("ads.delete", lambda c: c.ads.delete([1], confirm=True)),
    ("ads.suspend", lambda c: c.ads.suspend([1])),
    ("ads.resume", lambda c: c.ads.resume([1])),
    ("ads.archive", lambda c: c.ads.archive([1], confirm=True)),
    ("ads.unarchive", lambda c: c.ads.unarchive([1])),
    ("ads.moderate", lambda c: c.ads.moderate([1])),
    (
        "ad_groups.create",
        lambda c: c.ad_groups.create(
            [{"CampaignId": 1, "Name": "g", "RegionIds": [225]}]
        ),
    ),
    ("ad_groups.update", lambda c: c.ad_groups.update([{"Id": 1, "Name": "g"}])),
    ("ad_groups.delete", lambda c: c.ad_groups.delete([1], confirm=True)),
    (
        "ad_group_items.add",
        lambda c: c.ad_group_items.add([{"AdGroupId": 1, "Keyword": "k"}]),
    ),
    (
        "ad_group_items.set_bids",
        lambda c: c.ad_group_items.set_bids([{"Id": 1, "Bids": {"Bid": 10}}], confirm=True),
    ),
    ("ad_group_items.set_bid", lambda c: c.ad_group_items.set_bid(1, 10.0)),
    ("ad_group_items.delete", lambda c: c.ad_group_items.delete([1], confirm=True)),
    (
        "audience_targets.create",
        lambda c: c.audience_targets.create([{"AdGroupId": 1, "InterestId": 1}]),
    ),
    ("audience_targets.delete", lambda c: c.audience_targets.delete([1], confirm=True)),
    ("audience_targets.suspend", lambda c: c.audience_targets.suspend([1])),
    ("audience_targets.resume", lambda c: c.audience_targets.resume([1])),
    (
        "audience_targets.set_bids",
        lambda c: c.audience_targets.set_bids([{"Id": 1, "ContextBid": 10}]),
    ),
    (
        "retargeting_conditions.create",
        lambda c: c.retargeting_conditions.create(
            [{"AdGroupId": 1, "RetargetingListId": 1}]
        ),
    ),
    (
        "retargeting_conditions.delete",
        lambda c: c.retargeting_conditions.delete([1], confirm=True),
    ),
    (
        "retargeting_adjustments.add",
        lambda c: c.retargeting_adjustments.add(
            [{"CampaignId": 1, "SegmentId": 1, "BidDelta": 10}]
        ),
    ),
    (
        "retargeting_adjustments.update",
        lambda c: c.retargeting_adjustments.update([{"Id": 1}], confirm=True),
    ),
    (
        "retargeting_adjustments.delete",
        lambda c: c.retargeting_adjustments.delete([1], confirm=True),
    ),
    (
        "negative_keywords.create",
        lambda c: c.negative_keywords.create([{"Name": "n", "NegativeKeywords": ["k"]}]),
    ),
    (
        "negative_keywords.update",
        lambda c: c.negative_keywords.update([{"Id": 1, "Name": "n"}]),
    ),
    (
        "negative_keywords.delete",
        lambda c: c.negative_keywords.delete([1], confirm=True),
    ),
    (
        "ad_extensions.create_sitelinks",
        lambda c: c.ad_extensions.create_sitelinks([{"Sitelinks": []}]),
    ),
    (
        "ad_extensions.delete_sitelinks",
        lambda c: c.ad_extensions.delete_sitelinks([1], confirm=True),
    ),
    (
        "ad_extensions.create_callouts",
        lambda c: c.ad_extensions.create_callouts([{"Callout": {"CalloutText": "t"}}]),
    ),
    (
        "ad_extensions.delete_callouts",
        lambda c: c.ad_extensions.delete_callouts([1], confirm=True),
    ),
    # Слой 3: денежные операции.
    (
        "campaigns.set_weekly_budget",
        lambda c: c.campaigns.set_weekly_budget([1], 100, confirm=True),
    ),
    (
        "campaigns.set_daily_budget",
        lambda c: c.campaigns.set_daily_budget([1], 100, confirm=True),
    ),
    (
        "campaigns.set_bid_strategy",
        lambda c: c.campaigns.set_bid_strategy(
            [1], {"BiddingStrategyType": "MANUAL_CPC"}, confirm=True
        ),
    ),
    # Слой 4: сегменты и условия нацеливания.
    (
        "retargeting_lists.create",
        lambda c: c.retargeting_lists.create(
            [
                {
                    "Name": "s",
                    "Type": "AUDIENCE",
                    "Rules": [{"Operator": "ANY", "Arguments": [{"ExternalId": 1}]}],
                }
            ]
        ),
    ),
    (
        "retargeting_lists.update",
        lambda c: c.retargeting_lists.update(
            [
                {
                    "Id": 1,
                    "Name": "s",
                    "Type": "AUDIENCE",
                    "Rules": [{"Operator": "ANY", "Arguments": [{"ExternalId": 1}]}],
                }
            ],
            confirm=True,
        ),
    ),
    (
        "retargeting_lists.delete",
        lambda c: c.retargeting_lists.delete([1], confirm=True),
    ),
    (
        "targeting.create_audience_target",
        lambda c: c.targeting.create_audience_target(
            1, DemographicsTarget(ad_group_id=1, segment_ids=[1])
        ),
    ),
]


@pytest.mark.parametrize(("name", "call"), _MUTATIONS, ids=[n for n, _ in _MUTATIONS])
@responses.activate
def test_g16_readonly_blocks_every_mutation(name: str, call: Any) -> None:
    """`readonly=True` блокирует все мутации до похода в сеть (G16)."""
    with _client(client_login="TESTLOGIN", readonly=True) as c:
        with pytest.raises(ValidationError):
            call(c)
    assert len(responses.calls) == 0, f"{name} не должен слать запрос в readonly"


# ---------------- retry-поведение (F-0.4) ----------------


@responses.activate
def test_f04_401_is_not_retried() -> None:
    from yandex_direct_api_client.exceptions import AuthError

    responses.add(responses.POST, V5_CAMPAIGNS, json={"error": "unauthorized"}, status=401)
    with _client(client_login="TESTLOGIN", max_retries=3) as c:
        with pytest.raises(AuthError):
            c.campaigns.list()
    assert len(responses.calls) == 1, "401 не должен повторяться"


@responses.activate
def test_f04_429_exhausts_retries_and_reports_retry_after() -> None:
    from yandex_direct_api_client.exceptions import RateLimitError

    for _ in range(3):
        responses.add(
            responses.POST,
            V5_CAMPAIGNS,
            json={"error": "too many"},
            status=429,
            headers={"Retry-After": "0"},
        )
    with _client(client_login="TESTLOGIN", max_retries=2) as c:
        with pytest.raises(RateLimitError) as exc:
            c.campaigns.list()
    assert len(responses.calls) == 3, "исходный запрос + 2 повтора"
    assert exc.value.retry_after == 0.0
    assert exc.value.is_retryable


# ---------------- F-0.1: версии API и Client-Login ----------------


@responses.activate
def test_f01_default_version_is_v5() -> None:
    responses.add(responses.POST, V5_CAMPAIGNS, json={"result": {"Campaigns": []}})
    with _client(client_login="TESTLOGIN") as c:
        c.campaigns.list()
    assert responses.calls[0].request.url.startswith(V5_CAMPAIGNS)


@responses.activate
def test_f01_api_version_v501_switches_url() -> None:
    responses.add(responses.POST, V501_CAMPAIGNS, json={"result": {"Campaigns": []}})
    with _client(client_login="TESTLOGIN", api_version="v501") as c:
        c.campaigns.list()
    assert responses.calls[0].request.url.startswith(V501_CAMPAIGNS)


@responses.activate
def test_f01_api_url_with_version_in_url_is_normalized() -> None:
    """`api_url` с хвостом `/json/v5` не должен давать `.../v5/v5/...`."""
    responses.add(responses.POST, V501_CAMPAIGNS, json={"result": {"Campaigns": []}})
    with _client(
        client_login="TESTLOGIN",
        api_url="https://api.direct.yandex.com/json/v5",
        api_version="v501",
    ) as c:
        c.campaigns.list()
    assert responses.calls[0].request.url.startswith(V501_CAMPAIGNS)


@responses.activate
def test_f01_client_login_header_sent_when_set() -> None:
    responses.add(responses.POST, V5_CAMPAIGNS, json={"result": {"Campaigns": []}})
    with _client(client_login="AGENCYLOGIN") as c:
        c.campaigns.list()
    assert responses.calls[0].request.headers["Client-Login"] == "AGENCYLOGIN"


@responses.activate
def test_f01_client_login_header_absent_when_not_set() -> None:
    """Прямому рекламодателю заголовок `Client-Login` не нужен (F-0.1)."""
    responses.add(responses.POST, V5_CAMPAIGNS, json={"result": {"Campaigns": []}})
    with _client() as c:
        c.campaigns.list()
    assert "Client-Login" not in responses.calls[0].request.headers


def test_f01_client_login_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_CLIENT_LOGIN", "ENVLOGIN")
    with _client() as c:
        assert c.client_login == "ENVLOGIN"


def test_f01_api_version_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_API_VERSION", "v501")
    with _client() as c:
        assert c.api_version == "v501"


# ---------------- F-0.2: лимиты и чанкинг ----------------


@responses.activate
def test_f02_campaigns_add_chunked_by_ten() -> None:
    """`campaigns/add` — максимум 10 кампаний за вызов."""
    for _ in range(3):
        responses.add(
            responses.POST,
            V5_CAMPAIGNS,
            json={"result": {"AddResults": [{"Id": 1}, {"Id": 2}]}},
        )
    bodies = [{"Name": f"c{i}"} for i in range(25)]
    with _client(client_login="TESTLOGIN") as c:
        res = c.campaigns.create_many(bodies)
    assert len(res) == 6
    sent = [len(_body_of(call)["params"]["Campaigns"]) for call in responses.calls]
    assert sent == [10, 10, 5]
    for size in sent:
        assert size <= CAMPAIGNS_ADD_MAX


@responses.activate
def test_f02_ads_add_chunked_by_200() -> None:
    for _ in range(2):
        responses.add(
            responses.POST,
            V5_ADS,
            json={"result": {"AddResults": [{"Id": 1}]}},
        )
    bodies = [{"AdGroupId": 10} for _ in range(250)]
    with _client(client_login="TESTLOGIN") as c:
        c.ads.create(bodies)
    sent = [len(_body_of(call)["params"]["Ads"]) for call in responses.calls]
    assert sent == [200, 50]
    assert max(sent) <= MUTATE_MAX


@responses.activate
def test_f02_ads_get_chunked_by_ads_get_max() -> None:
    for _ in range(2):
        responses.add(responses.POST, V5_ADS, json={"result": {"Ads": []}})
    with _client(client_login="TESTLOGIN") as c:
        c.ads.get(list(range(1, 10002)))
    sent = [len(_body_of(call)["params"]["SelectionCriteria"]["Ids"]) for call in responses.calls]
    assert sent == [10000, 1]


@responses.activate
def test_f02_criteria_add_chunked_by_200() -> None:
    for _ in range(2):
        responses.add(
            responses.POST,
            "https://api.direct.yandex.com/json/v5/criteria/",
            json={"result": {"AddResults": [{"Id": 1}]}},
        )
    with _client(client_login="TESTLOGIN") as c:
        c.ad_group_items.add([{"AdGroupId": 10, "Keyword": f"k{i}"} for i in range(201)])
    sent = [
        len(_body_of(call)["params"]["AdGroupItems"]) for call in responses.calls
    ]
    assert sent == [200, 1]


# ---------------- F-0.3: частичные результаты batch ----------------


@responses.activate
def test_f03_collect_keeps_successes_and_failures() -> None:
    responses.add(
        responses.POST,
        V5_ADGROUPS,
        json={
            "result": {
                "AddResults": [
                    {"Id": 1},
                    {"Errors": [{"Code": 5, "Message": "bad campaign"}]},
                    {"Id": 3},
                ]
            }
        },
    )
    bodies = [
        {"CampaignId": 10, "Name": "ok-1", "RegionIds": [225]},
        {"CampaignId": 0, "Name": "bad", "RegionIds": [225]},
        {"CampaignId": 10, "Name": "ok-2", "RegionIds": [225]},
    ]
    with _client(client_login="TESTLOGIN", validate=False) as c:
        result = c.ad_groups.create(bodies, on_item_error="collect")
    assert isinstance(result, BatchResult)
    assert [item["Id"] for item in result.succeeded] == [1, 3]
    assert len(result.failed) == 1
    failure = result.failed[0]
    assert failure.code == 5
    assert failure.message == "bad campaign"


@responses.activate
def test_f03_raise_is_default_behaviour() -> None:
    responses.add(
        responses.POST,
        V5_ADGROUPS,
        json={"result": {"AddResults": [{"Errors": [{"Code": 5, "Message": "nope"}]}]}},
    )
    with _client(client_login="TESTLOGIN", validate=False) as c:
        with pytest.raises(ApiError) as exc:
            c.ad_groups.create([{"CampaignId": 10, "Name": "g", "RegionIds": [225]}])
    assert "nope" in str(exc.value)


@responses.activate
def test_f03_failure_carries_request_id() -> None:
    responses.add(
        responses.POST,
        V5_ADGROUPS,
        json={"result": {"AddResults": [{"Errors": [{"Code": 5, "Message": "nope"}]}]}},
        headers={"X-Request-Id": "req-42"},
    )
    with _client(client_login="TESTLOGIN", validate=False) as c:
        result = c.ad_groups.create(
            [{"CampaignId": 10, "Name": "g", "RegionIds": [225]}],
            on_item_error="collect",
        )
    assert isinstance(result, BatchResult)
    assert result.failed[0].request_id == "req-42"


@responses.activate
def test_f03_collect_across_chunks() -> None:
    """Частичные результаты собираются по всем чанкам запроса."""
    for _ in range(2):
        responses.add(
            responses.POST,
            V5_ADS,
            json={"result": {"AddResults": [{"Id": 1}]}},
        )
    with _client(client_login="TESTLOGIN") as c:
        result = c.ads.create(
            [{"AdGroupId": 10} for _ in range(201)], on_item_error="collect"
        )
    assert isinstance(result, BatchResult)
    assert len(result.succeeded) == 2


@responses.activate
def test_f03_empty_input_returns_empty_batch_result() -> None:
    with _client(client_login="TESTLOGIN") as c:
        result = c.ads.create([], on_item_error="collect")
    assert isinstance(result, BatchResult)
    assert result.succeeded == []
    assert result.failed == []
    assert len(responses.calls) == 0


# ---------------- F-0.4: классификация ошибок и request_id ----------------


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, KIND_AUTH),
        (403, KIND_AUTH),
        (429, KIND_RATE_LIMIT),
        (400, KIND_VALIDATION),
        (404, KIND_FATAL),
        (500, KIND_RETRYABLE),
        (503, KIND_RETRYABLE),
        (None, "other"),
    ],
)
def test_f04_classify_error(status: int, kind: str) -> None:
    assert classify_error(status) == kind


@responses.activate
def test_f04_api_error_keeps_request_id_and_kind() -> None:
    responses.add(
        responses.POST,
        V5_CAMPAIGNS,
        json={"error": {"error_code": 8000, "error_string": "wrong param"}},
        status=400,
        headers={"X-Request-Id": "req-777"},
    )
    with _client(client_login="TESTLOGIN") as c:
        with pytest.raises(ApiError) as exc:
            c.campaigns.list()
    err = exc.value
    assert err.request_id == "req-777"
    assert err.error_code == "8000"
    assert err.is_validation
    assert "req-777" in str(err)


def test_f04_error_helpers_reflect_kind() -> None:
    err = ApiError("x", status_code=429)
    assert err.is_retryable
    assert ApiError("x", status_code=403).is_auth
    assert ApiError("x", status_code=404).is_fatal


@responses.activate
def test_f04_response_body_errors_are_typed() -> None:
    responses.add(
        responses.POST,
        V5_CAMPAIGNS,
        json={"error": {"error_code": 404, "error_string": "not found"}},
        status=200,
    )
    with _client(client_login="TESTLOGIN") as c:
        with pytest.raises(ApiError) as exc:
            c.campaigns.list()
    assert exc.value.error_code == "404"


# ---------------- F-0.5: structured logging ----------------


@responses.activate
def test_f05_mutation_logged_with_structured_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    responses.add(
        responses.POST,
        V5_CAMPAIGNS,
        json={"result": {"AddResults": [{"Id": 5}]}},
        headers={"X-Request-Id": "req-log-1"},
    )
    with caplog.at_level(logging.INFO, logger="yandex_direct_api_client"):
        with _client(client_login="TESTLOGIN") as c:
            c.campaigns.create({"Name": "logged"})
    records = [r for r in caplog.records if r.name.startswith("yandex_direct_api_client")]
    assert records, "ожидается запись логгера клиента"
    record = records[-1]
    assert record.service == "campaigns"  # type: ignore[attr-defined]
    assert record.method == "add"  # type: ignore[attr-defined]
    assert record.api_version == "json/v5"  # type: ignore[attr-defined]
    assert record.request_id == "req-log-1"  # type: ignore[attr-defined]
    assert record.status_code == 200  # type: ignore[attr-defined]
    assert isinstance(record.duration_ms, int)  # type: ignore[attr-defined]


@responses.activate
def test_f05_get_requests_logged_at_debug_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    responses.add(responses.POST, V5_CAMPAIGNS, json={"result": {"Campaigns": []}})
    with caplog.at_level(logging.INFO, logger="yandex_direct_api_client"):
        with _client(client_login="TESTLOGIN") as c:
            c.campaigns.list()
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "mutation" not in messages


def test_f05_root_logger_has_null_handler() -> None:
    root = logging.getLogger("yandex_direct_api_client")
    assert any(isinstance(h, logging.NullHandler) for h in root.handlers)


# ---------------- F-0.6: redactor ----------------


def test_f06_redact_masks_sensitive_keys() -> None:
    data = {"Authorization": "Bearer abc", "refresh_token": _REAL_TOKEN, "name": "ok"}
    masked = redact(data)
    assert masked["Authorization"] == MASK
    assert masked["refresh_token"] == MASK
    assert masked["name"] == "ok"


def test_f06_redact_masks_token_like_strings_regardless_of_key() -> None:
    assert redact({"note": f"вот токен {_REAL_TOKEN} в тексте"})["note"] == (
        f"вот токен {MASK} в тексте"
    )


def test_f06_redact_text_masks_bearer() -> None:
    assert redact_text("Authorization: Bearer abcdef123456") == (
        f"Authorization: Bearer {MASK}"
    )


def test_f06_exception_text_and_body_are_redacted() -> None:
    err = ApiError(
        f"ошибка с токеном {_REAL_TOKEN}",
        response_body={"token": _REAL_TOKEN, "id": 1},
    )
    assert _REAL_TOKEN not in str(err)
    assert _REAL_TOKEN not in repr(err.response_body)
    assert err.response_body["id"] == 1


# ---------------- F-0.7: pre-send validation ----------------


def test_f07_ids_must_be_positive_integers() -> None:
    v = Validator(True)
    with pytest.raises(ValidationError):
        v.ids([0], field="Ids")
    with pytest.raises(ValidationError):
        v.ids([-5], field="Ids")
    with pytest.raises(ValidationError):
        v.ids(["1"], field="Ids")
    with pytest.raises(ValidationError):
        v.ids([], field="Ids")
    v.ids([1, 2], field="Ids")


def test_f07_region_zero_and_empty_rejected() -> None:
    v = Validator(True)
    with pytest.raises(ValidationError):
        v.region_ids([0])
    with pytest.raises(ValidationError):
        v.region_ids([])
    v.region_ids([225, -219])


def test_f07_name_and_text_limits() -> None:
    v = Validator(True)
    with pytest.raises(ValidationError):
        v.name("", field="Campaign.Name")
    with pytest.raises(ValidationError):
        v.name("x" * 61, field="Campaign.Name")
    with pytest.raises(ValidationError):
        v.text("y" * 82, field="TextAd.Text", max_length=81)
    v.text("ok", field="TextAd.Text", max_length=81)


def test_f07_href_and_amount_checks() -> None:
    v = Validator(True)
    with pytest.raises(ValidationError):
        v.href("example.com")
    with pytest.raises(ValidationError):
        v.href("")
    with pytest.raises(ValidationError):
        v.positive_amount(-1, field="DailyBudget")
    with pytest.raises(ValidationError):
        v.positive_amount(0, field="Bid")
    v.positive_amount(10.5, field="Bid")
    v.positive_amount(0, field="Budget", allow_zero=True)


def test_f07_validation_can_be_disabled() -> None:
    v = Validator(False)
    v.ids([0], field="Ids")
    v.region_ids([0])
    v.name("", field="Campaign.Name")


@responses.activate
def test_f07_validation_prevents_http_request() -> None:
    """Невалидный payload не должен уходить в сеть (F-0.7)."""
    with _client(client_login="TESTLOGIN") as c:
        with pytest.raises(ValidationError):
            c.ad_groups.create([{"CampaignId": 0, "Name": "g", "RegionIds": [225]}])
        with pytest.raises(ValidationError):
            c.ad_groups.create([{"CampaignId": 1, "Name": "g", "RegionIds": [0]}])
    assert len(responses.calls) == 0


@responses.activate
def test_f07_validate_false_sends_request() -> None:
    """`validate=False` — escape-hatch для отладки сырых payload'ов."""
    responses.add(
        responses.POST,
        V5_ADGROUPS,
        json={"result": {"AddResults": [{"Id": 9}]}},
    )
    with _client(client_login="TESTLOGIN", validate=False) as c:
        res = c.ad_groups.create([{"CampaignId": 0, "Name": "g", "RegionIds": [0]}])
    assert res[0]["Id"] == 9


def test_f07_validate_flag_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_VALIDATE", "0")
    with _client() as c:
        assert c.validate is False
    monkeypatch.setenv("YANDEX_DIRECT_VALIDATE", "1")
    with _client() as c:
        assert c.validate is True
