"""`YandexDirectClient` — sync typed клиент Yandex.Direct API v5."""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

import requests

from ._transport import Transport
from .cache import JsonCache
from .config import DEFAULT_REPORT_TIMEOUT, Settings
from .exceptions import ValidationError
from .region_selector import RegionSelector
from .services.ad_extensions import AdExtensionService
from .services.ad_group_items import AdGroupItemService
from .services.ad_groups import AdGroupService
from .services.ad_images import AdImageService
from .services.ads import AdService
from .services.audience_targets import AudienceTargetService
from .services.campaigns import CampaignService
from .services.clients import ClientsService
from .services.creatives import CreativesService
from .services.dictionaries import DictionariesService
from .services.negative_keywords import NegativeKeywordService
from .services.reports import ReportService
from .services.retargeting_adjustments import RetargetingAdjustmentService
from .services.retargeting_conditions import RetargetingConditionService
from .services.retargeting_lists import RetargetingListService
from .services.targeting import TargetingService


class YandexDirectClient:
    """Sync клиент Yandex.Direct API v5.

    Использование::

        client = YandexDirectClient(token="...", client_login="...")

        campaigns = client.campaigns.list()
        ads = client.ads.list(campaign_ids=[123])
        keywords = client.ad_group_items.list(campaign_ids=[123])
        stats = client.reports.get_ad_stats(ad_ids=[a.id for a in ads])

    :param token: OAuth access token. Если None — из env.
    :param client_login: логин клиента Директа. Необязателен: нужен только для
        агентского доступа (обход клиентов). Если None — из env, а если его
        нет — заголовок `Client-Login` не отправляется.
    :param api_url: базовый URL API.
    :param api_version: версия API по умолчанию (`v5`; `v501` — ЕПК).
    :param validate: выполнять ли пред-отправочную валидацию payload'ов.
    :param daily_budget_cap: предохранительный лимит денежных операций
        (env `YANDEX_DIRECT_BUDGET_CAP`); превышение → `ValidationError` до сети.
    :param timeout: таймаут одного HTTP-запроса, сек.
    :param max_retries: максимум повторов при 429 и 202.
    :param rate_limit_rps: rate limit на стороне клиента (token bucket).
    :param readonly: если True — все mutating-методы падают с ValidationError.
    :param session: свой `requests.Session` (для переиспользования/тестов).
    :param report_timeout: максимум секунд ожидания готовности отчёта.
    :param cache: свой кэш справочников (по умолчанию — дисковый, 7 суток).
    """

    def __init__(
        self,
        token: Optional[str] = None,
        client_login: Optional[str] = None,
        *,
        api_url: Optional[str] = None,
        api_version: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        rate_limit_rps: Optional[float] = None,
        readonly: Optional[bool] = None,
        validate: Optional[bool] = None,
        daily_budget_cap: Optional[Decimal] = None,
        require_confirm_for_money: Optional[bool] = None,
        session: Optional[requests.Session] = None,
        report_timeout: float = DEFAULT_REPORT_TIMEOUT,
        cache: Optional[JsonCache] = None,
    ) -> None:
        env = Settings.from_env()
        self._settings: Settings = env.merged_with(
            token=token,
            client_login=client_login,
            api_url=api_url,
            api_version=api_version,
            timeout=timeout,
            max_retries=max_retries,
            rate_limit_rps=rate_limit_rps,
            readonly=readonly,
            validate=validate,
            daily_budget_cap=daily_budget_cap,
            require_confirm_for_money=require_confirm_for_money,
        )
        if not self._settings.token:
            raise ValidationError(
                "Не задан token (передан аргументом или через YANDEX_DIRECT_TOKEN)"
            )

        self._transport = Transport(
            self._settings,
            session=session,
            report_timeout=report_timeout,
        )

        ro = self._settings.readonly
        self._campaigns = CampaignService(self._transport, readonly=ro)
        self._ads = AdService(self._transport, readonly=ro)
        self._ad_groups = AdGroupService(self._transport, readonly=ro)
        self._ad_group_items = AdGroupItemService(self._transport, readonly=ro)
        self._retargeting_adjustments = RetargetingAdjustmentService(
            self._transport, readonly=ro
        )
        self._negative_keywords = NegativeKeywordService(
            self._transport, readonly=ro
        )
        self._audience_targets = AudienceTargetService(
            self._transport, readonly=ro
        )
        self._retargeting_conditions = RetargetingConditionService(
            self._transport, readonly=ro
        )
        self._ad_extensions = AdExtensionService(self._transport, readonly=ro)
        self._ad_images = AdImageService(self._transport, readonly=ro)
        self._creatives = CreativesService(self._transport)
        self._dictionaries = DictionariesService(self._transport, cache=cache)
        self._retargeting_lists = RetargetingListService(
            self._transport, readonly=ro
        )
        self._targeting = TargetingService(
            self._transport,
            dictionaries=self._dictionaries,
            retargeting_lists=self._retargeting_lists,
            readonly=ro,
        )
        self._clients = ClientsService(self._transport)
        self._reports = ReportService(self._transport)

    # -------- context manager --------
    def __enter__(self) -> "YandexDirectClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Закрыть внутреннюю сессию."""
        self._transport.close()

    # -------- properties --------
    @property
    def readonly(self) -> bool:
        return self._settings.readonly

    @property
    def client_login(self) -> Optional[str]:
        """Логин клиента Директа (None — прямой доступ без агентского обхода)."""
        return self._settings.client_login

    @property
    def api_url(self) -> str:
        return self._transport.api_url

    @property
    def api_version(self) -> str:
        """Версия Direct API, используемая по умолчанию (`v5` или `v501`)."""
        return self._transport.api_version

    @property
    def validate(self) -> bool:
        """Включена ли пред-отправочная валидация payload'ов."""
        return self._settings.validate

    # -------- namespaces --------
    @property
    def campaigns(self) -> CampaignService:
        """Операции над кампаниями."""
        return self._campaigns

    @property
    def ads(self) -> AdService:
        """Операции над объявлениями."""
        return self._ads

    @property
    def ad_groups(self) -> AdGroupService:
        """Операции над группами объявлений."""
        return self._ad_groups

    @property
    def ad_group_items(self) -> AdGroupItemService:
        """Операции над ключевыми фразами."""
        return self._ad_group_items

    @property
    def retargeting_adjustments(self) -> RetargetingAdjustmentService:
        """Операции над корректировками по ретаргетинг-сегментам."""
        return self._retargeting_adjustments

    @property
    def negative_keywords(self) -> NegativeKeywordService:
        """Операции над наборами минус-фраз (NegativeKeywordSharedSets)."""
        return self._negative_keywords

    @property
    def audience_targets(self) -> AudienceTargetService:
        """Операции над условиями нацеливания на аудиторию."""
        return self._audience_targets

    @property
    def retargeting_conditions(self) -> RetargetingConditionService:
        """Операции над условиями ретаргетинга (через API audiencetargets)."""
        return self._retargeting_conditions

    @property
    def ad_extensions(self) -> AdExtensionService:
        """Операции над расширениями объявлений (быстрые ссылки, уточнения)."""
        return self._ad_extensions

    @property
    def ad_images(self) -> AdImageService:
        """Операции над изображениями объявлений (загрузка, чтение, удаление)."""
        return self._ad_images

    @property
    def creatives(self) -> CreativesService:
        """Чтение креативов объявлений (`creatives/get`)."""
        return self._creatives

    @property
    def dictionaries(self) -> DictionariesService:
        """Справочники Директа: гео, интересы, сегменты, типы объявлений."""
        return self._dictionaries

    @property
    def retargeting_lists(self) -> RetargetingListService:
        """Сегменты ретаргетинга (`retargetinglists`): add/update/delete/get."""
        return self._retargeting_lists

    @property
    def targeting(self) -> TargetingService:
        """Таргетинг: демография, интересы, сборка условий нацеливания."""
        return self._targeting

    @property
    def clients(self) -> ClientsService:
        """Параметры клиента и его лимиты."""
        return self._clients

    @property
    def reports(self) -> ReportService:
        """Отчёты и статистика."""
        return self._reports

    # -------- составной хелпер гео (F-1.2) --------
    def regions(self, selector: RegionSelector) -> List[int]:
        """Резолвнуть `RegionSelector` через справочник клиента.

        Короткий путь к `RegionSelector.resolve(self.dictionaries)`: код
        «исключить гео» читается как «получить список ID регионов».

        :param selector: описание гео (включения/исключения).
        :return: список ID регионов для `RegionIds`.
        :raises ValidationError: неизвестный/неоднозначный регион или пустой
            результат.
        """
        return selector.resolve(self.dictionaries)


__all__ = ["YandexDirectClient"]
