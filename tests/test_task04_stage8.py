"""Тесты этапа 8 STAGE_05: permanent live-скрипт `scripts/smoke_campaign_live.py`.

Живой прогон выполняется вручную на креды владельца (D9), но сам скрипт —
обычный модуль, поэтому его сценарии проверяются mock-тестами: сетевые ответы
подменяются через `responses`, реальных запросов к Директу не происходит
(AGENTS.md §5).

Проверяется именно тот контракт, который важен на живом прогоне:
- сценарий без обязательных аргументов падает понятной ошибкой, а не
  создаёт половину сущностей;
- гео-проверка действительно ловит нарушение исключений;
- отчёт содержит этап ошибки и код возврата ненулевой при провале.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import responses

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import smoke_campaign_live as smoke  # noqa: E402
from yandex_direct_api_client import YandexDirectClient  # noqa: E402

V5 = "https://api.direct.yandex.com/json/v5"
V501 = "https://api.direct.yandex.com/json/v501"
CLIENTS_URL = f"{V5}/clients/"
DICTIONARIES_URL_V5 = f"{V5}/dictionaries/"
DICTIONARIES_URL_V501 = f"{V501}/dictionaries/"
CAMPAIGNS_URL = f"{V5}/campaigns/"

def _geo_payload() -> Dict[str, Any]:
    """Справочник регионов РФ в формате API v501 (ключи `GeoRegionId`/`GeoRegionName`/`GeoRegionType`/`ParentId`)."""
    regions: List[Dict[str, Any]] = [
        {"GeoRegionId": 225, "GeoRegionName": "Россия", "GeoRegionType": "Country", "ParentId": 1},
    ]
    for name in (
        "Москва",
        "Московская область",
        "Санкт-Петербург",
        "Ленинградская область",
    ):
        regions.append(
            {
                "GeoRegionId": 100 + len(regions),
                "GeoRegionName": name,
                "GeoRegionType": "City" if "Москва" in name or "Санкт-Петербург" in name else "Region",
                "ParentId": 225,
            }
        )
    for name in smoke.PROBE_REGIONS:
        regions.append(
            {
                "GeoRegionId": 200 + len(regions),
                "GeoRegionName": name,
                "GeoRegionType": "Region",
                "ParentId": 225,
            }
        )
    for index in range(1, 81):
        regions.append(
            {
                "GeoRegionId": 1000 + index,
                "GeoRegionName": f"Область {index}",
                "GeoRegionType": "Region",
                "ParentId": 225,
            }
        )
    return {"result": {"GeoRegions": regions}}


#: Ответ `dictionaries/getGeoRegions` (v501) для сценария гео.
GEO_REGIONS = _geo_payload()


def _client(cache_dir: Optional[Path] = None) -> YandexDirectClient:
    """Клиент с тестовыми настройками."""
    from yandex_direct_api_client.cache import JsonCache

    return YandexDirectClient(
        token="t",
        rate_limit_rps=1000.0,
        max_retries=1,
        cache=JsonCache(cache_dir=cache_dir) if cache_dir else None,
    )


def _args(**kwargs: Any) -> argparse.Namespace:
    """Собрать Namespace с параметрами сценариев по умолчанию."""
    base: Dict[str, Any] = {
        "scenario": "all",
        "budget": 1.0,
        "href": "https://example.com",
        "creative_id": None,
        "image": [],
        "campaign_id": None,
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


def _mock_clients() -> None:
    """Подменить ответ `clients/get`."""
    responses.add(
        responses.POST,
        CLIENTS_URL,
        json={
            "result": {
                "Clients": [{"ClientInfo": "owner", "Restrictions": []}]
            }
        },
    )


# ---------------- регистрация сценариев ----------------


def test_scenarios_registry_covers_spec() -> None:
    """Все сценарии §9.4 зарегистрированы и идут в логическом порядке."""
    assert list(smoke.SCENARIOS) == ["S-01", "S-02", "S-03", "S-04", "S-05"]


def test_test_name_marks_entities_as_smoke() -> None:
    """Имена сущностей содержат маркер теста и метку времени."""
    name = smoke._test_name("кампания")
    assert name.startswith(smoke.NAME_PREFIX)
    assert "кампания" in name


def test_probe_regions_exclude_moscow_and_spb() -> None:
    """Пять проверочных регионов — вне МСК/СПб/ЛО/МО (вопрос бизнеса)."""
    lowered = [region.lower() for region in smoke.PROBE_REGIONS]
    assert len(smoke.PROBE_REGIONS) == 5
    for forbidden in ("москва", "санкт-петербург", "ленинградская"):
        assert not any(forbidden in region for region in lowered)


# ---------------- S-01 ----------------


@responses.activate
def test_scenario_client_reports_limits(tmp_path: Path) -> None:
    """S-01 читает лимиты клиента и справочник регионов."""
    _mock_clients()
    responses.add(responses.POST, CAMPAIGNS_URL, json={"result": {"Campaigns": []}})
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=GEO_REGIONS)
    responses.add(responses.POST, DICTIONARIES_URL_V501, json=GEO_REGIONS)
    with _client(tmp_path / "cache") as client:
        smoke.scenario_client(client, _args())


@responses.activate
def test_scenario_client_fails_without_regions(tmp_path: Path) -> None:
    """Пустой справочник регионов — провал сценария, а не тихий успех."""
    _mock_clients()
    responses.add(responses.POST, CAMPAIGNS_URL, json={"result": {"Campaigns": []}})
    responses.add(responses.POST, DICTIONARIES_URL_V501, json={"result": {"GeoRegions": []}})
    with _client(tmp_path / "cache") as client:
        with pytest.raises(smoke.SmokeError, match="S-01"):
            smoke.scenario_client(client, _args())


# ---------------- S-02 ----------------


@responses.activate
def test_scenario_geo_resolves_outside_capitals(tmp_path: Path) -> None:
    """S-02 резолвит и пять регионов, и «всю РФ кроме четырёх»."""
    for _ in range(6):
        responses.add(responses.POST, DICTIONARIES_URL_V501, json=GEO_REGIONS)
    with _client(tmp_path / "cache") as client:
        smoke.scenario_geo(client, _args())


@responses.activate
def test_scenario_geo_detects_excluded_region(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если исключённый регион попал в результат — сценарий падает."""

    def fake_resolve(self: Any, dictionaries: Any) -> List[int]:
        """Вернуть список, где «исключённый» регион остался."""
        if self.include:
            return [1, 5]
        return [1, 5, 6]

    monkeypatch.setattr(smoke.RegionSelector, "resolve", fake_resolve)
    # Мокаем dictionaries.geo_regions для _resolve_excluded_region_ids
    responses.add(
        responses.POST,
        "https://api.direct.yandex.com/json/v501/dictionaries/",
        json={"result": {"GeoRegions": [{"GeoRegionId": 1, "GeoRegionName": "Москва", "GeoRegionType": "City", "ParentId": 225}]}},
    )
    with _client(tmp_path / "cache") as client:
        with pytest.raises(smoke.SmokeError, match="исключённые регионы"):
            smoke.scenario_geo(client, _args())


# ---------------- S-03 / S-04: обязательные аргументы ----------------


def test_scenario_rsya_requires_creative_id() -> None:
    """Без готового креатива сценарий РСЯ не идёт в сеть (D11)."""
    with pytest.raises(smoke.SmokeError, match="CreativeId"):
        smoke.scenario_rsya(_client(), _args())


def test_scenario_epk_requires_image() -> None:
    """Без изображения сценарий ЕПК не идёт в сеть."""
    with pytest.raises(smoke.SmokeError, match="изображение"):
        smoke.scenario_epk(_client(), _args())


def test_scenario_report_requires_campaign_id() -> None:
    """Отчёт без ID кампании не выполняется."""
    with pytest.raises(smoke.SmokeError, match="--campaign-id"):
        smoke.scenario_report(_client(), _args())


# ---------------- прогон и отчёт ----------------


def test_run_reports_failure_per_scenario(tmp_path: Path) -> None:
    """Провал одного сценария не отменяет остальные и попадает в отчёт."""
    calls: List[str] = []
    originals = dict(smoke.SCENARIOS)

    def ok_scenario(client: Any, args: Any) -> None:
        """Успешный сценарий-заглушка."""
        calls.append("ok")

    def failing_scenario(client: Any, args: Any) -> None:
        """Сценарий, всегда падающий."""
        calls.append("fail")
        raise smoke.SmokeError("S-02", "ожидаемый провал")

    smoke.SCENARIOS.update({"S-01": ok_scenario, "S-02": failing_scenario})
    try:
        with _client(tmp_path / "cache") as client:
            assert smoke.run(client, _args(scenario="S-01"))[0]["ok"] is True
            single = smoke.run(client, _args(scenario="S-02"))
            everything = smoke.run(client, _args(scenario="all"))
    finally:
        smoke.SCENARIOS.clear()
        smoke.SCENARIOS.update(originals)

    assert single[0]["ok"] is False
    assert calls.count("ok") == 2
    by_name = {item["scenario"]: item for item in everything}
    assert by_name["S-01"]["ok"] is True
    assert by_name["S-02"]["ok"] is False
    assert "S-02" in by_name["S-02"]["detail"]


def test_main_returns_one_without_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Без токена CLI возвращает 1 и не делает запросов."""
    monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
    monkeypatch.setattr(
        YandexDirectClient,
        "__init__",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            __import__(
                "yandex_direct_api_client.exceptions", fromlist=["ValidationError"]
            ).ValidationError("нет токена")
        ),
    )
    assert smoke.main(["--scenario", "S-01"]) == 1


def test_cli_parses_scenario_and_budget() -> None:
    """Парсер принимает сценарий, бюджет, креатив и изображения."""
    args = smoke._build_parser().parse_args(
        [
            "--scenario",
            "S-04",
            "--budget",
            "3",
            "--creative-id",
            "77",
            "--image",
            "a.png",
            "--image",
            "b.png",
            "--campaign-id",
            "5",
        ]
    )
    assert args.scenario == "S-04"
    assert args.budget == 3.0
    assert args.creative_id == 77
    assert args.image == ["a.png", "b.png"]
    assert args.campaign_id == 5


def test_cli_rejects_unknown_scenario() -> None:
    """Неизвестный сценарий отвергается argparse."""
    with pytest.raises(SystemExit):
        smoke._build_parser().parse_args(["--scenario", "S-99"])


# ---------------- безопасность ----------------


def test_script_never_prints_token_source() -> None:
    """Скрипт не содержит печати токена (D9, AGENTS.md §7)."""
    source = Path(smoke.__file__).read_text(encoding="utf-8")
    assert "access_token" not in source
    assert "print(" not in source


def test_scenarios_use_draft_and_no_serve() -> None:
    """S-03 и S-04 не включают модерацию и показы (DRAFT-контур)."""
    source = Path(smoke.__file__).read_text(encoding="utf-8")
    assert "moderate=False" in source
    assert "serve=False" in source


def test_cleanup_runs_with_confirm() -> None:
    """Cleanup всегда вызывается с confirm=True — кампании удаляются."""
    source = Path(smoke.__file__).read_text(encoding="utf-8")
    assert source.count("rollback(client, partial, confirm=True)") == 2


def test_smoke_script_uses_v501_for_unified() -> None:
    """ЕПК-сценарий маршрутизирует чтение через v501."""
    source = source_of_module()
    assert "get_unified" in source
    assert "api_version=\"v501\"" not in source


def source_of_module() -> str:
    """Вернуть исходный код модуля скрипта.

    :return: текст файла скрипта.
    """
    return Path(smoke.__file__).read_text(encoding="utf-8")


def test_script_builds_no_raw_json() -> None:
    """Скрипт не строит сырые JSON-тела вручную (используются модели SDK)."""
    assert "json.dumps" not in source_of_module()
