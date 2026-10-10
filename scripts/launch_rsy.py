"""E2E-сборка запуска классической РСЯ (`CPM_BANNER_CAMPAIGN`, слой 5).

Сценарий 2А проходит путь «от нуля» так:

    справочники и лимиты → гео → кампания → группа → креатив →
    медийное объявление → модерация → показы → опциональный опрос статуса

Ключевое ограничение (D11): классическое медийное объявление создаётся как
`CpmBannerAdBuilderAd` со ссылкой на **готовый креатив** из конструктора
креативов — API баннерный креатив не создаёт. Поэтому на входе нужен
`creative_id` либо `creative_name` (имя ищется через `creatives/get`).
Полностью автоматический сценарий «картинка → объявление» реализован в
`scripts/launch_epk.py` (ЕПК, `v501`).

Оркестрация живёт вне пакета намеренно: `yandex_direct_api_client` остаётся
набором атомарных операций, порядок вызовов собирает скрипт.

Запуск вручную (живой аккаунт, всё в `DRAFT`, показы выключены), из корня
репозитория:

    .venv\\Scripts\\python.exe -m scripts.launch_rsy --dry-run \\
        --name "E2E TEST РСЯ" --creative-name "E2E TEST креатив" --budget 1
    .venv\\Scripts\\python.exe -m scripts.launch_rsy --name "E2E TEST РСЯ" \\
        --creative-name "E2E TEST креатив" --budget 1 \\
        --href https://example.com --rollback

Секреты читаются из `.env` и нигде не печатаются. Скрипт не создаёт
кампании реального бизнеса: имя должно выглядеть как тестовое либо требуется
`confirm=True` (см. `ensure_test_name`).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence

from scripts._launch_common import (
    LaunchResult,
    LaunchSpecBase,
    LaunchStep,
    PartialIds,
    ReuseCache,
    ensure_test_name,
    ensure_weekly_budget,
    load_env,
    moderate_ads,
    plan_lines,
    poll_ads,
    preflight,
    resolve_geo,
    resume_ads,
    rollback,
)
from yandex_direct_api_client import (
    CpmBannerAdGroup,
    CpmBannerCampaign,
    YandexDirectClient,
)
from yandex_direct_api_client.exceptions import ValidationError

logger = logging.getLogger("launch_rsy")

#: Тип кампании сценария.
CAMPAIGN_KIND = "CPM_BANNER_CAMPAIGN"

#: Префикс ключа кэша для креативов, найденных по имени.
CREATIVE_CACHE_PREFIX = "creative:"


@dataclass
class RsyaLaunchSpec(LaunchSpecBase):
    """Спецификация запуска классической РСЯ.

    :param creative_id: ID готового креатива (`IMAGE_CREATIVE`); взаимоисключающе
        с `creative_name`.
    :param creative_name: имя креатива для поиска через `creatives/get`.
    :param turbo_page_id: ID Турбо-страницы вместо ссылки.
    :param subtype: подтип группы (`KEYWORDS` или `USER_PROFILE`).
    :param negative_keywords: минус-фразы группы (запрещены для
        `USER_PROFILE`).
    :param counter_ids: счётчики Яндекс Метрики.
    """

    creative_id: Optional[int] = None
    creative_name: Optional[str] = None
    turbo_page_id: Optional[int] = None
    subtype: str = "KEYWORDS"
    negative_keywords: Optional[Sequence[str]] = None
    counter_ids: Optional[Sequence[int]] = None

    def plan(self) -> List[str]:
        """План запуска с учётом креатива.

        :return: список строк плана.
        """
        lines = plan_lines(self, CAMPAIGN_KIND)
        creative = (
            f"creative_id={self.creative_id}"
            if self.creative_id
            else f"creative_name={self.creative_name!r}"
        )
        lines.insert(2, f"Креатив: {creative}")
        if self.negative_keywords:
            lines.append(f"Минус-фразы группы: {len(self.negative_keywords)}")
        return lines


def _parse_date(value: Optional[str]) -> Optional[_dt.date]:
    """Разобрать дату `YYYY-MM-DD`.

    :param value: строка даты либо None.
    :return: объект даты или None.
    :raises ValidationError: строка не является датой.
    """
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"Некорректная дата {value!r}: ожидается YYYY-MM-DD") from exc


def _validate_spec(spec: RsyaLaunchSpec) -> None:
    """Проверить спецификацию до любых сетевых вызовов.

    :param spec: спецификация запуска.
    :raises ValidationError: не задан креатив, нет ссылки/Турбо-страницы,
        не задан бюджет или неизвестен подтип группы.
    """
    if not spec.creative_id and not spec.creative_name:
        raise ValidationError(
            "Классической РСЯ нужен готовый креатив: укажите creative_id "
            "(созданный в конструкторе креативов) или creative_name "
            "(скрипт найдёт его через creatives/get). Автоматическая загрузка "
            "баннерного креатива API не поддерживает — см. scripts/launch_epk.py"
        )
    if spec.creative_id and spec.creative_name:
        raise ValidationError("Задайте либо creative_id, либо creative_name, не оба")
    if not spec.href and not spec.turbo_page_id:
        raise ValidationError("Нужна ссылка href (или turbo_page_id) для объявления")
    ensure_weekly_budget(spec)
    if spec.subtype not in ("KEYWORDS", "USER_PROFILE"):
        raise ValidationError(
            f"Неизвестный подтип группы {spec.subtype!r}: доступно KEYWORDS, "
            "USER_PROFILE"
        )
    if spec.subtype == "USER_PROFILE" and spec.negative_keywords:
        raise ValidationError(
            "CpmBannerUserProfileAdGroup не поддерживает NegativeKeywords"
        )


def _fail(result: LaunchResult, step: LaunchStep, exc: Exception) -> LaunchResult:
    """Зафиксировать сбой шага в отчёте запуска.

    :param result: отчёт запуска.
    :param step: сорванный шаг.
    :param exc: исключение.
    :return: тот же отчёт с `ok=False`.
    """
    step.failed(f"{type(exc).__name__}: {exc}")
    result.ok = False
    result.error = f"{step.name}: {exc}"
    logger.error("Сбой шага %s: %s", step.name, exc)
    return result


def _resolve_creative(
    client: YandexDirectClient,
    spec: RsyaLaunchSpec,
    step: LaunchStep,
    cache: ReuseCache,
) -> int:
    """Определить ID креатива (по ID или по имени, с кэшем).

    :param client: авторизованный клиент.
    :param spec: спецификация запуска.
    :param step: шаг отчёта для пометки результата.
    :param cache: кэш переиспользования.
    :return: ID креатива.
    :raises ValidationError: креатив не найден или найдено несколько.
    """
    if spec.creative_id:
        step.done(f"creative_id={spec.creative_id}")
        return int(spec.creative_id)
    name = str(spec.creative_name)
    cache_key = f"{CREATIVE_CACHE_PREFIX}{name}"
    cached = cache.lookup(cache_key)
    if cached is not None:
        step.reused(f"creative_id={cached} (из кэша по имени {name!r})")
        return int(cached)
    ids = client.creatives.image_creative_ids(names=[name])
    if not ids:
        raise ValidationError(
            f"Картинный креатив с именем {name!r} не найден. Создайте его в "
            "конструкторе креативов Директа: API баннерные креативы не создаёт"
        )
    if len(ids) > 1:
        raise ValidationError(
            f"Под имя {name!r} подходит {len(ids)} креативов ({ids}) — укажите "
            "creative_id явно"
        )
    cache.store(cache_key, ids[0])
    step.done(f"creative_id={ids[0]} (найден по имени {name!r})")
    return int(ids[0])


def launch(
    client: YandexDirectClient,
    spec: RsyaLaunchSpec,
    *,
    dry_run: bool = False,
    poll_interval: float = 30.0,
    poll_timeout: float = 3600.0,
    confirm: bool = False,
) -> LaunchResult:
    """Собрать и выполнить запуск классической РСЯ.

    Порядок шагов: валидация → (справочники, лимиты) → гео → креатив →
    кампания → группа → объявление → модерация → показы → опрос статуса.

    Ошибка на любом шаге **не** выбрасывается наружу: сбой фиксируется в
    отчёте, а созданные сущности доступны в `result.partial_ids` для
    компенсации через `rollback(result.partial_ids, confirm=True)`.

    :param client: авторизованный клиент.
    :param spec: спецификация запуска.
    :param dry_run: True — только валидация и план, **ноль** сетевых вызовов.
    :param poll_interval: пауза между опросами статуса, секунды.
    :param poll_timeout: максимальное время ожидания статуса, секунды.
    :param confirm: разрешить запуск с «нетестовым» именем.
    :return: отчёт о запуске.
    """
    result = LaunchResult(
        ok=True,
        dry_run=dry_run,
        plan=spec.plan(),
        partial_ids=PartialIds(api_version="v5"),
    )
    steps: List[LaunchStep] = result.steps
    validation = LaunchStep("validation")
    steps.append(validation)
    geo_step = LaunchStep("geo")
    creative_step = LaunchStep("creative")
    campaign_step = LaunchStep("campaign")
    group_step = LaunchStep("ad_group")
    ad_step = LaunchStep("ad")
    moderate_step = LaunchStep("moderate")
    serve_step = LaunchStep("serve")
    status_step = LaunchStep("status")
    steps.extend([geo_step, creative_step, campaign_step, group_step, ad_step,
                  moderate_step, serve_step, status_step])

    try:
        _validate_spec(spec)
        ensure_test_name(spec.name, confirm=confirm)
        validation.done("спецификация корректна")
    except ValidationError as exc:
        return _fail(result, validation, exc)

    if dry_run:
        for step in steps[1:]:
            step.skipped("dry_run: сетевые вызовы не выполняются")
        logger.info("DRY-RUN РСЯ:\n%s", "\n".join(result.plan))
        return result

    cache = ReuseCache.load(prefix="rsy", enabled=spec.reuse_cache)
    start = _parse_date(spec.start_date) or (_dt.date.today() + _dt.timedelta(days=1))

    try:
        info = preflight(client)
        geo_step.done(info.describe())
        if info.warnings:
            for warning in info.warnings:
                logger.warning("Предварительная проверка: %s", warning)
    except Exception as exc:  # noqa: BLE001 — шаг 1: компенсировать нечего
        return _fail(result, geo_step, exc)

    try:
        region_ids = resolve_geo(client, spec)
        geo_step.detail = f"{info.describe()}; регионов={len(region_ids)}"
    except Exception as exc:  # noqa: BLE001
        return _fail(result, geo_step, exc)

    try:
        creative_id = _resolve_creative(client, spec, creative_step, cache)
        result.partial_ids.creative_id = creative_id
    except Exception as exc:  # noqa: BLE001
        return _fail(result, creative_step, exc)

    try:
        campaign = CpmBannerCampaign(
            name=spec.name,
            start_date=start,
            end_date=_parse_date(spec.end_date),
            weekly_budget=ensure_weekly_budget(spec),
            counter_ids=list(spec.counter_ids) if spec.counter_ids else None,
        )
        created = client.campaigns.create(campaign)
        result.partial_ids.campaign_id = int(created["Id"])
        campaign_step.done(f"campaign_id={result.partial_ids.campaign_id}")
    except Exception as exc:  # noqa: BLE001
        return _fail(result, campaign_step, exc)

    try:
        group = CpmBannerAdGroup(
            name=spec.ad_group_name(),
            campaign_id=int(result.partial_ids.campaign_id),
            region_ids=list(region_ids),
            subtype=spec.subtype,
            negative_keywords=(
                list(spec.negative_keywords) if spec.negative_keywords else None
            ),
        )
        created_group = client.ad_groups.create([group])[0]
        result.partial_ids.ad_group_id = int(created_group["Id"])
        group_step.done(f"ad_group_id={result.partial_ids.ad_group_id}")
    except Exception as exc:  # noqa: BLE001
        return _fail(result, group_step, exc)

    try:
        ad = client.ads.create_rsya_banner(
            int(result.partial_ids.ad_group_id),
            creative_id,
            href=spec.href,
            turbo_page_id=spec.turbo_page_id,
        )
        result.partial_ids.ad_ids.append(int(ad["Id"]))
        ad_step.done(f"ad_id={ad['Id']}")
    except Exception as exc:  # noqa: BLE001
        return _fail(result, ad_step, exc)

    ad_ids = list(result.partial_ids.ad_ids)
    if spec.moderate:
        try:
            result.ad_statuses = moderate_ads(client, ad_ids)
            moderate_step.done(
                ", ".join(f"{k}={v}" for k, v in result.ad_statuses.items())
                or "нет результатов"
            )
        except Exception as exc:  # noqa: BLE001
            return _fail(result, moderate_step, exc)
    else:
        moderate_step.skipped("spec.moderate=False: объявление остаётся в DRAFT")

    if spec.serve:
        try:
            resumed = resume_ads(client, ad_ids)
            serve_step.done(f"показы возобновлены: {resumed or 'нет'}")
        except Exception as exc:  # noqa: BLE001
            return _fail(result, serve_step, exc)
    else:
        serve_step.skipped("spec.serve=False: показы не включаются")

    if spec.wait_status:
        try:
            result.ad_statuses = poll_ads(
                client,
                ad_ids,
                interval=poll_interval,
                timeout=poll_timeout,
            )
            status_step.done(
                ", ".join(f"{k}={v}" for k, v in result.ad_statuses.items())
            )
        except Exception as exc:  # noqa: BLE001
            return _fail(result, status_step, exc)
    else:
        status_step.skipped("spec.wait_status=False: опрос статуса не запрошен")

    return result


def _build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов командной строки.

    :return: настроенный парсер.
    """
    parser = argparse.ArgumentParser(
        description="E2E-запуск классической РСЯ (CPM_BANNER_CAMPAIGN)",
    )
    parser.add_argument("--name", required=True, help="имя тестовой кампании")
    parser.add_argument(
        "--creative-id", type=int, default=None, help="ID готового креатива"
    )
    parser.add_argument(
        "--creative-name", default=None, help="имя креатива для поиска"
    )
    parser.add_argument(
        "--budget", required=True, type=float, help="недельный бюджет в валюте аккаунта"
    )
    parser.add_argument("--href", default=None, help="ссылка объявления")
    parser.add_argument(
        "--turbo-page-id", type=int, default=None, help="ID Турбо-страницы"
    )
    parser.add_argument("--start-date", default=None, help="дата старта YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="дата окончания YYYY-MM-DD")
    parser.add_argument(
        "--geo", nargs="*", default=None, help="регионы показа (названия или ID)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="только план, без сетевых вызовов"
    )
    parser.add_argument("--wait", action="store_true", help="ждать статус модерации")
    parser.add_argument(
        "--serve", action="store_true", help="включить показы после модерации"
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="после запуска откатить созданное (архив и удаление)",
    )
    parser.add_argument(
        "--confirm", action="store_true", help="разрешить нетестовое имя кампании"
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Точка входа CLI.

    :param argv: аргументы командной строки (None — из sys.argv).
    :return: код возврата: 0 — успех, 1 — сбой запуска или компенсации.
    """
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    spec = RsyaLaunchSpec(
        name=args.name,
        weekly_budget=args.budget,
        start_date=args.start_date,
        end_date=args.end_date,
        geo=args.geo or None,
        href=args.href,
        creative_id=args.creative_id,
        creative_name=args.creative_name,
        turbo_page_id=args.turbo_page_id,
        moderate=not args.dry_run,
        serve=args.serve,
        wait_status=args.wait,
    )
    client = YandexDirectClient()
    try:
        result = launch(client, spec, dry_run=args.dry_run, confirm=args.confirm)
        logger.info("План запуска:\n%s", "\n".join(result.plan))
        logger.info("%s", result.summary())
        if not result.ok:
            if result.partial_ids.is_empty:
                return 1
            report = rollback(client, result.partial_ids, confirm=args.rollback)
            logger.info("Компенсация: %s", report.steps)
            for error in report.errors:
                logger.error("Компенсация: %s", error)
            return 1
        if args.rollback and not args.dry_run:
            report = rollback(client, result.partial_ids, confirm=True)
            logger.info("Компенсация: %s", report.steps)
            return 0 if report.ok else 1
        return 0
    finally:
        client.close()


__all__ = ["CAMPAIGN_KIND", "RsyaLaunchSpec", "launch", "main"]

if __name__ == "__main__":
    sys.exit(main())
