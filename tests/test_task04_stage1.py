"""Тесты слоя 1 STAGE_05 (tasks/task04.md): справочники, гео-резолв, лимиты клиента.

Идентификаторы критериев приёмки:
- F-1.1 — `DictionariesService` + дисковый кэш (7 суток);
- F-1.2 — `RegionSelector(include/exclude)` без зашитых бизнес-значений;
- F-1.3 — `ClientsService` + `Restrictions` + `can_create_campaign`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.cache import CACHE_FILE_NAME, JsonCache
from yandex_direct_api_client.exceptions import ApiError, ValidationError
from yandex_direct_api_client.models.dictionaries import DictEntry, GeoRegion
from yandex_direct_api_client.region_selector import RegionSelector
from yandex_direct_api_client.services.clients import (
    LIMIT_CAMPAIGNS_TOTAL,
    ClientInfo,
)

DICTIONARIES_URL_V5 = "https://api.direct.yandex.com/json/v5/dictionaries/"
DICTIONARIES_URL_V501 = "https://api.direct.yandex.com/json/v501/dictionaries/"
CLIENTS_URL = "https://api.direct.yandex.com/json/v5/clients/"


def _body_of(call: Any) -> Dict[str, Any]:
    """Разобрать JSON-тело исходящего запроса."""
    return json.loads(call.request.body)


def _client(cache: JsonCache) -> YandexDirectClient:
    """Клиент с изолированным кэшем справочников."""
    return YandexDirectClient(
        token="test_token",
        client_login="TESTLOGIN",
        rate_limit_rps=1000.0,
        max_retries=1,
        cache=cache,
    )


def _regions_payload() -> Dict[str, Any]:
    """Справочник регионов РФ: 82 области + 4 исключённых + иерархия (v501 формат)."""
    regions: List[Dict[str, Any]] = [
        {"GeoRegionId": 225, "GeoRegionName": "Россия", "GeoRegionType": "Country", "ParentId": 1},
    ]
    # 4 региона, которые бизнес исключает.
    regions += [
        {"GeoRegionId": 213, "GeoRegionName": "Москва", "GeoRegionType": "City", "ParentId": 225},
        {"GeoRegionId": 214, "GeoRegionName": "Московская область", "GeoRegionType": "Region", "ParentId": 225},
        {"GeoRegionId": 2, "GeoRegionName": "Санкт-Петербург", "GeoRegionType": "City", "ParentId": 225},
        {
            "GeoRegionId": 69,
            "GeoRegionName": "Ленинградская область",
            "GeoRegionType": "Region",
            "ParentId": 225,
        },
    ]
    # Ещё 80 областей (имитация полного справочника РФ).
    for i in range(1, 81):
        regions.append(
            {
                "GeoRegionId": 1000 + i,
                "GeoRegionName": f"Область {i}",
                "GeoRegionType": "Region",
                "ParentId": 225,
            }
        )
    return {"result": {"GeoRegions": regions}}


@pytest.fixture
def cache(tmp_path: Path) -> JsonCache:
    """Изолированный кэш в временном каталоге теста."""
    return JsonCache(cache_dir=tmp_path / "cache")


# ---------------- F-1.1: справочники ----------------


@responses.activate
def test_f11_geo_regions_parsed(cache: JsonCache) -> None:
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        regions = c.dictionaries.geo_regions("RUC")
    assert len(regions) >= 80
    assert regions[0].id == 225
    assert regions[0].name == "Россия"
    assert regions[0].is_top_level
    assert any(r.name == "Москва" for r in regions)
    payload = _body_of(responses.calls[0])
    assert payload["method"] == "get"
    assert "DictionaryNames" in payload["params"]
    assert payload["params"]["DictionaryNames"] == ["GeoRegions"]


@responses.activate
def test_f11_second_call_served_from_cache(cache: JsonCache) -> None:
    """Повторный вызов справочника не должен ходить в сеть (F-1.1 AC)."""
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        first = c.dictionaries.geo_regions()
        second = c.dictionaries.geo_regions()
    assert len(responses.calls) == 1
    assert [r.id for r in first] == [r.id for r in second]
    assert (cache.cache_dir / CACHE_FILE_NAME).exists()


@responses.activate
def test_f11_cache_ttl_expiry_triggers_refetch(
    cache: JsonCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Просроченная запись кэша не используется."""
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        c.dictionaries.geo_regions()
        # Подставляем запись в прошлое.
        path = cache.cache_dir / CACHE_FILE_NAME
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.values():
            entry["stored_at"] = 0.0
        path.write_text(json.dumps(data), encoding="utf-8")
        c.dictionaries.geo_regions()
    assert len(responses.calls) == 2


@responses.activate
def test_f11_use_cache_false_always_fetches(cache: JsonCache) -> None:
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        c.dictionaries.geo_regions(use_cache=False)
        c.dictionaries.geo_regions(use_cache=False)
    assert len(responses.calls) == 2


@responses.activate
def test_f11_clear_cache_forces_refetch(cache: JsonCache) -> None:
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        c.dictionaries.geo_regions()
        assert c.dictionaries.clear_cache() is True
        c.dictionaries.geo_regions()
    assert len(responses.calls) == 2


@responses.activate
def test_f11_unknown_dictionary_raises_api_error(cache: JsonCache) -> None:
    """Неожиданный формат ответа справочника — понятная ApiError."""
    responses.add(responses.POST, DICTIONARIES_URL_V501, json={"result": {}})
    with _client(cache) as c:
        with pytest.raises(ApiError) as exc:
            c.dictionaries.geo_regions()
    assert "GeoRegions" in str(exc.value)


@responses.activate
def test_f11_broken_cache_file_is_ignored(cache: JsonCache) -> None:
    """Битый файл кэша не ломает клиент — запрос идёт в сеть."""
    cache.cache_dir.mkdir(parents=True, exist_ok=True)
    (cache.cache_dir / CACHE_FILE_NAME).write_text("{не json", encoding="utf-8")
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        regions = c.dictionaries.geo_regions()
    assert len(regions) >= 80


@responses.activate
def test_f11_interests_and_retargeting_lists(cache: JsonCache) -> None:
    responses.add(
        responses.POST,
        DICTIONARIES_URL_V501,
        json={"result": {"Interests": [{"InterestId": 1, "Name": "Авто", "ParentId": 0, "IsTargetable": "YES"}]}},
    )
    responses.add(
        responses.POST,
        DICTIONARIES_URL_V5,
        json={
            "result": {
                "RetargetingLists": [
                    {
                        "RetargetingListId": 7,
                        "Name": "Посетители",
                        "Type": "AUDIENCE",
                        "Subtype": "URL",
                        "GoalId": 123,
                    }
                ]
            }
        },
    )
    with _client(cache) as c:
        interests = c.dictionaries.interests(225)
        lists = c.dictionaries.retargeting_lists()
    assert interests[0].id == 1
    assert interests[0].name == "Авто"
    assert lists[0].id == 7
    assert lists[0].goal_id == 123
    assert "DictionaryNames" in _body_of(responses.calls[0])["params"]
    assert _body_of(responses.calls[0])["params"]["DictionaryNames"] == ["Interests"]
    assert "getRetargetingLists" in _body_of(responses.calls[1])["params"]


@responses.activate
def test_f11_currency_returns_single_object(cache: JsonCache) -> None:
    responses.add(
        responses.POST,
        DICTIONARIES_URL_V501,
        json={"result": {"Currencies": [{"Currency": "RUB", "Name": "рубль"}]}},
    )
    with _client(cache) as c:
        cur = c.dictionaries.currency()
    assert cur.currency == "RUB"


@responses.activate
def test_f11_dicts_escape_hatch(cache: JsonCache) -> None:
    responses.add(
        responses.POST,
        DICTIONARIES_URL_V5,
        json={"result": {"BingTypes": [{"BingType": "ALL", "Name": "Все"}]}},
    )
    with _client(cache) as c:
        entries = c.dictionaries.dicts("getBingTypes", {})
    assert isinstance(entries[0], DictEntry)
    assert entries[0].key == "BingTypes"
    assert entries[0].values_of("BingType") == ["ALL"]


@responses.activate
def test_f11_geo_hierarchy(cache: JsonCache) -> None:
    responses.add(
        responses.POST,
        DICTIONARIES_URL_V5,
        json={"result": {"GeoRegions": [{"GeoRegionId": 1, "GeoRegionName": "Москва", "GeoRegionType": "City", "ParentId": 225}]}},
    )
    with _client(cache) as c:
        regions = c.dictionaries.geo_hierarchy([213])
    assert regions[0].id == 1
    assert _body_of(responses.calls[0])["params"]["getGeoHierarchy"]["GeoRegionIds"] == [213]


# ---------------- F-1.2: RegionSelector ----------------


@responses.activate
def test_f12_exclude_four_regions(cache: JsonCache) -> None:
    """«Вся РФ кроме МСК/МО/СПб/ЛО» — прямой ответ на вопрос бизнеса."""
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    selector = RegionSelector(
        exclude=["Москва", "Московская область", "Санкт-Петербург", "Ленинградская область"]
    )
    with _client(cache) as c:
        ids = c.regions(selector)
    excluded = {213, 214, 2, 69}
    assert len(ids) >= 75
    assert not excluded & set(ids)
    assert len(ids) == len(set(ids))


@responses.activate
def test_f12_repeat_resolve_makes_no_extra_requests(cache: JsonCache) -> None:
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    selector = RegionSelector(exclude=["Москва"])
    with _client(cache) as c:
        first = c.regions(selector)
        second = c.regions(selector)
    assert first == second
    assert len(responses.calls) == 1, "второй резолв должен взять справочник из кэша"


@responses.activate
def test_f12_include_by_id_name_and_code(cache: JsonCache) -> None:
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        ids = c.regions(RegionSelector(include=[213, "Московская область"]))
    assert ids == [213, 214]
    assert len(responses.calls) == 1


@responses.activate
def test_f12_unknown_region_raises_with_suggestions(cache: JsonCache) -> None:
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        with pytest.raises(ValidationError) as exc:
            c.regions(RegionSelector(include=["Москва-не-существует"]))
    message = str(exc.value)
    assert "не найден" in message


@responses.activate
def test_f12_ambiguous_region_raises(cache: JsonCache) -> None:
    """Два региона с одинаковым названием → требование уточнить, а не выбор."""
    responses.add(
        responses.POST,
        DICTIONARIES_URL_V501,
        json={
            "result": {
                "GeoRegions": [
                    {"GeoRegionId": 1, "GeoRegionName": "Тверская область", "GeoRegionType": "Region", "ParentId": 225},
                    {"GeoRegionId": 2, "GeoRegionName": "Тверская область", "GeoRegionType": "Region", "ParentId": 225},
                ]
            }
        },
    )
    with _client(cache) as c:
        with pytest.raises(ValidationError) as exc:
            c.regions(RegionSelector(include=["Тверская область"]))
    assert "неоднозначно" in str(exc.value)


@responses.activate
def test_f12_empty_resolution_raises(cache: JsonCache) -> None:
    """Исключение всех регионов → ValidationError, а не `RegionIds: []`."""
    payload = {"result": {"GeoRegions": [{"GeoRegionId": 1, "GeoRegionName": "Москва", "GeoRegionType": "City", "ParentId": 225}]}}
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=payload)
    with _client(cache) as c:
        with pytest.raises(ValidationError):
            c.regions(RegionSelector(include=[1], exclude=[1]))


@responses.activate
def test_f12_no_lists_raises(cache: JsonCache) -> None:
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        with pytest.raises(ValidationError):
            c.regions(RegionSelector())


@responses.activate
def test_f12_include_all_russia(cache: JsonCache) -> None:
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        all_ids = c.regions(RegionSelector().include_all_russia())
        without_msk = c.regions(RegionSelector().include_all_russia().include_all_russia())
    assert len(all_ids) == 85
    assert all_ids == without_msk


def test_f12_current_reads_region_ids_from_model_and_dict() -> None:
    assert RegionSelector.current({"RegionIds": [1, 2, 3]}) == [1, 2, 3]
    assert RegionSelector.current({"RegionIds": {"Items": [4]}}) == [4]
    assert RegionSelector.current({}) == []

    class _Group:
        region_ids = [7, 8]

    assert RegionSelector.current(_Group()) == [7, 8]


@responses.activate
def test_f12_fake_region_id_rejected(cache: JsonCache) -> None:
    """Выдуманные ID запрещены (D5)."""
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=_regions_payload())
    with _client(cache) as c:
        with pytest.raises(ValidationError) as exc:
            c.regions(RegionSelector(include=[999999]))
    assert "не найден" in str(exc.value)


# ---------------- F-1.3: лимиты клиента ----------------


@responses.activate
def test_f13_clients_get_parsed(cache: JsonCache) -> None:
    responses.add(
        responses.POST,
        CLIENTS_URL,
        json={
            "result": {
                "Clients": [
                    {
                        "ClientInfo": "Тестовый клиент",
                        "Restrictions": [
                            {
                                "Element": "CAMPAIGNS_TOTAL_PER_CLIENT",
                                "Value": 100,
                            },
                            {
                                "Element": "CAMPAIGNS_UNARCHIVED_PER_CLIENT",
                                "Value": 50,
                            },
                        ],
                    }
                ]
            }
        },
    )
    with _client(cache) as c:
        info = c.clients.get()
    assert info.name == "Тестовый клиент"
    assert info.restriction(LIMIT_CAMPAIGNS_TOTAL) == 100
    assert info.can_create_campaign(5) is True
    assert info.can_create_campaign(60) is False
    assert "Restrictions" in _body_of(responses.calls[0])["params"]["FieldNames"]


def test_f13_can_create_campaign_without_limits() -> None:
    info = ClientInfo(id=1, raw={})
    assert info.restrictions == {}
    assert info.can_create_campaign(10_000) is True


def test_f13_can_create_campaign_rejects_negative() -> None:
    with pytest.raises(ValueError):
        ClientInfo(id=1, raw={}).can_create_campaign(-1)


# ---------------- JsonCache unit ----------------


def test_cache_roundtrip(tmp_path: Path) -> None:
    c = JsonCache(cache_dir=tmp_path)
    assert c.get("ns", {"a": 1}) is None
    assert c.set("ns", {"a": 1}, [1, 2]) is True
    assert c.get("ns", {"a": 1}) == [1, 2]
    assert c.get("ns", {"a": 2}) is None
    assert c.clear() is True
    assert c.get("ns", {"a": 1}) is None


def test_cache_ttl_expired(tmp_path: Path) -> None:
    c = JsonCache(ttl_seconds=0, cache_dir=tmp_path)
    c.set("ns", "k", "v")
    assert c.get("ns", "k") is None


def test_cache_env_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_CACHE_DIR", str(tmp_path / "custom"))
    c = JsonCache()
    c.set("ns", "k", "v")
    assert (tmp_path / "custom" / CACHE_FILE_NAME).exists()


def test_cache_write_failure_is_silent(tmp_path: Path) -> None:
    """Недоступный каталог не ломает клиент — операция возвращает False."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    c = JsonCache(cache_dir=blocker / "sub")
    assert c.set("ns", "k", "v") is False
    assert c.get("ns", "k") is None


def test_geo_region_model_defaults() -> None:
    region = GeoRegion.from_dict({"GeoRegionId": "225", "GeoRegionName": "Россия"})
    assert region.id == 225
    assert region.parent_id is None
    assert region.raw == {"GeoRegionId": "225", "GeoRegionName": "Россия"}
