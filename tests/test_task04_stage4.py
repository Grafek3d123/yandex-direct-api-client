"""Тесты слоя 4 STAGE_05: таргетинг — демография, интересы, ретаргетинг.

Идентификаторы критериев приёмки (tasks/task04.md, §7):

- F-4.1 — спеки `DemographicsSpec`, `InterestSpec`, `RetargetingSpec` и
  типизированные билдеры `audiencetargets` вместо сырых словарей;
- F-4.2 — `InterestSpec.resolve(name)` через справочник с кэшем и
  `ValidationError` при неоднозначности;
- F-4.3 — матрица допустимости «тип группы × вид нацеливания»;
- F-4.4 — несовместимая комбинация → `ValidationError` **до** сети;
- F-4.5 — полный сценарий «сегмент → условие нацеливания → корректировка»;
- F-4.6 — ключевые фразы неприменимы к медийным группам;
- F-4.7 — `AutotargetingSettings` для динамических групп.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.constants import (
    TARGET_KIND_DEMOGRAPHICS,
    TARGET_KIND_INTEREST,
    TARGET_KIND_KEYWORD,
    TARGET_KIND_RETARGETING,
    interest_prefix,
    is_allowed,
    segment_external_id,
)
from yandex_direct_api_client.exceptions import ApiError, ValidationError
from yandex_direct_api_client.models.ad_group_payloads import (
    AutotargetingSetting,
    DynamicFeedAdGroup,
    DynamicSiteAdGroup,
    build_ad_group,
)
from yandex_direct_api_client.models.targeting import (
    GENDER_ALL,
    GENDER_FEMALE,
    ContextTarget,
    DemographicsSpec,
    DemographicsTarget,
    InterestSpec,
    InterestTarget,
    RetargetingList,
    RetargetingSpec,
    RetargetingTarget,
    check_keywords_allowed,
)
from yandex_direct_api_client.services.retargeting_lists import (
    RetargetingListService,
)
from yandex_direct_api_client.services.targeting import TargetingService

DICT_URL_V5 = "https://api.direct.yandex.com/json/v5/dictionaries/"
DICT_URL_V501 = "https://api.direct.yandex.com/json/v501/dictionaries/"
RL_URL = "https://api.direct.yandex.com/json/v5/retargetinglists/"
AT_URL = "https://api.direct.yandex.com/json/v5/audiencetargets/"
ADJ_URL = "https://api.direct.yandex.com/json/v5/retargetingadjustments/"
ADGROUPS_URL = "https://api.direct.yandex.com/json/v5/adgroups/"

#: Сегменты демографии, как их отдаёт `AudienceDemographicProfiles`.
PROFILES = [
    {"Id": 101, "Type": "AGE", "Name": "18-24", "Description": "молодые"},
    {"Id": 102, "Type": "AGE", "Name": "25-34", "Description": "молодые"},
    {"Id": 201, "Type": "GENDER", "Name": "Мужчины", "Description": "мужчины"},
    {"Id": 202, "Type": "GENDER", "Name": "Женщины", "Description": "женщины"},
]

#: Интересы мобильных приложений, как их отдаёт `Interests`.
INTERESTS = [
    {"InterestId": 2499001182, "InterestName": "Авиабилеты"},
    {"InterestId": 2499001182, "InterestName": "Авиабилеты"},
    {"InterestId": 2499001105, "InterestName": "Гостиницы"},
]


def _body_of(call: Any) -> Dict[str, Any]:
    """Разобрать JSON-тело исходящего запроса."""
    return json.loads(call.request.body)


@pytest.fixture(autouse=True)
def isolated_cache(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """Изолировать дисковый кэш справочников от домашнего каталога.

    Справочники сегментов кэшируются на 7 суток, поэтому без изоляции тесты
    видели бы данные предыдущего прогона и загрязняли кэш пользователя.
    """
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("YANDEX_DIRECT_CACHE_DIR", str(cache_dir))
    return cache_dir


def _client(**kwargs: Any) -> YandexDirectClient:
    """Клиент с тестовыми настройками."""
    params: Dict[str, Any] = {
        "token": "test_token",
        "rate_limit_rps": 1000.0,
        "max_retries": 1,
    }
    params.update(kwargs)
    return YandexDirectClient(**params)


# ---------------------------------------------------------------- F-4.1/F-4.2


def test_demographics_spec_resolves_names_to_ids() -> None:
    from yandex_direct_api_client.models.dictionaries import (
        AudienceDemographicProfile,
    )

    segments = [AudienceDemographicProfile.from_dict(item) for item in PROFILES]
    spec = DemographicsSpec(
        age_ranges=["25-34"], gender=GENDER_FEMALE,
        gender_names={GENDER_FEMALE: "Женщины"},
    )
    assert spec.resolve(segments) == [102, 202]


def test_demographics_spec_age_only() -> None:
    from yandex_direct_api_client.models.dictionaries import (
        AudienceDemographicProfile,
    )

    segments = [AudienceDemographicProfile.from_dict(item) for item in PROFILES]
    spec = DemographicsSpec(age_ranges=["18-24", "25-34"])
    assert spec.resolve(segments) == [101, 102]


def test_demographics_spec_unknown_segment() -> None:
    from yandex_direct_api_client.models.dictionaries import (
        AudienceDemographicProfile,
    )

    segments = [AudienceDemographicProfile.from_dict(item) for item in PROFILES]
    with pytest.raises(ValidationError) as exc:
        DemographicsSpec(age_ranges=["99-100"]).resolve(segments)
    assert "99-100" in str(exc.value)


def test_demographics_spec_ambiguous_segment() -> None:
    from yandex_direct_api_client.models.dictionaries import (
        AudienceDemographicProfile,
    )

    segments = [
        AudienceDemographicProfile.from_dict(item)
        for item in PROFILES
        + [{"Id": 103, "Type": "AGE", "Name": "25-34"}]
    ]
    with pytest.raises(ValidationError) as exc:
        DemographicsSpec(age_ranges=["25-34"]).resolve(segments)
    assert "неоднозначен" in str(exc.value)


def test_demographics_spec_gender_requires_explicit_names() -> None:
    from yandex_direct_api_client.models.dictionaries import (
        AudienceDemographicProfile,
    )

    segments = [AudienceDemographicProfile.from_dict(item) for item in PROFILES]
    spec = DemographicsSpec(age_ranges=["25-34"], gender=GENDER_FEMALE)
    with pytest.raises(ValidationError) as exc:
        spec.resolve(segments)
    assert "gender_names" in str(exc.value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"age_ranges": [], "gender": GENDER_ALL},
        {"age_ranges": ["25-34"], "gender": "ALien"},
    ],
)
def test_demographics_spec_validation(kwargs: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DemographicsSpec(**kwargs)


def test_interest_spec_resolve_by_name() -> None:
    from yandex_direct_api_client.models.dictionaries import Interest

    interests = [Interest.from_dict(item) for item in INTERESTS]
    spec = InterestSpec.resolve("гостиницы", interests)
    assert spec.interest_ids == [2499001105]


def test_interest_spec_resolve_unknown() -> None:
    from yandex_direct_api_client.models.dictionaries import Interest

    interests = [Interest.from_dict(item) for item in INTERESTS]
    with pytest.raises(ValidationError) as exc:
        InterestSpec.resolve("Париж", interests)
    assert "Париж" in str(exc.value)


def test_interest_spec_resolve_ambiguous_name() -> None:
    from yandex_direct_api_client.models.dictionaries import Interest

    interests = [
        Interest.from_dict(item)
        for item in INTERESTS + [{"InterestId": 777, "InterestName": "Гостиницы"}]
    ]
    with pytest.raises(ValidationError) as exc:
        InterestSpec.resolve("Гостиницы", interests)
    assert "неоднозначен" in str(exc.value)


def test_interest_spec_segment_ids_with_prefix() -> None:
    spec = InterestSpec(interest_ids=[2499001182], importance="SHORT_TERM")
    assert spec.segment_ids() == [102499001182]
    long_term = InterestSpec(interest_ids=[2499001182], importance="LONG_TERM")
    assert long_term.segment_ids() == [202499001182]


def test_interest_spec_segment_ids_passthrough() -> None:
    spec = InterestSpec(interest_ids=[102499001182], use_segment_ids=True)
    assert spec.segment_ids() == [102499001182]
    with pytest.raises(ValidationError):
        InterestSpec(
            interest_ids=[102499001182],
            importance="LONG_TERM",
            use_segment_ids=True,
        ).segment_ids()


def test_segment_external_id_matches_documentation() -> None:
    # Пример из документации: интерес 2499001105 + долгосрочный интерес.
    assert segment_external_id(2499001105, "LONG_TERM") == 202499001105
    assert interest_prefix("ANY") == 30
    with pytest.raises(ValidationError):
        segment_external_id(0, "ANY")
    with pytest.raises(ValidationError):
        segment_external_id(5, "NEVER")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"list_id": None, "goal_id": None},
        {"list_id": 5, "goal_id": 7},
        {"list_id": 0},
        {"goal_id": 10, "membership_life_span": 0},
        {"goal_id": 10, "membership_life_span": 541},
    ],
)
def test_retargeting_spec_validation(kwargs: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RetargetingSpec(**kwargs)


def test_retargeting_spec_rule_argument() -> None:
    spec = RetargetingSpec(goal_id=123, membership_life_span=30)
    assert spec.to_rule_argument() == {
        "ExternalId": 123,
        "MembershipLifeSpan": 30,
    }
    with pytest.raises(ValidationError):
        RetargetingSpec(list_id=5).to_rule_argument()
    with pytest.raises(ValidationError):
        RetargetingSpec(goal_id=1).to_target(10)


# --------------------------------------------------------------------- F-4.3


@pytest.mark.parametrize(
    "ad_group_type,kind,allowed",
    [
        ("TEXT_AD_GROUP", TARGET_KIND_RETARGETING, True),
        ("CPM_BANNER_AD_GROUP", TARGET_KIND_RETARGETING, True),
        ("UNIFIED_AD_GROUP", TARGET_KIND_RETARGETING, True),
        ("MOBILE_APP_AD_GROUP", TARGET_KIND_RETARGETING, True),
        ("DYNAMIC_FEED_AD_GROUP", TARGET_KIND_RETARGETING, False),
        ("MOBILE_APP_AD_GROUP", TARGET_KIND_INTEREST, True),
        ("TEXT_AD_GROUP", TARGET_KIND_INTEREST, False),
        ("CPM_BANNER_AD_GROUP", TARGET_KIND_INTEREST, False),
        ("CPM_BANNER_AD_GROUP", TARGET_KIND_DEMOGRAPHICS, True),
        ("TEXT_AD_GROUP", TARGET_KIND_DEMOGRAPHICS, True),
        ("MOBILE_APP_AD_GROUP", TARGET_KIND_DEMOGRAPHICS, False),
        ("CPM_BANNER_AD_GROUP", TARGET_KIND_KEYWORD, False),
        ("TEXT_AD_GROUP", TARGET_KIND_KEYWORD, True),
    ],
)
def test_compatibility_matrix(
    ad_group_type: str, kind: str, allowed: bool
) -> None:
    assert is_allowed(ad_group_type, kind) is allowed


def test_matrix_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        is_allowed("TEXT_AD_GROUP", "teleportation")


def test_interest_target_on_text_group_rejected_before_network() -> None:
    target = InterestTarget(
        ad_group_id=10, interest_id=5, ad_group_type="TEXT_AD_GROUP"
    )
    with pytest.raises(ValidationError) as exc:
        target.to_payload()
    assert "MOBILE_APP_AD_GROUP" in str(exc.value)


def test_retargeting_target_on_dynamic_group_rejected() -> None:
    target = RetargetingTarget(
        ad_group_id=10, retargeting_list_id=5, ad_group_type="DYNAMIC_FEED_AD_GROUP"
    )
    with pytest.raises(ValidationError) as exc:
        target.to_payload()
    assert "ретаргетинг недопустим" in str(exc.value)


def test_retargeting_target_payload() -> None:
    target = RetargetingTarget(
        ad_group_id=10,
        retargeting_list_id=77,
        context_bid=500_000,
        strategy_priority="HIGH",
        ad_group_type="CPM_BANNER_AD_GROUP",
    )
    assert target.to_payload() == {
        "AdGroupId": 10,
        "ContextBid": 500_000,
        "StrategyPriority": "HIGH",
        "RetargetingListId": 77,
    }


def test_interest_target_payload() -> None:
    target = InterestTarget(
        ad_group_id=20, interest_id=2499001182, ad_group_type="MOBILE_APP_AD_GROUP"
    )
    assert target.to_payload() == {
        "AdGroupId": 20,
        "InterestId": 2499001182,
    }


def test_context_target_reports_api_limitation() -> None:
    with pytest.raises(ValidationError) as exc:
        ContextTarget(ad_group_id=10, url="example.com").to_payload()
    assert "RetargetingListId" in str(exc.value)


def test_demographics_target_requires_resolved_ids() -> None:
    target = DemographicsTarget(
        ad_group_id=10, spec=DemographicsSpec(age_ranges=["25-34"])
    )
    with pytest.raises(ValidationError) as exc:
        target.to_retargeting_list()
    assert "resolve_demographics" in str(exc.value)


def test_demographics_target_builds_audience_list() -> None:
    target = DemographicsTarget(
        ad_group_id=10, segment_ids=[102, 202], name="Женщины 25-34"
    )
    body = target.to_retargeting_list()
    assert body == {
        "Name": "Женщины 25-34",
        "Type": "AUDIENCE",
        "Rules": [{"Arguments": [{"ExternalId": 102}, {"ExternalId": 202}], "Operator": "ANY"}],
    }
    assert target.to_audience_target(555).to_payload()["RetargetingListId"] == 555


def test_demographics_target_on_text_group_rejected() -> None:
    target = DemographicsTarget(
        ad_group_id=10, segment_ids=[102], ad_group_type="MOBILE_APP_AD_GROUP"
    )
    with pytest.raises(ValidationError):
        target.to_retargeting_list()


def test_demographics_target_name_is_required() -> None:
    target = DemographicsTarget(
        ad_group_id=10, segment_ids=[102, 202]
    )
    with pytest.raises(ValidationError) as exc:
        target.to_retargeting_list()
    assert "name" in str(exc.value).lower()


# --------------------------------------------------------------------- F-4.6


@pytest.mark.parametrize(
    "ad_group_type",
    ["CPM_BANNER_AD_GROUP", "CPM_VIDEO_AD_GROUP", "UNIFIED_AD_GROUP"],
)
def test_keywords_rejected_for_media_groups(ad_group_type: str) -> None:
    with pytest.raises(ValidationError) as exc:
        check_keywords_allowed(ad_group_type)
    assert "ключевые фразы" in str(exc.value).lower()


def test_keywords_allowed_for_text_group() -> None:
    assert check_keywords_allowed("TEXT_AD_GROUP") is None


# --------------------------------------------------------------------- F-4.7


def test_autotargeting_setting_payload() -> None:
    assert AutotargetingSetting("EXACT").to_payload() == {
        "Category": "EXACT",
        "Value": "YES",
    }
    assert AutotargetingSetting("COMPETITOR", enabled=False).to_payload() == {
        "Category": "COMPETITOR",
        "Value": "NO",
    }
    with pytest.raises(ValidationError):
        AutotargetingSetting("SOMETHING")


def test_autotargeting_setting_default_enables_with_warning(caplog) -> None:
    with caplog.at_level(
        "WARNING", logger="yandex_direct_api_client.models.ad_group_payloads"
    ):
        setting = AutotargetingSetting("EXACT")
    assert setting.enabled is True
    assert any("enabled не задан" in r.message for r in caplog.records)


def test_autotargeting_setting_explicit_no_warn(caplog) -> None:
    with caplog.at_level(
        "WARNING", logger="yandex_direct_api_client.models.ad_group_payloads"
    ):
        setting = AutotargetingSetting("EXACT", enabled=False)
    assert setting.enabled is False
    assert not [r for r in caplog.records if "enabled не задан" in r.message]


def test_dynamic_site_ad_group_payload() -> None:
    group = DynamicSiteAdGroup(
        name="Динамика",
        campaign_id=1,
        region_ids=[225],
        domain_url="example.com",
        autotargeting_settings=[
            AutotargetingSetting("EXACT"),
            AutotargetingSetting("BROADER", enabled=False),
        ],
    )
    body = group.to_payload()
    assert body["DynamicTextAdGroup"] == {
        "DomainUrl": "example.com",
        "AutotargetingCategories": [
            {"Category": "EXACT", "Value": "YES"},
            {"Category": "BROADER", "Value": "NO"},
        ],
    }
    with pytest.raises(ValidationError):
        DynamicSiteAdGroup(
            name="x" * 5, campaign_id=1, region_ids=[225], domain_url=""
        ).to_payload()


def test_dynamic_feed_ad_group_payload() -> None:
    group = DynamicFeedAdGroup(
        name="Фид",
        campaign_id=1,
        region_ids=[225],
        feed_id=42,
        autotargeting_settings=[{"Category": "ACCESSORY", "Value": "NO"}],
    )
    assert group.to_payload()["DynamicTextFeedAdGroup"] == {
        "FeedId": 42,
        "AutotargetingCategories": [{"Category": "ACCESSORY", "Value": "NO"}],
    }
    with pytest.raises(ValidationError):
        DynamicFeedAdGroup(name="Фид", campaign_id=1, region_ids=[225]).to_payload()


def test_build_ad_group_supports_dynamic_types() -> None:
    group = build_ad_group(
        "DYNAMIC_SITE_AD_GROUP",
        name="Динамика",
        campaign_id=1,
        region_ids=[225],
        domain_url="example.com",
    )
    assert "DynamicTextAdGroup" in group.to_payload()


# ---------------------------------------------------------- справочники (F-4.2)


@responses.activate
def test_audience_demographic_profiles_dictionaries() -> None:
    responses.add(
        responses.POST, DICT_URL_V501, json={"result": {"AudienceDemographicProfiles": PROFILES}}
    )
    with _client() as c:
        segments = c.dictionaries.audience_demographic_profiles()
    assert [s.id for s in segments] == [101, 102, 201, 202]
    assert segments[0].type == "AGE"
    assert segments[3].name == "Женщины"
    sent = _body_of(responses.calls[0])["params"]
    assert sent == {"DictionaryNames": ["AudienceDemographicProfiles"]}


@responses.activate
def test_audience_profiles_of_type_filters() -> None:
    responses.add(
        responses.POST, DICT_URL_V501, json={"result": {"AudienceDemographicProfiles": PROFILES}}
    )
    with _client() as c:
        ages = c.dictionaries.audience_profiles_of_type("AGE")
    assert [s.name for s in ages] == ["18-24", "25-34"]


@responses.activate
def test_audience_criteria_types_and_interests() -> None:
    responses.add(
        responses.POST,
        DICT_URL_V501,
        json={
            "result": {
                "AudienceCriteriaTypes": [
                    {
                        "Type": "AGE",
                        "Name": "Возраст",
                        "BlockElement": "age",
                        "CanSelect": "EXCEPT_ALL",
                    }
                ]
            }
        },
    )
    responses.add(
        responses.POST,
        DICT_URL_V501,
        json={
            "result": {
                "AudienceInterests": [
                    {
                        "Id": 102499001182,
                        "InterestKey": 2499001182,
                        "Name": "Авиабилеты",
                        "InterestType": "SHORT_TERM",
                    }
                ]
            }
        },
    )
    with _client() as c:
        criteria = c.dictionaries.audience_criteria_types()
        segments = c.dictionaries.audience_interests()
    assert criteria[0].can_select == "EXCEPT_ALL"
    assert segments[0].id == 102499001182
    assert segments[0].interest_key == 2499001182


@responses.activate
def test_audience_dictionary_missing_list_raises() -> None:
    responses.add(responses.POST, DICT_URL_V501, json={"result": {}})
    with _client() as c:
        with pytest.raises(ApiError):
            c.dictionaries.audience_demographic_profiles()


# -------------------------------------------------- сервис retargetinglists


def test_retargeting_list_model_payload() -> None:
    segment = RetargetingList(
        name="Женщины 25-34",
        type="AUDIENCE",
        rules=[{"Arguments": [{"ExternalId": 202}], "Operator": "ANY"}],
        description="сегмент SDK",
    )
    assert segment.to_add_payload() == {
        "Name": "Женщины 25-34",
        "Type": "AUDIENCE",
        "Rules": [{"Arguments": [{"ExternalId": 202}], "Operator": "ANY"}],
        "Description": "сегмент SDK",
    }
    with pytest.raises(ValidationError):
        segment.to_update_payload()
    segment.id = 5
    assert segment.to_update_payload()["Id"] == 5


@pytest.mark.parametrize(
    "rules",
    [
        [],
        [{"Operator": "ANY"}],
        [{"Operator": "SOMETIMES", "Arguments": [{"ExternalId": 1}]}],
        [{"Operator": "ANY", "Arguments": []}],
        [{"Operator": "ANY", "Arguments": [{"MembershipLifeSpan": 30}]}],
        [{"Operator": "ANY", "Arguments": [{"ExternalId": 1, "MembershipLifeSpan": 999}]}],
    ],
)
def test_retargeting_list_rules_validation(rules: List[Dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        RetargetingList(name="Сегмент", rules=rules)


def test_retargeting_list_rules_limit() -> None:
    rules = [
        {"Operator": "ANY", "Arguments": [{"ExternalId": i}]} for i in range(51)
    ]
    with pytest.raises(ValidationError) as exc:
        RetargetingList(name="Сегмент", rules=rules)
    assert "50" in str(exc.value)


@responses.activate
def test_retargeting_lists_get_and_filter() -> None:
    responses.add(
        responses.POST,
        RL_URL,
        json={
            "result": {
                "RetargetingLists": [
                    {
                        "Id": 5,
                        "Name": "Сегмент",
                        "Type": "AUDIENCE",
                        "Rules": [{"Arguments": [{"ExternalId": 1}], "Operator": "ANY"}],
                        "AvailableForTargetsInAdGroupTypes": [
                            "CPM_BANNER_AD_GROUP"
                        ],
                    }
                ]
            }
        },
    )
    with _client() as c:
        segments = c.retargeting_lists.get(types=["AUDIENCE"])
    assert segments[0].id == 5
    assert segments[0].available_for_ad_group_types == ["CPM_BANNER_AD_GROUP"]
    sent = _body_of(responses.calls[0])["params"]
    assert sent["SelectionCriteria"]["Types"] == ["AUDIENCE"]
    assert "Type" in sent["FieldNames"]


@responses.activate
def test_list_for_group_type_uses_server_field() -> None:
    responses.add(
        responses.POST,
        RL_URL,
        json={
            "result": {
                "RetargetingLists": [
                    {
                        "Id": 5,
                        "Name": "A",
                        "Type": "AUDIENCE",
                        "Rules": [{"Arguments": [{"ExternalId": 1}], "Operator": "ANY"}],
                        "AvailableForTargetsInAdGroupTypes": [
                            "CPM_BANNER_AD_GROUP"
                        ],
                    },
                    {
                        "Id": 6,
                        "Name": "B",
                        "Type": "AUDIENCE",
                        "Rules": [{"Arguments": [{"ExternalId": 2}], "Operator": "ANY"}],
                        "AvailableForTargetsInAdGroupTypes": [
                            "MOBILE_APP_AD_GROUP"
                        ],
                    },
                ]
            }
        },
    )
    with _client() as c:
        segments = c.retargeting_lists.list_for_group_type("CPM_BANNER_AD_GROUP")
    assert [s.id for s in segments] == [5]


@responses.activate
def test_retargeting_lists_create_update_delete() -> None:
    responses.add(
        responses.POST, RL_URL, json={"result": {"AddResults": [{"Id": 5}]}}
    )
    responses.add(
        responses.POST, RL_URL, json={"result": {"UpdateResults": [{"Id": 5}]}}
    )
    responses.add(
        responses.POST, RL_URL, json={"result": {"DeleteResults": [{"Id": 5}]}}
    )
    segment = RetargetingList(
        name="Сегмент",
        type="AUDIENCE",
        rules=[{"Arguments": [{"ExternalId": 202}], "Operator": "ANY"}],
        id=5,
    )
    with _client() as c:
        assert c.retargeting_lists.create([segment])[0]["Id"] == 5
        assert c.retargeting_lists.update([segment], confirm=True)[0]["Id"] == 5
        assert c.retargeting_lists.delete([5], confirm=True)[0]["Id"] == 5
    add_sent = _body_of(responses.calls[0])["params"]["RetargetingLists"][0]
    assert add_sent["Type"] == "AUDIENCE"
    upd_sent = _body_of(responses.calls[1])["params"]["RetargetingLists"][0]
    assert upd_sent["Id"] == 5
    del_sent = _body_of(responses.calls[2])["params"]
    assert del_sent == {"SelectionCriteria": {"Ids": [5]}}


@responses.activate
def test_retargeting_lists_update_requires_confirm() -> None:
    segment = RetargetingList(
        name="Сегмент", rules=[{"Arguments": [{"ExternalId": 1}], "Operator": "ANY"}]
    )
    with _client() as c:
        with pytest.raises(ValidationError):
            c.retargeting_lists.update([segment])
    assert len(responses.calls) == 0


def test_readonly_blocks_retargeting_lists_and_targeting() -> None:
    with _client(readonly=True) as c:
        with pytest.raises(ValidationError):
            c.retargeting_lists.create(
                [
                    RetargetingList(
                        name="x",
                        rules=[{"Arguments": [{"ExternalId": 1}], "Operator": "ANY"}],
                    )
                ]
            )
        with pytest.raises(ValidationError):
            c.targeting.create_audience_target(
                10, DemographicsTarget(ad_group_id=10, segment_ids=[1])
            )
    assert len(responses.calls) == 0


def test_create_audience_segment_helper_rejects_bad_operator() -> None:
    service = RetargetingListService(_transport_of(_client()))
    with pytest.raises(ValidationError) as exc:
        service.create_audience_segment("Сегмент", [1], operator="ALL")
    assert "ANY" in str(exc.value)
    with pytest.raises(ValidationError):
        service.create_audience_segment("Сегмент", [])


def _transport_of(client: YandexDirectClient) -> Any:
    """Достать транспорт клиента (внутренняя деталь для unit-теста хелпера)."""
    return client._transport  # type: ignore[attr-defined]


# ------------------------------------------------------------------- F-4.5


@responses.activate
def test_full_scenario_segment_to_condition_to_adjustment() -> None:
    responses.add(
        responses.POST, DICT_URL_V501, json={"result": {"AudienceDemographicProfiles": PROFILES}}
    )
    responses.add(
        responses.POST, RL_URL, json={"result": {"AddResults": [{"Id": 700}]}}
    )
    responses.add(
        responses.POST, AT_URL, json={"result": {"AddResults": [{"Id": 800}]}}
    )
    responses.add(
        responses.POST,
        ADJ_URL,
        json={"result": {"AddResults": [{"Id": 900}]}},
    )
    with _client() as c:
        target = c.targeting.resolve_demographics(
            DemographicsSpec(
                age_ranges=["25-34"], gender=GENDER_FEMALE,
                gender_names={GENDER_FEMALE: "Женщины"},
            )
        )
        assert target.segment_ids == [102, 202]
        created = c.targeting.create_audience_target(123, target, context_bid=500_000)
        assert created.retargeting_list_id == 700
        assert created.audience_target_id == 800
        adjustment = c.retargeting_adjustments.add(
            [
                {
                    "CampaignId": 1,
                    "SegmentId": created.retargeting_list_id,
                    "Type": "NSC",
                    "LevelId": 123,
                    "LevelType": "DEVICE",
                    "BidDelta": 20,
                }
            ]
        )
    assert adjustment[0]["Id"] == 900
    list_sent = _body_of(responses.calls[1])["params"]["RetargetingLists"][0]
    assert list_sent["Type"] == "AUDIENCE"
    assert list_sent["Rules"][0]["Operator"] == "ANY"
    at_sent = _body_of(responses.calls[2])["params"]["AudienceTargets"][0]
    assert at_sent == {
        "AdGroupId": 123,
        "ContextBid": 500_000,
        "RetargetingListId": 700,
    }
    adj_sent = _body_of(responses.calls[3])["params"]["RetargetingAdjustments"][0]
    assert adj_sent["SegmentId"] == 700


@responses.activate
def test_create_audience_target_surfaces_item_error() -> None:
    responses.add(
        responses.POST, RL_URL, json={"result": {"AddResults": [{"Id": 700}]}}
    )
    responses.add(
        responses.POST,
        AT_URL,
        json={
            "result": {
                "AddResults": [
                    {"Errors": [{"Code": 34, "Message": "Audience target is full"}]}
                ]
            }
        },
    )
    with _client() as c:
        with pytest.raises(ApiError) as exc:
            c.targeting.create_audience_target(
                123, DemographicsTarget(
                    ad_group_id=0, segment_ids=[102], name="Сегмент"
                )
            )
    assert "Audience target is full" in str(exc.value)


@responses.activate
def test_resolve_interest_uses_dictionary() -> None:
    responses.add(
        responses.POST,
        DICT_URL_V501,
        json={
            "result": {
                "Interests": [
                    {"InterestId": 2499001105, "InterestName": "Гостиницы"},
                ]
            }
        },
    )
    with _client() as c:
        spec = c.targeting.resolve_interest("Гостиницы", importance="LONG_TERM")
    assert spec.interest_ids == [2499001105]
    assert spec.segment_ids() == [202499001105]


@responses.activate
def test_demographic_segment_names_listing() -> None:
    responses.add(
        responses.POST, DICT_URL_V501, json={"result": {"AudienceDemographicProfiles": PROFILES}}
    )
    with _client() as c:
        assert c.targeting.demographic_segment_names("AGE") == ["18-24", "25-34"]
        assert c.targeting.demographic_segment_names("GENDER") == ["Женщины", "Мужчины"]


def test_targeting_service_builders() -> None:
    service = TargetingService(
        _transport_of(_client()),
        dictionaries=_client()._dictionaries,  # type: ignore[attr-defined]
        retargeting_lists=_client()._retargeting_lists,  # type: ignore[attr-defined]
    )
    retargeting = service.retargeting_target(
        10,
        RetargetingSpec(list_id=5),
        context_bid=100_000,
        ad_group_type="CPM_BANNER_AD_GROUP",
    )
    assert retargeting.to_payload()["RetargetingListId"] == 5
    interest = service.interest_target(20, InterestSpec(interest_ids=[7]))
    assert interest.to_payload()["InterestId"] == 7
    with pytest.raises(ValidationError):
        service.interest_target(20, InterestSpec(interest_ids=[7, 8]))


# ------------------------------------------- readonly по новым методам (G16)


def test_readonly_covers_new_mutating_methods() -> None:
    with _client(readonly=True) as c:
        with pytest.raises(ValidationError):
            c.retargeting_lists.update(
                [RetargetingList(name="x", rules=[{"Arguments": [{"ExternalId": 1}], "Operator": "ANY"}])],
                confirm=True,
            )
        with pytest.raises(ValidationError):
            c.retargeting_lists.delete([1], confirm=True)
    assert len(responses.calls) == 0
