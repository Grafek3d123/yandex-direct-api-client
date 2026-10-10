"""E2E-сборка запуска ЕПК (`UNIFIED_CAMPAIGN`, слой 5, сценарий 2Б).

Сценарий 2Б — **основной автоматический** путь (D11), потому что он не
требует ручных шагов в веб-интерфейсе:

    справочники и лимиты → гео → загрузка изображений (adimages/add) →
    ЕПК-кампания (v501) → группа ЕПК → ResponsiveAd (v501) → модерация →
    показы → опциональный опрос статуса

Ключевой момент: изображение загружается один раз. `AdImageHash` кэшируется
по **хэшу содержимого файла** (SHA-256), поэтому повторный запуск с тем же
файлом не грузит его повторно — используется сохранённый хэш.

Оркестрация живёт вне пакета: `yandex_direct_api_client` остаётся набором
атомарных операций, порядок вызовов собирает скрипт.

Запуск вручную (живой аккаунт, всё в `DRAFT`, показы выключены), из корня
репозитория:

    .venv\\Scripts\\python.exe -m scripts.launch_epk --dry-run \\
        --name "E2E TEST ЕПК" --image pic.jpg --budget 1 \\
        --href https://example.com
    .venv\\Scripts\\python.exe -m scripts.launch_epk --name "E2E TEST ЕПК" \\
        --image pic.jpg --budget 1 --href https://example.com --rollback

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
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from scripts._launch_common import (
    LaunchResult,
    LaunchSpecBase,
    LaunchStep,
    PartialIds,
    ReuseCache,
    ensure_test_name,
    ensure_weekly_budget,
    file_digest,
    load_env,
    moderate_ads,
    plan_lines,
    poll_ads,
    preflight,
    resolve_geo,
    resume_ads,
    rollback,
    single_result,
)
from yandex_direct_api_client import (
    UnifiedAdGroup,
    UnifiedCampaign,
    UnifiedStrategy,
    YandexDirectClient,
)
from yandex_direct_api_client.exceptions import ValidationError

logger = logging.getLogger("launch_epk")

#: Тип кампании сценария.
CAMPAIGN_KIND = "UNIFIED_CAMPAIGN"

#: Версия API для сущностей ЕПК.
API_VERSION = "v501"

#: Префикс ключа кэша для загруженных изображений.
AD_IMAGE_CACHE_PREFIX = "adimage:"

#: Ставка по умолчанию (ручная) для стратегий, где ставка обязательна.
DEFAULT_BID = 1.0

#: Заголовок объявления ЕПК по умолчанию (тестовый).
DEFAULT_TITLE = "E2E TEST ЕПК"

#: Текст объявления ЕПК по умолчанию (тестовый).
DEFAULT_TEXT = "Тестовое объявление ЕПК для проверки сборки запуска."


@dataclass
class EpkLaunchSpec(LaunchSpecBase):
    """Спецификация запуска ЕПК.

    :param images: пути к файлам изображений объявления (1..5).
    :param titles: заголовки `ResponsiveAd` (1..7 по 56 символов).
    :param texts: тексты `ResponsiveAd` (1..3 по 81 символ).
    :param business_id: ID организации из ЕИР (вместо ссылки).
    :param counter_ids: счётчики Яндекс Метрики.
    :param network_strategy: стратегия показа в сетях (по умолчанию
        `NETWORK_DEFAULT` — показы в сетях по цене ЕПК).
    :param search_strategy: стратегия показа на поиске (по умолчанию
        `SERVING_OFF` — медийный сценарий).
    :param bid: ставка для стратегий, требующих ставки.
    :param goal_id: цель Метрики для стратегий, требующих цели.
    """

    images: Sequence[str] = ()
    titles: Sequence[str] = (DEFAULT_TITLE,)
    texts: Sequence[str] = (DEFAULT_TEXT,)
    business_id: Optional[int] = None
    counter_ids: Optional[Sequence[int]] = None
    network_strategy: str = "NETWORK_DEFAULT"
    search_strategy: str = "WB_MAXIMUM_CLICKS"
    bid: float = DEFAULT_BID
    goal_id: Optional[int] = None

    def plan(self) -> List[str]:
        """План запуска с деталями объявления.

        :return: список строк плана.
        """
        lines = plan_lines(self, CAMPAIGN_KIND)
        lines.insert(2, f"Изображения ({len(self.images)}): {', '.join(self.images)}")
        lines.append(f"Заголовков: {len(self.titles)}, текстов: {len(self.texts)}")
        lines.append(
            f"Стратегии: поиск={self.search_strategy}, сети={self.network_strategy}"
        )
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


def _validate_spec(spec: EpkLaunchSpec) -> None:
    """Проверить спецификацию до любых сетевых вызовов.

    :param spec: спецификация запуска.
    :raises ValidationError: нет изображений или ссылки/бизнеса, нет бюджета,
        некорректные заголовки/тексты.
    """
    if not spec.images:
        raise ValidationError(
            "ЕПК требует изображения объявления: передайте пути к файлам в "
            "spec.images (1..5 файлов .jpg/.jpeg/.png/.gif)"
        )
    if not spec.href and not spec.business_id:
        raise ValidationError("Нужна ссылка href (или business_id) для объявления")
    ensure_weekly_budget(spec)
    for image in spec.images:
        if not Path(image).is_file():
            raise ValidationError(f"Файл изображения не найден: {image}")
    if not spec.titles:
        raise ValidationError("ResponsiveAd требует хотя бы один заголовок")
    if not spec.texts:
        raise ValidationError("ResponsiveAd требует хотя бы один текст")


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


def _upload_images(
    client: YandexDirectClient,
    spec: EpkLaunchSpec,
    step: LaunchStep,
    cache: ReuseCache,
) -> Dict[str, str]:
    """Загрузить изображения, переиспользуя кэш по хэшу содержимого.

    Кэш работает целиком: если хотя бы для одного файла хэш не найден,
    загружаются только недостающие файлы, а найденные берутся из кэша.
    Кэшируются **только загруженные в этом запуске** хэши — на откате
    удаляются именно они (чужие изображения не трогаем).

    :param client: авторизованный клиент.
    :param spec: спецификация запуска.
    :param step: шаг отчёта для пометки результата.
    :param cache: кэш переиспользования.
    :return: отображение `путь к файлу → AdImageHash`.
    :raises ValidationError: API вернул неполный ответ или ошибку элемента.
    """
    digests = {path: file_digest(path) for path in spec.images}
    keys = [f"{AD_IMAGE_CACHE_PREFIX}{digests[path]}" for path in spec.images]
    cached = cache.lookup_many(keys) or []

    hashes: Dict[str, str] = {}
    missing: List[str] = []
    reused = 0
    for index, path in enumerate(spec.images):
        found = cached[index] if index < len(cached) else None
        if found:
            hashes[path] = found
            reused += 1
        else:
            missing.append(path)

    for path in missing:
        name = Path(path).name
        raw = client.ad_images.add_from_file(path, name=name)
        result = single_result(raw, f"adimages/add ({name})")
        ad_image_hash = result.get("AdImageHash")
        if not isinstance(ad_image_hash, str) or not ad_image_hash:
            raise ValidationError(
                f"adimages/add не вернул AdImageHash для {path}: ответ {result!r}"
            )
        hashes[path] = ad_image_hash
        cache.store(f"{AD_IMAGE_CACHE_PREFIX}{digests[path]}", ad_image_hash)

    detail = f"загружено={len(missing)}, из кэша={reused}"
    if missing:
        step.done(detail)
    else:
        step.reused(detail)
    return hashes


def _build_strategy(spec: EpkLaunchSpec, placement: str) -> UnifiedStrategy:
    """Собрать стратегию ЕПК для поиска или сетей.

    Недельный бюджет и цель подставляются только тем стратегиям, которые их
    требуют: `SERVING_OFF`/`NETWORK_DEFAULT` не принимают ни того, ни другого
    и получили бы ошибку валидации.

    :param spec: спецификация запуска.
    :param placement: `Search` или `Network`.
    :return: готовый билдер стратегии.
    :raises ValidationError: стратегия требует цель, а `goal_id` не задан.
    """
    strategy = spec.search_strategy if placement == "Search" else spec.network_strategy
    kwargs: Dict[str, Any] = {"strategy": strategy}
    from yandex_direct_api_client.models.campaign_payloads import (
        UNIFIED_STRATEGY_REQUIRES_BUDGET,
        UNIFIED_STRATEGY_REQUIRES_GOAL,
    )

    if strategy in UNIFIED_STRATEGY_REQUIRES_BUDGET:
        kwargs["weekly_budget"] = ensure_weekly_budget(spec)
    if strategy in UNIFIED_STRATEGY_REQUIRES_GOAL and spec.goal_id is None:
        raise ValidationError(
            f"Стратегия {strategy} требует goal_id — цели Метрики выбирает "
            "пользователь, угадывать их нельзя"
        )
    if strategy in UNIFIED_STRATEGY_REQUIRES_GOAL and spec.goal_id is not None:
        kwargs["goal_id"] = spec.goal_id
    if strategy == "AVERAGE_CPC":
        kwargs["average_cpc"] = spec.bid
    return UnifiedStrategy(**kwargs)


def _search_strategy(spec: EpkLaunchSpec) -> UnifiedStrategy:
    """Стратегия показа на поиске.

    :param spec: спецификация запуска.
    :return: готовый билдер стратегии.
    """
    return _build_strategy(spec, "Search")


def _network_strategy(spec: EpkLaunchSpec) -> UnifiedStrategy:
    """Стратегия показа в сетях.

    :param spec: спецификация запуска.
    :return: готовый билдер стратегии.
    """
    return _build_strategy(spec, "Network")


def launch(
    client: YandexDirectClient,
    spec: EpkLaunchSpec,
    *,
    dry_run: bool = False,
    poll_interval: float = 30.0,
    poll_timeout: float = 3600.0,
    confirm: bool = False,
) -> LaunchResult:
    """Собрать и выполнить запуск ЕПК.

    Порядок шагов: валидация → (справочники, лимиты) → гео → изображения →
    кампания ЕПК → группа ЕПК → `ResponsiveAd` → модерация → показы →
    опрос статуса.

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
        partial_ids=PartialIds(api_version=API_VERSION, unified=True),
    )
    steps: List[LaunchStep] = result.steps
    validation = LaunchStep("validation")
    geo_step = LaunchStep("geo")
    image_step = LaunchStep("ad_images")
    campaign_step = LaunchStep("campaign")
    group_step = LaunchStep("ad_group")
    ad_step = LaunchStep("ad")
    moderate_step = LaunchStep("moderate")
    serve_step = LaunchStep("serve")
    status_step = LaunchStep("status")
    steps.extend(
        [
            validation,
            geo_step,
            image_step,
            campaign_step,
            group_step,
            ad_step,
            moderate_step,
            serve_step,
            status_step,
        ]
    )

    try:
        _validate_spec(spec)
        ensure_test_name(spec.name, confirm=confirm)
        validation.done("спецификация корректна")
    except ValidationError as exc:
        return _fail(result, validation, exc)

    if dry_run:
        for step in steps[1:]:
            step.skipped("dry_run: сетевые вызовы не выполняются")
        logger.info("DRY-RUN ЕПК:\n%s", "\n".join(result.plan))
        return result

    cache = ReuseCache.load(prefix="epk", enabled=spec.reuse_cache)
    start = _parse_date(spec.start_date) or (_dt.date.today() + _dt.timedelta(days=1))

    try:
        info = preflight(client)
        geo_step.done(info.describe())
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
        digests = _upload_images(client, spec, image_step, cache)
        result.partial_ids.ad_image_hashes = [
            digests[path] for path in spec.images if path in digests
        ]
    except Exception as exc:  # noqa: BLE001
        return _fail(result, image_step, exc)

    try:
        campaign = UnifiedCampaign(
            name=spec.name,
            start_date=start,
            end_date=_parse_date(spec.end_date),
            search=_search_strategy(spec),
            network=_network_strategy(spec),
            counter_ids=list(spec.counter_ids) if spec.counter_ids else None,
        )
        created = single_result(
            client.campaigns.create_unified(campaign), "campaigns/add (ЕПК)"
        )
        result.partial_ids.campaign_id = int(created["Id"])
        campaign_step.done(f"campaign_id={result.partial_ids.campaign_id}")
    except Exception as exc:  # noqa: BLE001
        return _fail(result, campaign_step, exc)

    try:
        group = UnifiedAdGroup(
            name=spec.ad_group_name(),
            campaign_id=int(result.partial_ids.campaign_id),
            region_ids=list(region_ids),
        )
        created_group = client.ad_groups.create([group], api_version=API_VERSION)[0]
        result.partial_ids.ad_group_id = int(created_group["Id"])
        group_step.done(f"ad_group_id={result.partial_ids.ad_group_id}")
    except Exception as exc:  # noqa: BLE001
        return _fail(result, group_step, exc)

    try:
        ad = client.ads.create_responsive_ad(
            int(result.partial_ids.ad_group_id),
            list(spec.titles),
            list(spec.texts),
            href=spec.href,
            ad_image_hashes=list(result.partial_ids.ad_image_hashes),
        )
        result.partial_ids.ad_ids.append(int(ad["Id"]))
        ad_step.done(f"ad_id={ad['Id']}")
    except Exception as exc:  # noqa: BLE001
        return _fail(result, ad_step, exc)

    ad_ids = list(result.partial_ids.ad_ids)
    if spec.moderate:
        try:
            result.ad_statuses = moderate_ads(
                client, ad_ids, api_version=API_VERSION
            )
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
            resumed = resume_ads(client, ad_ids, api_version=API_VERSION)
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
        description="E2E-запуск ЕПК (UNIFIED_CAMPAIGN, v501)",
    )
    parser.add_argument("--name", required=True, help="имя тестовой кампании")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        dest="images",
        help="файл изображения объявления (можно указать несколько раз)",
    )
    parser.add_argument(
        "--budget", required=True, type=float, help="недельный бюджет в валюте аккаунта"
    )
    parser.add_argument("--href", default=None, help="ссылка объявления")
    parser.add_argument("--title", action="append", default=None, help="заголовок")
    parser.add_argument("--text", action="append", default=None, help="текст")
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
    spec = EpkLaunchSpec(
        name=args.name,
        weekly_budget=args.budget,
        start_date=args.start_date,
        end_date=args.end_date,
        geo=args.geo or None,
        href=args.href,
        images=list(args.images),
        titles=tuple(args.title) if args.title else (DEFAULT_TITLE,),
        texts=tuple(args.text) if args.text else (DEFAULT_TEXT,),
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


__all__ = ["API_VERSION", "CAMPAIGN_KIND", "EpkLaunchSpec", "launch", "main"]

if __name__ == "__main__":
    sys.exit(main())
