"""Общие части E2E-сборки запуска (слой 5, задача `task04.md` §8).

Оркестрация намеренно живёт **вне пакета**: `yandex_direct_api_client`
остаётся набором атомарных операций Direct API, а порядок вызовов
(справочники → гео → кампания → группа → креатив → объявление → модерация)
собирается здесь и использует только публичный API клиента.

Что здесь общего у обоих сценариев:

- `LaunchStep` / `LaunchResult` — отчёт о ходе запуска и **частичные ID**
  для компенсации (`LaunchResult.partial_ids`);
- `LaunchSpecBase` — общие поля спецификации запуска;
- `PreflightResult` — проверка клиента перед созданием сущностей;
- `rollback()` — компенсация: остановка показов, архивирование и удаление
  созданного, удаление загруженных изображений;
- `poll_ads()` — опциональный опрос статуса объявлений;
- `ReuseCache` — кэш «хэш содержимого → ID созданной сущности», чтобы
  повторный запуск с тем же креативом/картинкой не грузил файл второй раз;
- `file_digest()` — SHA-256 содержимого файла (ключ кэша).

Модуль не выполняет сетевых вызовов сам и не содержит секретов.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.config import API_VERSION_V5, API_VERSION_V501
from yandex_direct_api_client.exceptions import ValidationError
from yandex_direct_api_client.models.batch import BatchResult

logger = logging.getLogger("launch")

#: Имя переменной окружения с каталогом кэша переиспользования.
ENV_REUSE_CACHE_DIR = "YANDEX_DIRECT_LAUNCH_CACHE_DIR"

#: Каталог кэша переиспользования по умолчанию.
DEFAULT_REUSE_CACHE_DIR = "~/.yandex-direct-api-client/launch-cache"

#: Имя файла кэша переиспользования внутри каталога.
REUSE_CACHE_FILENAME = "reuse.json"

#: Статусы шага запуска.
STEP_PLANNED = "planned"
STEP_DONE = "done"
STEP_REUSED = "reused"
STEP_FAILED = "failed"
STEP_SKIPPED = "skipped"

#: Статусы объявления, при которых опрос статуса можно прекратить.
TERMINAL_AD_STATUSES = ("MODERATED", "REJECTED", "MODERATION_REJECTED")

#: Статусы объявления, означающие, что модерация ещё идёт.
PENDING_AD_STATUSES = ("MODERATION", "SUBMITTED", "PROCESSING")


def file_digest(path: Union[str, "os.PathLike[str]"]) -> str:
    """Посчитать SHA-256 содержимого файла — ключ кэша переиспользования.

    Ключ строится по **содержимому**, а не по имени или пути: переименование
    файла или перенос в другой каталог не приводят к повторной загрузке,
    а изменение байтов — приводит.

    :param path: путь к файлу.
    :return: hex-хэш содержимого.
    :raises ValidationError: файл не существует или не читается.
    """
    digest = hashlib.sha256()
    try:
        with open(Path(path), "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValidationError(f"Не удалось прочитать файл {path}: {exc}") from exc
    return digest.hexdigest()


@dataclass
class ReuseCache:
    """Кэш «хэш содержимого → ID сущности» для повторных запусков.

    Файл кэша вспомогательный: проблемы с файловой системой не должны ломать
    запуск — они логируются на DEBUG, и работа продолжается без кэша.

    :param path: путь к файлу кэша; None — работа без кэша на диске.
    :param entries: загруженные записи (заполняется при чтении файла).
    :param hits: счётчик попаданий (только для отчёта).
    :param misses: счётчик промахов.
    """

    path: Optional[Path] = None
    entries: Dict[str, str] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    @classmethod
    def load(
        cls,
        *,
        prefix: str = "",
        enabled: bool = True,
        directory: Optional[str] = None,
    ) -> "ReuseCache":
        """Открыть кэш из каталога (по умолчанию — домашний каталог).

        :param prefix: подкаталог внутри каталога кэша (обычно имя сценария).
        :param enabled: False — вернуть кэш без файла (каждый запуск грузит
            заново).
        :param directory: каталог кэша; None — из `YANDEX_DIRECT_LAUNCH_CACHE_DIR`
            либо значение по умолчанию.
        :return: готовый к работе кэш.
        """
        if not enabled:
            return cls()
        base = directory or os.environ.get(ENV_REUSE_CACHE_DIR) or DEFAULT_REUSE_CACHE_DIR
        path = Path(base).expanduser()
        if prefix:
            path = path / prefix
        cache = cls(path=path / REUSE_CACHE_FILENAME)
        cache.reload()
        return cache

    def reload(self) -> None:
        """Прочитать записи кэша с диска (ошибки игнорируются)."""
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.debug("Кэш переиспользования %s не прочитан: %s", self.path, exc)
            return
        if isinstance(raw, dict) and isinstance(raw.get("entries"), dict):
            self.entries = {str(k): str(v) for k, v in raw["entries"].items()}

    def save(self) -> None:
        """Записать записи кэша на диск (ошибки игнорируются)."""
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"entries": self.entries}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.debug("Кэш переиспользования %s не записан: %s", self.path, exc)

    def lookup(self, key: str) -> Optional[str]:
        """Найти сохранённый ID по ключу.

        :param key: ключ (обычно хэш содержимого файла).
        :return: сохранённый ID или None.
        """
        value = self.entries.get(key)
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value

    def store(self, key: str, value: Union[int, str]) -> None:
        """Сохранить ID по ключу и сохранить кэш на диск.

        :param key: ключ (обычно хэш содержимого файла).
        :param value: созданный ID (число или строка).
        """
        self.entries[key] = str(value)
        self.save()

    def lookup_many(self, keys: Sequence[str]) -> Optional[List[str]]:
        """Найти ID сразу по нескольким ключам.

        Используется, когда сущность создаётся одним batch-запросом: кэш
        работает только когда **все** ключи найдены, иначе пришлось бы
        частично использовать чужой результат.

        :param keys: ключи в том же порядке, что и создаваемые сущности.
        :return: список ID в том же порядке либо None, если хотя бы один
            ключ не найден.
        """
        if not keys:
            return []
        values: List[str] = []
        for key in keys:
            value = self.entries.get(key)
            if value is None:
                self.misses += 1
                return None
            self.hits += 1
            values.append(value)
        return values


@dataclass
class LaunchStep:
    """Один шаг запуска и его результат.

    :param name: имя шага (например, `campaign`).
    :param status: `planned`, `done`, `reused`, `failed` или `skipped`.
    :param detail: человекочитаемая деталь (ID, причина сбоя).
    """

    name: str
    status: str = STEP_PLANNED
    detail: str = ""

    def done(self, detail: str = "") -> None:
        """Отметить шаг выполненным.

        :param detail: деталь для отчёта.
        """
        self.status = STEP_DONE
        self.detail = detail

    def reused(self, detail: str = "") -> None:
        """Отметить шаг выполненным через кэш переиспользования.

        :param detail: деталь для отчёта.
        """
        self.status = STEP_REUSED
        self.detail = detail

    def failed(self, detail: str) -> None:
        """Отметить шаг сорванным.

        :param detail: причина сбоя.
        """
        self.status = STEP_FAILED
        self.detail = detail

    def skipped(self, detail: str = "") -> None:
        """Отметить шаг пропущенным.

        :param detail: причина пропуска.
        """
        self.status = STEP_SKIPPED
        self.detail = detail

    def __str__(self) -> str:
        """Человекочитаемая строка шага.

        :return: `имя: статус (деталь)`.
        """
        return f"{self.name}: {self.status}" + (f" ({self.detail})" if self.detail else "")


@dataclass
class PartialIds:
    """ID сущностей, созданных до сбоя (нужны для компенсации).

    :param campaign_id: ID созданной кампании, если создана.
    :param ad_group_id: ID созданной группы, если создана.
    :param ad_ids: ID созданных объявлений.
    :param ad_image_hashes: хэши загруженных в этом запуске изображений.
    :param creative_id: использованный креатив (классическая РСЯ).
    :param api_version: версия API запуска (`v5` или `v501`).
    :param unified: True, если сущности ЕПК (для выбора маршрута отката).
    """

    campaign_id: Optional[int] = None
    ad_group_id: Optional[int] = None
    ad_ids: List[int] = field(default_factory=list)
    ad_image_hashes: List[str] = field(default_factory=list)
    creative_id: Optional[int] = None
    api_version: str = API_VERSION_V5
    unified: bool = False

    @property
    def is_empty(self) -> bool:
        """Есть ли что откатывать.

        :return: True, если ни одна сущность не создана.
        """
        return not (
            self.campaign_id
            or self.ad_group_id
            or self.ad_ids
            or self.ad_image_hashes
        )

    def summary(self) -> str:
        """Краткое описание созданного — для логов и отчёта.

        :return: строка с ID.
        """
        parts: List[str] = []
        if self.campaign_id:
            parts.append(f"campaign={self.campaign_id}")
        if self.ad_group_id:
            parts.append(f"ad_group={self.ad_group_id}")
        if self.ad_ids:
            parts.append(f"ads={','.join(str(i) for i in self.ad_ids)}")
        if self.ad_image_hashes:
            parts.append(f"ad_images={len(self.ad_image_hashes)}")
        return ", ".join(parts) if parts else "ничего не создано"


@dataclass
class RollbackReport:
    """Отчёт о компенсации.

    :param steps: выполненные действия компенсации.
    :param errors: ошибки компенсации (компенсация считается неполной).
    """

    steps: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Прошла ли компенсация без ошибок.

        :return: True, если ошибок нет.
        """
        return not self.errors


@dataclass
class PreflightResult:
    """Результат предварительной проверки клиента.

    :param login: логин клиента.
    :param currency: валюта клиента.
    :param can_create_campaign: False, если лимит кампаний исчерпан.
    :param campaigns_count: текущее число кампаний аккаунта.
    :param warnings: предупреждения, не блокирующие запуск.
    """

    login: str = ""
    currency: str = ""
    can_create_campaign: bool = True
    campaigns_count: int = 0
    warnings: List[str] = field(default_factory=list)

    def describe(self) -> str:
        """Текстовая сводка для плана запуска.

        :return: строка с логином, валютой и числом кампаний.
        """
        return (
            f"клиент={self.login or '?'}, валюта={self.currency or '?'}, "
            f"кампаний на аккаунте={self.campaigns_count}"
        )


@dataclass
class LaunchResult:
    """Результат E2E-запуска.

    :param ok: True, если запуск дошёл до целевого статуса.
    :param dry_run: True, если выполнялась только валидация и план.
    :param plan: строки плана (что именно будет сделано).
    :param steps: шаги запуска с фактическим статусом.
    :param partial_ids: созданные сущности (основа компенсации).
    :param ad_statuses: статусы объявлений после модерации/опроса.
    :param error: текст ошибки, если запуск сорвался.
    :param target_status: ожидаемый статус объявлений.
    """

    ok: bool
    dry_run: bool = False
    plan: List[str] = field(default_factory=list)
    steps: List[LaunchStep] = field(default_factory=list)
    partial_ids: PartialIds = field(default_factory=PartialIds)
    ad_statuses: Dict[int, str] = field(default_factory=dict)
    error: Optional[str] = None
    target_status: str = "MODERATION"

    def step(self, name: str) -> LaunchStep:
        """Найти шаг по имени.

        :param name: имя шага.
        :return: найденный шаг.
        :raises KeyError: если шага с таким именем нет.
        """
        for item in self.steps:
            if item.name == name:
                return item
        raise KeyError(name)

    def succeeded(self) -> bool:
        """Все ли шаги прошли успешно.

        :return: True, если нет шагов со статусом `failed`.
        """
        return all(item.status != STEP_FAILED for item in self.steps)

    def summary(self) -> str:
        """Многострочная сводка запуска для лога и отчёта.

        :return: текст со статусом, шагами и созданными ID.
        """
        head = "DRY-RUN" if self.dry_run else ("OK" if self.ok else "СБОЙ")
        lines = [f"Результат: {head}"]
        if self.error:
            lines.append(f"Ошибка: {self.error}")
        lines.append("Шаги:")
        for item in self.steps:
            lines.append(f"  - {item}")
        if self.ad_statuses:
            statuses = ", ".join(
                f"{ad_id}={status}" for ad_id, status in sorted(self.ad_statuses.items())
            )
            lines.append(f"Статусы объявлений: {statuses}")
        lines.append(f"Создано: {self.partial_ids.summary()}")
        return "\n".join(lines)


@dataclass
class LaunchSpecBase:
    """Общие поля спецификации запуска.

    :param name: имя кампании и группы (для тестовых сущностей рекомендуется
        префикс `TEST`/`E2E`).
    :param weekly_budget: недельный бюджет в валюте аккаунта.
    :param start_date: дата старта; None — завтра.
    :param end_date: дата окончания; None — бессрочно.
    :param geo: селектор гео (`RegionSelector`); None — Москва и область.
    :param href: адрес объявления (обязателен для ЕПК и РСЯ).
    :param moderate: отправлять ли объявления на модерацию.
    :param serve: включать ли показы сразу после модерации (`resume`).
    :param wait_status: ждать ли терминального статуса объявлений.
    :param reuse_cache: использовать ли кэш переиспользования сущностей.
    """

    name: str
    weekly_budget: Union[int, float, str] = 0
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    geo: Optional[Any] = None
    href: Optional[str] = None
    moderate: bool = True
    serve: bool = False
    wait_status: bool = False
    reuse_cache: bool = True

    def ad_group_name(self) -> str:
        """Имя группы объявлений по умолчанию.

        :return: строка вида `<имя кампании> — группа`.
        """
        return f"{self.name} — группа"


def ensure_weekly_budget(spec: LaunchSpecBase) -> Union[int, float, str]:
    """Проверить недельный бюджет спецификации до любых сетевых вызовов.

    :param spec: спецификация запуска.
    :return: бюджет, приведённый к числу (`Decimal` приводится к строке).
    :raises ValidationError: бюджет не задан или неположителен.
    """
    value = spec.weekly_budget
    if value is None or value == 0 or value == "0":
        raise ValidationError(
            "Недельный бюджет не задан: для тестовой кампании укажите "
            "weekly_budget (например, weekly_budget=1)"
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Некорректный недельный бюджет: {value!r}") from exc
    if number <= 0:
        raise ValidationError(
            f"Недельный бюджет должен быть больше нуля, получено {value!r}"
        )
    return value


def preflight(
    client: YandexDirectClient,
    *,
    check_limits: bool = True,
) -> PreflightResult:
    """Проверить клиента до создания сущностей.

    :param client: авторизованный клиент.
    :param check_limits: запрашивать ли `clients/get` (это сетевой вызов —
        в `dry_run` он не выполняется).
    :return: результат предварительной проверки.
    """
    result = PreflightResult()
    if not check_limits:
        return result
    info = client.clients.get()
    result.login = info.login or ""
    result.currency = info.currency or ""
    campaigns = client.campaigns.list()
    result.campaigns_count = len(campaigns)
    result.can_create_campaign = info.can_create_campaign(len(campaigns))
    if not result.can_create_campaign:
        result.warnings.append(
            "лимит кампаний на клиенте исчерпан — campaigns/add вернёт ошибку"
        )
    return result


def resolve_geo(client: YandexDirectClient, spec: LaunchSpecBase) -> List[int]:
    """Разрешить гео запуска в список ID регионов.

    Значения резолвятся только через справочник Директа: выдуманные ID
    невозможны, неизвестные названия дают `ValidationError` с подсказками.

    :param client: авторизованный клиент.
    :param spec: спецификация запуска.
    :return: список ID регионов для `RegionIds`.
    :raises ValidationError: гео не задано или резолв не дал регионов.
    """
    from yandex_direct_api_client import RegionSelector

    selector = spec.geo
    if selector is None:
        selector = RegionSelector(include=["Москва", "Московская область"])
    if isinstance(selector, RegionSelector):
        return selector.resolve(client.dictionaries)
    if isinstance(selector, (list, tuple)):
        return RegionSelector(include=list(selector)).resolve(client.dictionaries)
    raise ValidationError(
        "geo: ожидается RegionSelector или список регионов, получено "
        f"{type(selector).__name__}"
    )


def moderate_ads(
    client: YandexDirectClient,
    ad_ids: Sequence[int],
    *,
    api_version: Optional[str] = None,
) -> Dict[int, str]:
    """Отправить объявления на модерацию.

    Отправлять можно только объявления в статусе `DRAFT`; ошибки элементов
    не роняют весь пакет — они попадают в лог, а в отчёт попадают только
    успешно отправленные.

    :param client: авторизованный клиент.
    :param ad_ids: ID объявлений.
    :param api_version: версия API; None — версия по умолчанию.
    :return: отображение `ID объявления → статус`.
    """
    statuses: Dict[int, str] = {}
    if not ad_ids:
        return statuses
    results = client.ads.moderate(list(ad_ids), api_version=api_version)
    for item in results:
        ad_id = item.get("Id")
        if isinstance(ad_id, int):
            statuses[ad_id] = str(item.get("Status") or "")
    return statuses


def resume_ads(
    client: YandexDirectClient,
    ad_ids: Sequence[int],
    *,
    api_version: Optional[str] = None,
) -> List[int]:
    """Возобновить показы объявлений.

    :param client: авторизованный клиент.
    :param ad_ids: ID объявлений.
    :param api_version: версия API; None — версия по умолчанию.
    :return: ID объявлений, для которых показы возобновлены.
    """
    resumed: List[int] = []
    if not ad_ids:
        return resumed
    results = client.ads.resume(list(ad_ids), api_version=api_version)
    for item in results:
        ad_id = item.get("Id")
        if isinstance(ad_id, int) and item.get("IsResumed") in (True, "YES"):
            resumed.append(ad_id)
    return resumed


def poll_ads(
    client: YandexDirectClient,
    ad_ids: Sequence[int],
    *,
    interval: float = 30.0,
    timeout: float = 3600.0,
    sleep_fn: Any = time.sleep,
    clock: Any = time.monotonic,
) -> Dict[int, str]:
    """Дождаться терминального статуса объявлений.

    Опрос выполняется только по явно запрошенному `wait_status`: без него
    запуск возвращает статус сразу после `moderate`.

    :param client: авторизованный клиент.
    :param ad_ids: ID объявлений.
    :param interval: пауза между опросами, секунды.
    :param timeout: максимальное время ожидания, секунды.
    :param sleep_fn: функция паузы (подменяется в тестах).
    :param clock: функция времени (подменяется в тестах).
    :return: отображение `ID объявления → статус` на момент завершения.
    """
    statuses: Dict[int, str] = {}
    pending = [int(x) for x in ad_ids]
    if not pending:
        return statuses
    deadline = clock() + max(0.0, float(timeout))
    while pending:
        for ad in client.ads.get(pending):
            statuses[ad.id] = str(ad.status or "")
        pending = [
            ad_id
            for ad_id in pending
            if statuses.get(ad_id, "") not in TERMINAL_AD_STATUSES
        ]
        if not pending:
            break
        if clock() >= deadline:
            logger.warning(
                "Опрос статуса прерван по таймауту: %s остаются в статусе %s",
                pending,
                [statuses.get(i) for i in pending],
            )
            break
        sleep_fn(max(0.0, float(interval)))
    return statuses


def rollback(
    client: YandexDirectClient,
    partial: PartialIds,
    *,
    confirm: bool = False,
    delete_ad_images: bool = True,
) -> RollbackReport:
    """Откатить частично созданные сущности запуска.

    Порядок действий:

    1. остановить показы объявлений и кампании (`suspend`) — чтобы
       архивирование не оставило активных показов;
    2. архивировать объявления и кампанию (`archive`) — сущности уходят в
       архив, история сохраняется;
    3. удалить кампанию (`campaigns/delete` с `confirm=True`) — на этом шаге
       `confirm` обязателен;
    4. удалить изображения, загруженные **в этом запуске**
       (`adimages/delete`), если `delete_ad_images=True`.

    Компенсация не бросает исключений: ошибки собираются в отчёт, чтобы
    вызывающий код мог решить, что делать дальше.

    :param client: авторизованный клиент.
    :param partial: ID созданных сущностей.
    :param confirm: явное подтверждение удаления кампании; без `True` откат
        ограничивается остановкой и архивированием.
    :param delete_ad_images: удалять ли загруженные изображения.
    :return: отчёт о компенсации.
    """
    report = RollbackReport()
    api_version = API_VERSION_V501 if partial.unified else API_VERSION_V5

    if partial.ad_ids:
        try:
            client.ads.suspend(list(partial.ad_ids), api_version=api_version)
            report.steps.append(f"suspend ads={len(partial.ad_ids)}")
        except Exception as exc:  # noqa: BLE001 — компенсация не должна падать
            report.errors.append(f"suspend ads: {exc}")
    if partial.campaign_id:
        try:
            client.campaigns.suspend([partial.campaign_id], api_version=api_version)
            report.steps.append(f"suspend campaign={partial.campaign_id}")
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"suspend campaign: {exc}")
    if partial.ad_ids:
        try:
            client.ads.archive(
                list(partial.ad_ids), confirm=True, api_version=api_version
            )
            report.steps.append(f"archive ads={len(partial.ad_ids)}")
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"archive ads: {exc}")
    if partial.campaign_id:
        try:
            client.campaigns.archive(
                [partial.campaign_id], confirm=True, api_version=api_version
            )
            report.steps.append(f"archive campaign={partial.campaign_id}")
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"archive campaign: {exc}")
        if confirm:
            try:
                if partial.unified:
                    client.campaigns.delete_unified([partial.campaign_id], confirm=True)
                else:
                    client.campaigns.delete([partial.campaign_id], confirm=True)
                report.steps.append(f"delete campaign={partial.campaign_id}")
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"delete campaign: {exc}")
        else:
            report.steps.append(
                "delete campaign пропущен: требуется confirm=True"
            )
    if partial.ad_image_hashes and delete_ad_images:
        try:
            client.ad_images.delete(list(partial.ad_image_hashes), confirm=True)
            report.steps.append(f"delete ad_images={len(partial.ad_image_hashes)}")
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"delete ad_images: {exc}")
    if partial.is_empty:
        report.steps.append("нечего откатывать")
    return report


def single_result(
    result: Union[Mapping[str, Any], BatchResult],
    action: str,
) -> Dict[str, Any]:
    """Сузить результат batch-операции до одного элемента `AddResults`.

    Вызывается только с `on_item_error="raise"` (значение по умолчанию),
    поэтому `BatchResult` означает нарушение контракта самого SDK — это
    ошибка, а не «частичный успех», который можно обработать.

    :param result: результат операции (`dict` или `BatchResult`).
    :param action: название операции для сообщения об ошибке.
    :return: элемент результата как словарь.
    :raises ValidationError: вернулся `BatchResult`.
    """
    if isinstance(result, BatchResult):
        raise ValidationError(
            f"{action}: ожидался один элемент AddResults, а вернулся "
            f"BatchResult ({len(result.succeeded)} успешных, "
            f"{len(result.failed)} с ошибками)"
        )
    return dict(result)


def plan_lines(spec: LaunchSpecBase, kind: str) -> List[str]:
    """Собрать план запуска для отчёта и `dry_run`.

    :param spec: спецификация запуска.
    :param kind: вид кампании (`CPM_BANNER_CAMPAIGN` или `UNIFIED_CAMPAIGN`).
    :return: список строк плана.
    """
    lines = [
        f"Кампания {spec.name!r} ({kind}), недельный бюджет={spec.weekly_budget}",
        f"Группа {spec.ad_group_name()!r}",
    ]
    if spec.href:
        lines.append(f"Ссылка: {spec.href}")
    lines.append(f"Модерация: {'да' if spec.moderate else 'нет'}")
    lines.append(f"Показы сразу после модерации: {'да' if spec.serve else 'нет'}")
    lines.append(f"Ожидание терминального статуса: {'да' if spec.wait_status else 'нет'}")
    return lines


def result_ids_of(items: Sequence[Mapping[str, Any]], key: str = "Id") -> List[int]:
    """Достать целочисленные ID из результатов batch-операции.

    :param items: элементы `AddResults` и подобных.
    :param key: имя поля с ID.
    :return: список ID в порядке элементов.
    """
    ids: List[int] = []
    for item in items:
        value = item.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            ids.append(value)
        elif isinstance(value, str) and value.lstrip("-").isdigit():
            ids.append(int(value))
    return ids


def load_env(path: Optional[Union[str, "os.PathLike[str]"]] = None) -> None:
    """Подгрузить переменные окружения из `.env` без внешних зависимостей.

    Существующие переменные окружения не перезаписываются: файл дополняет
    окружение, но не имеет над ним приоритета. Значения секретов нигде не
    печатаются.

    :param path: путь к файлу; None — `.env` в корне репозитория.
    """
    env_path = (
        Path(path)
        if path is not None
        else Path(__file__).resolve().parent.parent / ".env"
    )
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.debug(".env не прочитан: %s", exc)
        return
    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, _, value = entry.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


#: Префиксы имён, которые считаются тестовыми сущностями.
TEST_NAME_MARKERS = ("E2E", "TEST", "ТЕСТ", "ТЕСТОВАЯ", "SMOKE")


def ensure_test_name(name: str, *, confirm: bool = False) -> None:
    """Убедиться, что запуск не трогает «настоящие» сущности бизнеса.

    Автоматический запуск реальной кампании запрещён правилом D9, поэтому
    имя должно явно выглядеть как тестовое (`E2E`, `TEST`, `ТЕСТ`...), а
    иначе требуется явный `confirm=True`.

    :param name: имя кампании/группы запуска.
    :param confirm: явное подтверждение владельцем скрипта.
    :raises ValidationError: имя не выглядит тестовым, а `confirm` не задан.
    """
    if confirm:
        return
    upper = name.upper()
    if any(marker in upper for marker in TEST_NAME_MARKERS):
        return
    raise ValidationError(
        f"Имя {name!r} не похоже на тестовое. Скрипт запускает только "
        "техническую возможность на тестовых сущностях (D9): добавьте в имя "
        "префикс E2E/TEST либо передайте confirm=True, если это осознанно"
    )


__all__ = [
    "DEFAULT_REUSE_CACHE_DIR",
    "ENV_REUSE_CACHE_DIR",
    "LaunchResult",
    "LaunchSpecBase",
    "LaunchStep",
    "PENDING_AD_STATUSES",
    "PartialIds",
    "PreflightResult",
    "REUSE_CACHE_FILENAME",
    "RollbackReport",
    "STEP_DONE",
    "STEP_FAILED",
    "STEP_PLANNED",
    "STEP_REUSED",
    "STEP_SKIPPED",
    "TERMINAL_AD_STATUSES",
    "TEST_NAME_MARKERS",
    "ensure_test_name",
    "ensure_weekly_budget",
    "file_digest",
    "load_env",
    "moderate_ads",
    "plan_lines",
    "poll_ads",
    "preflight",
    "resolve_geo",
    "result_ids_of",
    "resume_ads",
    "rollback",
    "single_result",
]
