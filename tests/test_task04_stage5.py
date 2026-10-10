"""Тесты слоя 5 STAGE_05: E2E-сборка запуска и компенсации (tasks/task04.md, §8).

Критерии приёмки слоя:

- `dry_run=True` — только валидация и план, **ноль** сетевых вызовов;
- happy path доходит до `MODERATION` для классической РСЯ (`v5`) и ЕПК (`v501`);
- сбой на шаге объявления даёт непустые `LaunchResult.partial_ids`, а
  `rollback(..., confirm=True)` реально откатывает созданное;
- повторный запуск с тем же файлом не грузит изображение второй раз
  (кэш по SHA-256 содержимого);
- валидация спецификации выполняется до сети.

Оркестрация лежит в `scripts/`, поэтому тесты импортируют её как модуль
(в pytest нет сетевых вызовов — всё замокано через `responses`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import responses

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._launch_common import (  # noqa: E402
    PartialIds,
    ReuseCache,
    RollbackReport,
    ensure_test_name,
    file_digest,
    rollback,
)
from scripts.launch_epk import EpkLaunchSpec  # noqa: E402
from scripts.launch_epk import launch as launch_epk
from scripts.launch_rsy import RsyaLaunchSpec  # noqa: E402
from scripts.launch_rsy import launch as launch_rsy
from yandex_direct_api_client import YandexDirectClient  # noqa: E402
from yandex_direct_api_client.exceptions import ValidationError  # noqa: E402

V5 = "https://api.direct.yandex.com/json/v5"
V501 = "https://api.direct.yandex.com/json/v501"
CLIENTS_URL = f"{V5}/clients/"
CAMPAIGNS_URL = f"{V5}/campaigns/"
CAMPAIGNS_501_URL = f"{V501}/campaigns/"
ADGROUPS_URL = f"{V5}/adgroups/"
ADGROUPS_501_URL = f"{V501}/adgroups/"
ADS_URL = f"{V5}/ads/"
ADS_501_URL = f"{V501}/ads/"
ADIMAGES_URL = f"{V5}/adimages/"
CREATIVES_URL = f"{V5}/creatives/"
DICTIONARIES_URL = f"{V5}/dictionaries/"

#: Справочник регионов: Москва, МО и ещё несколько.
REGIONS: Dict[str, Any] = {
    "result": {
        "GeoRegions": [
            {"GeoRegionId": 225, "GeoRegionName": "Россия", "CountryRegion": "RUC"},
            {"GeoRegionId": 213, "GeoRegionName": "Москва", "CountryRegion": "RUC"},
            {
                "GeoRegionId": 214,
                "GeoRegionName": "Московская область",
                "CountryRegion": "RUC",
            },
            {"GeoRegionId": 2, "GeoRegionName": "Санкт-Петербург", "CountryRegion": "RUC"},
        ]
    }
}

#: Ответ `clients/get` без ограничений.
CLIENT: Dict[str, Any] = {
    "result": {
        "Id": 123,
        "Login": "test-client",
        "Name": "Тестовый клиент",
        "Currency": "RUB",
        "TimeZone": "Europe/Moscow",
        "Agency": "no",
        "Restrictions": {
            "CAMPAIGNS_TOTAL_PER_CLIENT": 100,
            "CAMPAIGNS_UNARCHIVED_PER_CLIENT": 50,
        },
    }
}

#: Ответ `campaigns/get` для списка кампаний аккаунта.
CAMPAIGNS: Dict[str, Any] = {"result": {"Campaigns": []}}

#: Картинный креатив, как его отдаёт `creatives/get`.
CREATIVES: Dict[str, Any] = {
    "result": {
        "Creatives": [
            {
                "Id": 777,
                "Type": "IMAGE_CREATIVE",
                "Name": "E2E TEST креатив",
                "PreviewUrl": "https://example.com/preview.png",
            }
        ]
    }
}

#: Ответ `adimages/add`.
ADIMAGE_ADD: Dict[str, Any] = {
    "result": {"AddResults": [{"AdImageHash": "hash-image-1"}]}
}


def _body_of(call: Any) -> Dict[str, Any]:
    """Разобрать JSON-тело исходящего запроса."""
    body: Dict[str, Any] = json.loads(call.request.body)
    return body


def _mark() -> int:
    """Отметка текущего числа вызовов — начало среза.

    `responses.calls` — общий список за сессию pytest, поэтому счётчики
    сравниваются по срезу «от отметки», а не по абсолютным индексам.

    :return: число выполненных к этому моменту вызовов.
    """
    return len(responses.calls)


def _url_of(call: Any) -> str:
    """URL вызова как строка (в `responses` он может быть `None`).

    :param call: вызов `responses`.
    :return: URL запроса либо пустая строка.
    """
    return str(call.request.url or "")


def _methods(mark: int = 0) -> List[str]:
    """Собрать список вызовов в формате `method сервиса`.

    :param mark: отметка, с которой начинается срез.
    :return: список строк `ads/add` и подобных в порядке вызовов.
    """
    calls: List[str] = []
    for call in responses.calls[mark:]:
        payload = _body_of(call)
        service = _url_of(call).split("/json/")[-1].split("/", 1)[-1]
        calls.append(f"{payload['method']} {service}")
    return calls


def _body_since(mark: int, offset: int) -> Dict[str, Any]:
    """Тело запроса по смещению относительно отметки.

    :param mark: отметка начала среза.
    :param offset: смещение внутри среза.
    :return: разобранное JSON-тело запроса.
    """
    body: Dict[str, Any] = _body_of(responses.calls[mark + offset])
    return body


def _ok(result_key: str, ids: List[int]) -> Dict[str, Any]:
    """Собрать успешный ответ batch-операции.

    :param result_key: имя ключа результата (`AddResults` и подобные).
    :param ids: ID созданных объектов.
    :return: тело ответа API.
    """
    return {"result": {result_key: [{"Id": i} for i in ids]}}


def _client() -> YandexDirectClient:
    """Клиент с тестовыми настройками."""
    return YandexDirectClient(
        token="test_token",
        rate_limit_rps=1000.0,
        max_retries=1,
    )


@pytest.fixture(autouse=True)
def isolated_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Изолировать дисковые кэши (справочники и переиспользование)."""
    monkeypatch.setenv("YANDEX_DIRECT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("YANDEX_DIRECT_LAUNCH_CACHE_DIR", str(tmp_path / "launch"))


@pytest.fixture
def image_file(tmp_path: Path) -> Path:
    """Минимальный файл изображения для загрузки."""
    path = tmp_path / "banner.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"e2e-test-image")
    return path


def _mock_preflight(rsps: Any, *, geo: bool = True) -> None:
    """Замокать предварительные вызовы: клиент, список кампаний, гео."""
    rsps.add(responses.POST, CLIENTS_URL, json=CLIENT)
    rsps.add(responses.POST, CAMPAIGNS_URL, json=CAMPAIGNS)
    if geo:
        rsps.add(responses.POST, DICTIONARIES_URL, json=REGIONS)


def _rsya_spec(**kwargs: Any) -> RsyaLaunchSpec:
    """Спецификация запуска классической РСЯ по умолчанию."""
    params: Dict[str, Any] = {
        "name": "E2E TEST РСЯ",
        "weekly_budget": 1,
        "href": "https://example.com",
        "creative_id": 777,
    }
    params.update(kwargs)
    return RsyaLaunchSpec(**params)


def _epk_spec(image: Path, **kwargs: Any) -> EpkLaunchSpec:
    """Спецификация запуска ЕПК по умолчанию."""
    params: Dict[str, Any] = {
        "name": "E2E TEST ЕПК",
        "weekly_budget": 1,
        "href": "https://example.com",
        "images": [str(image)],
    }
    params.update(kwargs)
    return EpkLaunchSpec(**params)


# ---------------- dry_run: ноль сетевых вызовов ----------------


@responses.activate
def test_dry_run_rsy_makes_no_requests() -> None:
    """AC: `dry_run=True` у РСЯ — ноль сетевых вызовов, но есть план."""
    mark = _mark()
    with _client() as client:
        result = launch_rsy(client, _rsya_spec(), dry_run=True)
    assert result.dry_run is True
    assert result.ok is True
    assert _mark() == mark
    assert result.plan
    assert result.partial_ids.is_empty
    assert result.step("campaign").status == "skipped"


@responses.activate
def test_dry_run_epk_makes_no_requests(image_file: Path) -> None:
    """AC: `dry_run=True` у ЕПК — ноль сетевых вызовов."""
    mark = _mark()
    with _client() as client:
        result = launch_epk(client, _epk_spec(image_file), dry_run=True)
    assert result.dry_run is True
    assert _mark() == mark
    assert result.partial_ids.is_empty
    assert result.step("ad_images").status == "skipped"


@responses.activate
def test_dry_run_does_not_need_image_upload(image_file: Path) -> None:
    """`dry_run` не обращается к `adimages/add`, даже если файл есть."""
    with _client() as client:
        launch_epk(client, _epk_spec(image_file), dry_run=True)
    assert not any("adimages" in _url_of(call) for call in responses.calls)


# ---------------- валидация до сети ----------------


@responses.activate
def test_rsy_requires_creative() -> None:
    """Без креатива запуск падает до сети (D11)."""
    spec = _rsya_spec(creative_id=None)
    mark = _mark()
    with _client() as client:
        result = launch_rsy(client, spec)
    assert result.ok is False
    assert _mark() == mark
    assert "креатив" in (result.error or "").lower()


@responses.activate
def test_epk_requires_image() -> None:
    """ЕПК без изображений падает до сети."""
    spec = EpkLaunchSpec(
        name="E2E TEST ЕПК", weekly_budget=1, href="https://example.com"
    )
    mark = _mark()
    with _client() as client:
        result = launch_epk(client, spec)
    assert result.ok is False
    assert _mark() == mark


@responses.activate
def test_epk_requires_existing_file(tmp_path: Path) -> None:
    """Отсутствующий файл изображения отвергается без обращения к API."""
    spec = _epk_spec(tmp_path / "нет-такого.png")
    mark = _mark()
    with _client() as client:
        result = launch_epk(client, spec)
    assert result.ok is False
    assert _mark() == mark
    assert "не найден" in (result.error or "")


@responses.activate
def test_non_test_name_requires_confirm() -> None:
    """Имя реальной кампании требует явного `confirm=True`."""
    mark = _mark()
    with _client() as client:
        result = launch_rsy(client, _rsya_spec(name="Продажи — РСЯ"))
    assert result.ok is False
    assert _mark() == mark


def test_ensure_test_name_allows_explicit_confirm() -> None:
    """`confirm=True` снимает ограничение на имя."""
    ensure_test_name("Продажи", confirm=True)
    with pytest.raises(ValidationError):
        ensure_test_name("Продажи")


# ---------------- happy path ----------------


@responses.activate
def test_rsy_happy_path_reaches_moderation() -> None:
    """Классическая РСЯ: полный порядок шагов до статуса MODERATION."""
    _mock_preflight(responses)
    responses.add(responses.POST, CREATIVES_URL, json=CREATIVES)
    responses.add(responses.POST, CAMPAIGNS_URL, json=_ok("AddResults", [1001]))
    responses.add(responses.POST, ADGROUPS_URL, json=_ok("AddResults", [2001]))
    responses.add(responses.POST, ADS_URL, json=_ok("AddResults", [3001]))
    responses.add(
        responses.POST, ADS_URL, json={"result": {"ModerateResults": [{"Id": 3001}]}}
    )

    mark = _mark()
    with _client() as client:
        result = launch_rsy(client, _rsya_spec(creative_id=None, creative_name="E2E TEST креатив"))

    assert result.ok is True
    assert result.partial_ids.campaign_id == 1001
    assert result.partial_ids.ad_group_id == 2001
    assert result.partial_ids.ad_ids == [3001]
    assert result.partial_ids.creative_id == 777
    assert _methods(mark) == [
        "get clients/",
        "get campaigns/",
        "get dictionaries/",
        "get creatives/",
        "add campaigns/",
        "add adgroups/",
        "add ads/",
        "moderate ads/",
    ]
    ad_body = _body_since(mark, -2)["params"]["Ads"][0]
    assert ad_body["CpmBannerAdBuilderAd"]["Creative"]["CreativeId"] == 777


@responses.activate
def test_epk_happy_path_reaches_moderation(image_file: Path) -> None:
    """ЕПК: adimages → UnifiedCampaign → UnifiedAdGroup → ResponsiveAd."""
    _mock_preflight(responses)
    responses.add(responses.POST, ADIMAGES_URL, json=ADIMAGE_ADD)
    responses.add(responses.POST, CAMPAIGNS_501_URL, json=_ok("AddResults", [1101]))
    responses.add(responses.POST, ADGROUPS_501_URL, json=_ok("AddResults", [2101]))
    responses.add(responses.POST, ADS_501_URL, json=_ok("AddResults", [3101]))
    responses.add(
        responses.POST,
        ADS_501_URL,
        json={"result": {"ModerateResults": [{"Id": 3101, "Status": "MODERATION"}]}},
    )

    mark = _mark()
    with _client() as client:
        result = launch_epk(client, _epk_spec(image_file))

    assert result.ok is True
    assert result.partial_ids.ad_image_hashes == ["hash-image-1"]
    assert result.partial_ids.campaign_id == 1101
    assert result.partial_ids.ad_group_id == 2101
    assert result.partial_ids.ad_ids == [3101]
    assert result.ad_statuses == {3101: "MODERATION"}
    assert _methods(mark) == [
        "get clients/",
        "get campaigns/",
        "get dictionaries/",
        "add adimages/",
        "add campaigns/",
        "add adgroups/",
        "add ads/",
        "moderate ads/",
    ]
    ad_body = _body_since(mark, -2)["params"]["Ads"][0]
    assert ad_body["ResponsiveAd"]["AdImageHashes"] == ["hash-image-1"]


@responses.activate
def test_rsy_resume_and_poll() -> None:
    """`serve` и `wait_status` включают `resume` и опрос статуса."""
    _mock_preflight(responses)
    responses.add(responses.POST, CREATIVES_URL, json=CREATIVES)
    responses.add(responses.POST, CAMPAIGNS_URL, json=_ok("AddResults", [1001]))
    responses.add(responses.POST, ADGROUPS_URL, json=_ok("AddResults", [2001]))
    responses.add(responses.POST, ADS_URL, json=_ok("AddResults", [3001]))
    responses.add(
        responses.POST, ADS_URL, json={"result": {"ModerateResults": [{"Id": 3001}]}}
    )
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"ResumeResults": [{"Id": 3001, "IsResumed": True}]}},
    )
    responses.add(
        responses.POST,
        ADS_URL,
        json={"result": {"Ads": [{"Id": 3001, "Status": "MODERATED"}]}},
    )

    mark = _mark()
    with _client() as client:
        result = launch_rsy(
            client,
            _rsya_spec(creative_id=None, creative_name="E2E TEST креатив", serve=True, wait_status=True),
        )

    assert result.ok is True
    assert result.ad_statuses == {3001: "MODERATED"}
    assert _methods(mark)[-3:] == ["moderate ads/", "resume ads/", "get ads/"]


# ---------------- компенсация ----------------


def _fail_on_ads_create(rsps: Any) -> None:
    """Замокать ошибку элемента на шаге `ads/add`."""
    rsps.add(
        responses.POST,
        ADS_URL,
        json={
            "result": {
                "AddResults": [
                    {
                        "Id": 0,
                        "Errors": [
                            {
                                "Code": "ADGROUP_ID_UNKNOWN",
                                "Message": "Группа не найдена",
                                "Details": "группа удалена до создания объявления",
                            }
                        ],
                    }
                ]
            }
        },
    )


@responses.activate
def test_rsy_failure_gives_partial_ids_and_rollback_works() -> None:
    """Сбой на `ads/add`: `partial_ids` заполнены, `rollback` откатывает."""
    _mock_preflight(responses)
    responses.add(responses.POST, CREATIVES_URL, json=CREATIVES)
    responses.add(responses.POST, CAMPAIGNS_URL, json=_ok("AddResults", [1001]))
    responses.add(responses.POST, ADGROUPS_URL, json=_ok("AddResults", [2001]))
    _fail_on_ads_create(responses)
    responses.add(responses.POST, ADS_URL, json={"result": {"SuspendResults": []}})
    responses.add(responses.POST, CAMPAIGNS_URL, json={"result": {"SuspendResults": []}})
    responses.add(responses.POST, ADS_URL, json={"result": {"ArchiveResults": []}})
    responses.add(
        responses.POST, CAMPAIGNS_URL, json={"result": {"ArchiveResults": []}}
    )
    responses.add(responses.POST, CAMPAIGNS_URL, json={"result": {"DeleteResults": []}})

    mark = _mark()
    with _client() as client:
        result = launch_rsy(client, _rsya_spec(creative_id=None, creative_name="E2E TEST креатив"))
        assert result.ok is False
        assert result.partial_ids.campaign_id == 1001
        assert result.partial_ids.ad_group_id == 2001
        assert result.partial_ids.ad_ids == []
        assert not result.partial_ids.is_empty

        report = rollback(client, result.partial_ids, confirm=True)

    assert isinstance(report, RollbackReport)
    assert report.ok is True
    methods = _methods(mark)
    assert "suspend campaigns/" in methods
    assert "archive campaigns/" in methods
    assert "delete campaigns/" in methods


@responses.activate
def test_rollback_without_confirm_skips_delete() -> None:
    """Без `confirm=True` откат ограничивается архивированием."""
    _mock_preflight(responses)
    responses.add(responses.POST, CREATIVES_URL, json=CREATIVES)
    responses.add(responses.POST, CAMPAIGNS_URL, json=_ok("AddResults", [1001]))
    responses.add(responses.POST, ADGROUPS_URL, json=_ok("AddResults", [2001]))
    _fail_on_ads_create(responses)
    responses.add(responses.POST, CAMPAIGNS_URL, json={"result": {"SuspendResults": []}})
    responses.add(
        responses.POST, CAMPAIGNS_URL, json={"result": {"ArchiveResults": []}}
    )

    mark = _mark()
    with _client() as client:
        result = launch_rsy(client, _rsya_spec(creative_id=None, creative_name="E2E TEST креатив"))
        report = rollback(client, result.partial_ids)

    assert "delete campaigns/" not in _methods(mark)
    assert any("требуется confirm=True" in line for line in report.steps)


@responses.activate
def test_rollback_reports_errors_instead_of_raising(image_file: Path) -> None:
    """Ошибка компенсации попадает в отчёт, а не бросается наружу."""
    _mock_preflight(responses, geo=False)
    responses.add(
        responses.POST,
        CAMPAIGNS_501_URL,
        json={
            "result": {
                "SuspendResults": [
                    {"Id": 1101, "Errors": [{"Code": "X", "Message": "нельзя"}]}
                ]
            }
        },
    )

    with _client() as client:
        report = rollback(
            client,
            PartialIds(
                campaign_id=1101,
                ad_image_hashes=["hash-image-1"],
                unified=True,
            ),
            confirm=False,
        )
    assert report.ok is False
    assert any("suspend campaign" in message for message in report.errors)


@responses.activate
def test_rollback_on_empty_partial_does_nothing() -> None:
    """Пустой `partial_ids` — компенсация не делает ни одного вызова."""
    mark = _mark()
    with _client() as client:
        report = rollback(client, PartialIds())
    assert report.ok is True
    assert report.steps == ["нечего откатывать"]
    assert _mark() == mark


# ---------------- кэш по хэшу содержимого ----------------


@responses.activate
def test_epk_second_run_does_not_reupload_same_image(image_file: Path) -> None:
    """AC: повторный запуск с тем же файлом не грузит изображение снова."""
    spec = _epk_spec(image_file)
    first_moderate = {"result": {"ModerateResults": [{"Id": 3101, "Status": "MODERATION"}]}}

    _mock_preflight(responses)
    responses.add(responses.POST, ADIMAGES_URL, json=ADIMAGE_ADD)
    responses.add(responses.POST, CAMPAIGNS_501_URL, json=_ok("AddResults", [1101]))
    responses.add(responses.POST, ADGROUPS_501_URL, json=_ok("AddResults", [2101]))
    responses.add(responses.POST, ADS_501_URL, json=_ok("AddResults", [3101]))
    responses.add(responses.POST, ADS_501_URL, json=first_moderate)
    with _client() as client:
        first = launch_epk(client, spec)
    assert first.ok is True
    assert first.step("ad_images").status == "done"
    first_uploads = _count("add adimages/")
    assert first_uploads == 1

    _mock_preflight(responses)
    responses.add(responses.POST, CAMPAIGNS_501_URL, json=_ok("AddResults", [1102]))
    responses.add(responses.POST, ADGROUPS_501_URL, json=_ok("AddResults", [2102]))
    responses.add(responses.POST, ADS_501_URL, json=_ok("AddResults", [3102]))
    responses.add(
        responses.POST,
        ADS_501_URL,
        json={"result": {"ModerateResults": [{"Id": 3102, "Status": "MODERATION"}]}},
    )
    with _client() as client:
        second = launch_epk(client, _epk_spec(image_file))

    assert second.ok is True
    assert second.step("ad_images").status == "reused"
    assert _count("add adimages/") == first_uploads  # второй загрузки не было
    assert second.partial_ids.ad_image_hashes == ["hash-image-1"]
    assert second.partial_ids.ad_ids == [3102]


def _count(method: str, mark: int = 0) -> int:
    """Посчитать вызовы конкретного метода во всём прогоне.

    :param mark: отметка, с которой начинается срез.
    :param method: строка `метод сервиса/` (например, `add adimages/`).
    :return: количество совпадений.
    """
    return sum(1 for item in _methods(mark) if item == method)


def test_reuse_cache_roundtrip(tmp_path: Path) -> None:
    """Кэш переиспользования переживает перезапуск процесса."""
    directory = tmp_path / "cache"
    first = ReuseCache.load(prefix="epk", directory=str(directory))
    first.store("adimage:abc", "hash-1")
    assert first.hits == 0 and first.misses == 0

    second = ReuseCache.load(prefix="epk", directory=str(directory))
    assert second.lookup("adimage:abc") == "hash-1"
    assert second.hits == 1
    assert second.lookup("adimage:нет") is None
    assert second.misses == 1
    assert second.lookup_many(["adimage:нет", "adimage:abc"]) is None


def test_file_digest_depends_on_content(tmp_path: Path) -> None:
    """Ключ кэша зависит от содержимого, а не от имени файла."""
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    assert file_digest(first) == file_digest(second)
    second.write_bytes(b"other")
    assert file_digest(first) != file_digest(second)
    with pytest.raises(ValidationError):
        file_digest(tmp_path / "нет.png")


# ---------------- отчёт ----------------


@responses.activate
def test_launch_result_summary_and_succeeded(image_file: Path) -> None:
    """Отчёт содержит шаги, статусы и список созданного."""
    _mock_preflight(responses)
    responses.add(responses.POST, ADIMAGES_URL, json=ADIMAGE_ADD)
    responses.add(responses.POST, CAMPAIGNS_501_URL, json=_ok("AddResults", [1101]))
    responses.add(responses.POST, ADGROUPS_501_URL, json=_ok("AddResults", [2101]))
    responses.add(responses.POST, ADS_501_URL, json=_ok("AddResults", [3101]))
    responses.add(
        responses.POST,
        ADS_501_URL,
        json={"result": {"ModerateResults": [{"Id": 3101, "Status": "MODERATION"}]}},
    )
    with _client() as client:
        result = launch_epk(client, _epk_spec(image_file))

    summary = result.summary()
    assert result.succeeded() is True
    assert "ОК" not in summary
    assert "MODERATION" in summary
    assert "campaign=1101" in summary
    assert result.step("ad_group").detail == "ad_group_id=2101"


@responses.activate
def test_api_error_on_campaign_step_is_reported(image_file: Path) -> None:
    """Ошибка API на шаге кампании попадает в отчёт, а не наружу."""
    _mock_preflight(responses)
    responses.add(responses.POST, ADIMAGES_URL, json=ADIMAGE_ADD)
    responses.add(
        responses.POST,
        CAMPAIGNS_501_URL,
        json={"error": {"code": 60, "message": "нет доступа", "error": "no"}},
        status=200,
    )
    with _client() as client:
        result = launch_epk(client, _epk_spec(image_file))
    assert result.ok is False
    assert result.partial_ids.campaign_id is None
    assert result.partial_ids.ad_image_hashes == ["hash-image-1"]
    assert "campaign" in (result.error or "")

