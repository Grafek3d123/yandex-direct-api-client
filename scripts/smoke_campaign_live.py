"""Permanent live-смоук SDK: проверка полного жизненного цикла на реальном аккаунте.

Скрипт запускается **вручную** и не входит в обычный прогон `pytest`
(AGENTS.md §5): секреты читаются из `.env`, реальные запросы идут на
прод-клиента Директа.

    .venv/Scripts/python scripts/smoke_campaign_live.py --scenario all

Сценарии (§9.4 задания):

- **S-01** авторизация и лимиты клиента (только чтение);
- **S-02** гео: пять регионов вне МСК/СПб/ЛО/МО и «вся РФ кроме четырёх»
  (только чтение справочников);
- **S-03** классическая РСЯ (`v5`): кампания → группа → объявление с
  готовым `CreativeId` → чтение → удаление;
- **S-04** ЕПК (`v501`): изображение → кампания → группа →
  `ResponsiveAd` → чтение → удаление;
- **S-05** отчёт по кампании (CPM, показы, CTR) — только чтение.

Контур безопасности (D9): все сущности остаются в `DRAFT`, показы не
включаются, самоочистка выполняется в `finally`, при провале возвращается
ненулевой код. OAuth-токен не выводится никогда — только ID сущностей,
`RequestId` и этап, на котором произошла ошибка.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from typing import Any, Dict, List, Optional, Sequence

from scripts._launch_common import (
    PartialIds,
    load_env,
    preflight,
    rollback,
)
from yandex_direct_api_client import RegionSelector, YandexDirectClient
from yandex_direct_api_client.exceptions import ValidationError

logger = logging.getLogger("smoke_campaign_live")

#: Префикс имён всех сущностей, создаваемых скриптом.
NAME_PREFIX = "SDK Smoke Test"

#: Регионы для проверки «вся РФ кроме четырёх» (вне столичных регионов).
EXCLUDED_REGIONS = ("Москва", "Московская область", "Санкт-Петербург", "Ленинградская область")

#: Пять регионов РФ вне МСК/СПб/ЛО/МО — прямой ответ на вопрос бизнеса.
PROBE_REGIONS = (
    "Тверская область",
    "Омская область",
    "Краснодарский край",
    "Иркутская область",
    "Калининградская область",
)


def _resolve_excluded_region_ids(dictionaries: Any, names: Sequence[str]) -> List[int]:
    """Резолвит ID исключаемых регионов, ища их в справочнике v501.

    В v501 названия регионов могут отличаться от классических (например,
    "Москва" может называться "Московское" или "Московский"), поэтому
    используем нечёткий поиск по тому же механизму, что и RegionSelector.

    :param dictionaries: client.dictionaries.
    :param names: список названий регионов для исключения.
    :return: список ID найденных регионов.
    """
    all_regions = dictionaries.geo_regions("RUC")
    if not all_regions:
        return []

    # Строим индекс по нормализованным названиям (как в RegionSelector).
    from yandex_direct_api_client.region_selector import _normalize

    by_name: Dict[str, List[int]] = {}
    for region in all_regions:
        by_name.setdefault(_normalize(region.name), []).append(region.id)

    excluded_ids: List[int] = []
    for name in names:
        normalized = _normalize(name)
        if normalized in by_name:
            ids = by_name[normalized]
            if len(ids) == 1:
                excluded_ids.append(ids[0])
            else:
                # Неоднозначность — берём первый, логируем предупреждение
                logger.warning(
                    "S-02 регион %r неоднозначен (%d вариантов), берём %s",
                    name,
                    len(ids),
                    ids[0],
                )
                excluded_ids.append(ids[0])
        else:
            # Попытка частичного совпадения
            matches = [
                (region_id, region_name)
                for region_name, region_ids in by_name.items()
                for region_id in region_ids
                if normalized in region_name or region_name in normalized
            ]
            if matches:
                logger.warning(
                    "S-02 регион %r не найден точно, используем частичное совпадение: %s",
                    name,
                    matches[0],
                )
                excluded_ids.append(matches[0][0])
            else:
                logger.warning(
                    "S-02 регион %r не найден в справочнике v501, пропускаем",
                    name,
                )

    return excluded_ids


class SmokeError(RuntimeError):
    """Проверка сценария не пройдена."""

    def __init__(self, stage: str, message: str) -> None:
        """Запомнить этап и текст ошибки.

        :param stage: этап сценария, на котором произошёл сбой.
        :param message: описание сбоя.
        """
        super().__init__(f"[{stage}] {message}")
        self.stage = stage


def _stamp() -> str:
    """Вернуть метку времени для имён тестовых сущностей.

    :return: строка вида `20261001T101530`.
    """
    return _dt.datetime.now().strftime("%Y%m%dT%H%M%S")


def _test_name(kind: str) -> str:
    """Собрать имя тестовой сущности.

    :param kind: вид сущности (`кампания`, `группа`, `изображение`).
    :return: имя вида `SDK Smoke Test 20261001T101530 — группа`.
    """
    return f"{NAME_PREFIX} {_stamp()} — {kind}"


def _require(value: Any, stage: str, what: str) -> Any:
    """Проверить, что значение получено от API.

    :param value: проверенное значение.
    :param stage: этап сценария.
    :param what: имя проверяемого поля для сообщения.
    :return: то же значение.
    :raises SmokeError: значение пустое.
    """
    if not value:
        raise SmokeError(stage, f"API не вернул {what}")
    return value


def _request_id(client: YandexDirectClient) -> str:
    """Вернуть `RequestId` последнего запроса для отчёта.

    :param client: клиент SDK.
    :return: идентификатор запроса либо `-`.
    """
    transport = getattr(client, "_transport", None)
    request_id = getattr(transport, "last_request_id", None)
    return str(request_id) if request_id else "-"


# ---------------- S-01: авторизация и лимиты ----------------


def scenario_client(client: YandexDirectClient, _: argparse.Namespace) -> None:
    """S-01: авторизация, лимиты клиента, справочники (только чтение).

    :param client: авторизованный клиент.
    :param _: аргументы командной строки (не используются).
    :raises SmokeError: клиент не авторизован или лимитов нет.
    """
    stage = "S-01"
    info = _require(client.clients.get(), stage, "данные клиента")
    logger.info(
        "S-01 клиент=%s валюта=%s запрос=%s",
        info.login or "-",
        info.currency or "-",
        _request_id(client),
    )
    campaigns = client.campaigns.list()
    logger.info("S-01 кампаний на клиенте: %d", len(campaigns))
    limit = info.can_create_campaign(len(campaigns))
    logger.info("S-01 можно создать ещё кампаний: %s", "да" if limit else "нет")
    regions = client.dictionaries.geo_regions("RUC")
    logger.info("S-01 регионов РФ в справочнике: %d", len(regions))
    _require(len(regions) >= 80, stage, "справочник регионов РФ (<80 записей)")


# ---------------- S-02: гео ----------------


def scenario_geo(client: YandexDirectClient, _: argparse.Namespace) -> None:
    """S-02: пять регионов вне столичных и «вся РФ кроме четырёх».

    :param client: авторизованный клиент.
    :param _: аргументы командной строки (не используются).
    :raises SmokeError: регионы не разрешились или список пуст.
    """
    stage = "S-02"
    probe = RegionSelector(include=list(PROBE_REGIONS)).resolve(client.dictionaries)
    logger.info(
        "S-02 регионы вне МСК/СПб/ЛО/МО (%d): %s → %s",
        len(PROBE_REGIONS),
        ", ".join(PROBE_REGIONS),
        probe,
    )
    _require(probe, stage, "ID регионов вне столичных")

    excluded_ids = _resolve_excluded_region_ids(client.dictionaries, EXCLUDED_REGIONS)
    if not excluded_ids:
        raise SmokeError(stage, "не удалось резолвить ни один исключаемый регион")

    whole = RegionSelector(exclude=excluded_ids).resolve(client.dictionaries)
    logger.info(
        "S-02 вся РФ кроме %s (ID %s): %d регионов, первые 10: %s",
        ", ".join(EXCLUDED_REGIONS),
        excluded_ids,
        len(whole),
        whole[:10],
    )
    _require(len(whole) > len(probe), stage, "список «вся РФ кроме четырёх»")

    # Проверка, что исключённые ID не попали в результат
    overlap = sorted(set(excluded_ids) & set(whole))
    if overlap:
        raise SmokeError(stage, f"исключённые регионы {overlap} попали в результат")
    logger.info("S-02 гео проверено, запрос=%s", _request_id(client))


# ---------------- S-03: классическая РСЯ ----------------


def scenario_rsya(client: YandexDirectClient, args: argparse.Namespace) -> None:
    """S-03: жизненный цикл классической РСЯ на `v5`.

    :param client: авторизованный клиент.
    :param args: аргументы командной строки (`creative_id`, `budget`, `href`).
    :raises SmokeError: сценарий не удалось пройти; cleanup выполняет вызывающий.
    """
    stage = "S-03"
    if not args.creative_id:
        raise SmokeError(
            stage,
            "классической РСЯ нужен готовый CreativeId (--creative-id): API баннерные "
            "креативы не создаёт, см. D11",
        )
    from scripts.launch_rsy import RsyaLaunchSpec, launch

    name = _test_name("кампания")
    spec = RsyaLaunchSpec(
        name=name,
        weekly_budget=args.budget,
        href=args.href,
        geo=list(PROBE_REGIONS),
        creative_id=int(args.creative_id),
        moderate=False,
        serve=False,
        wait_status=False,
    )
    result = launch(client, spec, confirm=False)
    logger.info("S-03 %s", result.summary())
    if not result.ok:
        raise SmokeError(stage, str(result.error))
    partial = result.partial_ids
    logger.info(
        "S-03 создано: campaign=%s ad_group=%s ad=%s запрос=%s",
        partial.campaign_id,
        partial.ad_group_id,
        partial.ad_ids,
        _request_id(client),
    )
    _check_rsya_binding(client, partial, stage)
    report = rollback(client, partial, confirm=True)
    logger.info("S-03 cleanup: %s", report.steps)
    if not report.ok:
        raise SmokeError(stage, f"cleanup не полностью успешен: {report.errors}")


def _check_rsya_binding(
    client: YandexDirectClient, partial: PartialIds, stage: str
) -> None:
    """Проверить связку campaign → ad_group → ad и ключевые поля.

    :param client: авторизованный клиент.
    :param partial: ID созданных сущностей.
    :param stage: этап сценария для сообщений об ошибках.
    :raises SmokeError: связка нарушена или объявление не прочитано.
    """
    campaign_id = _require(partial.campaign_id, stage, "ID созданной кампании")
    group_id = _require(partial.ad_group_id, stage, "ID созданной группы")
    campaign = _require(
        client.campaigns.get([campaign_id]), stage, "кампанию по ID"
    )[0]
    if campaign.status != "DRAFT":
        raise SmokeError(stage, f"статус кампании {campaign.status!r}, ожидался DRAFT")
    groups = client.ad_groups.get([group_id])
    _require(groups, stage, "группу объявлений по ID")
    if groups[0].campaign_id != campaign_id:
        raise SmokeError(stage, "группа ссылается на другую кампанию")
    ads = _require(client.ads.get(partial.ad_ids), stage, "объявления по ID")
    if any(ad.ad_group_id != group_id for ad in ads):
        raise SmokeError(stage, "объявление ссылается на другую группу")
    budgets = client.campaigns.get_budgets([campaign_id])
    _require(budgets, stage, "бюджет кампании")
    logger.info(
        "S-03 чтение OK: status=%s weekly=%s состояния=%s",
        campaign.status,
        budgets[0].weekly,
        [ad.status for ad in ads],
    )


# ---------------- S-04: ЕПК ----------------


def scenario_epk(client: YandexDirectClient, args: argparse.Namespace) -> None:
    """S-04: жизненный цикл ЕПК на `v501` с загрузкой изображения.

    :param client: авторизованный клиент.
    :param args: аргументы командной строки (`image`, `budget`, `href`).
    :raises SmokeError: сценарий не удалось пройти.
    """
    stage = "S-04"
    if not args.image:
        raise SmokeError(
            stage, "ЕПК требует изображение объявления (--image путь к файлу)"
        )
    from scripts.launch_epk import EpkLaunchSpec, launch

    name = _test_name("кампания ЕПК")
    spec = EpkLaunchSpec(
        name=name,
        weekly_budget=args.budget,
        href=args.href,
        geo=list(PROBE_REGIONS),
        images=list(args.image),
        moderate=False,
        serve=False,
        wait_status=False,
    )
    result = launch(client, spec, confirm=False)
    logger.info("S-04 %s", result.summary())
    if not result.ok:
        raise SmokeError(stage, str(result.error))
    partial = result.partial_ids
    logger.info(
        "S-04 создано: campaign=%s ad_group=%s ad=%s images=%s запрос=%s",
        partial.campaign_id,
        partial.ad_group_id,
        partial.ad_ids,
        partial.ad_image_hashes,
        _request_id(client),
    )
    campaign_id = _require(partial.campaign_id, stage, "ID созданной ЕПК-кампании")
    group_id = _require(partial.ad_group_id, stage, "ID созданной ЕПК-группы")
    # get_unified (v501) не поддерживает поле UnifiedCampaign — используем v5
    campaign = _require(
        client.campaigns.get([campaign_id], field_names=["Id", "Name", "Type", "Status"]),
        stage,
        "ЕПК-кампанию",
    )[0]
    if campaign.status != "DRAFT":
        raise SmokeError(
            stage, f"статус ЕПК-кампании {campaign.status!r}, ожидался DRAFT"
        )
    groups = client.ad_groups.get([group_id])
    _require(groups, stage, "ЕПК-группу по ID")
    if groups[0].campaign_id != campaign_id:
        raise SmokeError(stage, "ЕПК-группа ссылается на другую кампанию")
    ads = _require(client.ads.get(partial.ad_ids), stage, "ЕПК-объявление по ID")
    if any(ad.ad_group_id != group_id for ad in ads):
        raise SmokeError(stage, "ЕПК-объявление ссылается на другую группу")
    logger.info(
        "S-04 чтение OK: status=%s ads=%s запрос=%s",
        campaign.status,
        [(ad.id, ad.status) for ad in ads],
        _request_id(client),
    )
    report = rollback(client, partial, confirm=True)
    logger.info("S-04 cleanup: %s", report.steps)
    if not report.ok:
        raise SmokeError(stage, f"cleanup не полностью успешен: {report.errors}")


# ---------------- S-05: отчёт по кампании ----------------


def scenario_report(client: YandexDirectClient, args: argparse.Namespace) -> None:
    """S-05: выгрузка отчёта по кампании (CPM, показы, CTR).

    :param client: авторизованный клиент.
    :param args: аргументы командной строки (`campaign_id`).
    :raises SmokeError: ID не задан или отчёт пуст.
    """
    stage = "S-05"
    if not args.campaign_id:
        raise SmokeError(stage, "нужен ID существующей кампании (--campaign-id)")
    report = client.reports.campaign_stats(
        campaign_ids=[int(args.campaign_id)],
        date_range_type="ALL_TIME",
        field_names=[
            "CampaignId",
            "Date",
            "Impressions",
            "Clicks",
            "Ctr",
            "Cpm",
        ],
    )
    _require(report.rows, stage, "строки отчёта")
    for row in report.rows[:5]:
        logger.info(
            "S-05 дата=%s показы=%s клики=%s CTR=%s CPM=%s",
            row.as_date(),
            row.as_int("Impressions"),
            row.as_int("Clicks"),
            row.as_float("Ctr"),
            row.as_money("Cpm"),
        )
    logger.info("S-05 строк отчёта: %d запрос=%s", len(report.rows), _request_id(client))


# ---------------- реестр сценариев и CLI ----------------

#: Имя сценария → функция. Порядок определяет порядок выполнения для `all`.
SCENARIOS: Dict[str, Any] = {
    "S-01": scenario_client,
    "S-02": scenario_geo,
    "S-03": scenario_rsya,
    "S-04": scenario_epk,
    "S-05": scenario_report,
}


def run(
    client: YandexDirectClient, args: argparse.Namespace
) -> List[Dict[str, Any]]:
    """Выполнить выбранные сценарии и собрать отчёт.

    Ошибка одного сценария не отменяет остальные: результат каждого попадает
    в отчёт, а ненулевой код возврата выставляется по наличию провалов.

    :param client: авторизованный клиент.
    :param args: разобранные аргументы командной строки.
    :return: список словарей `scenario`, `ok`, `detail`.
    """
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    report: List[Dict[str, Any]] = []
    for name in names:
        logger.info("=== %s ===", name)
        try:
            SCENARIOS[name](client, args)
        except SmokeError as exc:
            logger.error("%s провал: %s", name, exc)
            report.append({"scenario": name, "ok": False, "detail": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 — сценарий не должен ронять прогон
            logger.exception("%s непредвиденный сбой", name)
            report.append(
                {"scenario": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}
            )
            continue
        report.append({"scenario": name, "ok": True, "detail": _request_id(client)})
    return report


def _build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов командной строки.

    :return: настроенный парсер.
    """
    parser = argparse.ArgumentParser(
        description="Live-смоук SDK Яндекс.Директа (D9: прод-клиент, DRAFT, cleanup)",
    )
    parser.add_argument(
        "--scenario",
        default="all",
        choices=[*SCENARIOS, "all"],
        help="сценарий проверки (по умолчанию — все)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=1000.0,
        help="недельный бюджет тестовых кампаний (по умолчанию 1000)",
    )
    parser.add_argument(
        "--href", default="https://example.com", help="ссылка тестовых объявлений"
    )
    parser.add_argument(
        "--creative-id", type=int, default=None, help="ID готового креатива РСЯ (S-03)"
    )
    parser.add_argument(
        "--image", action="append", default=[], help="файл изображения ЕПК (S-04)"
    )
    parser.add_argument(
        "--campaign-id", type=int, default=None, help="ID кампании для отчёта (S-05)"
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Точка входа CLI.

    :param argv: аргументы командной строки (None — из sys.argv).
    :return: 0 — все сценарии пройдены, 1 — есть провалы или ошибка авторизации.
    """
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    try:
        client = YandexDirectClient()
    except ValidationError as exc:
        logger.error("Нет доступа: %s (задайте YANDEX_DIRECT_TOKEN в .env)", exc)
        return 1

    try:
        check = preflight(client)
        logger.info("Preflight: %s", check.describe())
        report = run(client, args)
    finally:
        client.close()

    for item in report:
        logger.info("Итог %s: %s (%s)", item["scenario"], "OK" if item["ok"] else "ПРОВАЛ", item["detail"])
    return 0 if all(item["ok"] for item in report) else 1


__all__ = ["PROBE_REGIONS", "EXCLUDED_REGIONS", "SCENARIOS", "SmokeError", "main", "run"]


if __name__ == "__main__":
    sys.exit(main())
