"""`YandexDirectClient` — sync typed клиент Yandex.Direct API v5."""
from __future__ import annotations

from typing import Optional

import requests

from ._transport import Transport
from .config import DEFAULT_REPORT_TIMEOUT, Settings
from .exceptions import ValidationError
from .services.ad_groups import AdGroupService
from .services.ads import AdService
from .services.campaigns import CampaignService
from .services.reports import ReportService


class YandexDirectClient:
    """Sync клиент Yandex.Direct API v5.

    Использование::

        client = YandexDirectClient(token="...", client_login="...")

        campaigns = client.campaigns.list()
        ads = client.ads.list(campaign_ids=[123])
        stats = client.reports.get_ad_stats(ad_ids=[a.id for a in ads])

    :param token: OAuth access token. Если None — из env.
    :param client_login: логин клиента Директа. Если None — из env.
    :param api_url: базовый URL API.
    :param timeout: таймаут одного HTTP-запроса, сек.
    :param max_retries: максимум повторов при 429 и 202.
    :param rate_limit_rps: rate limit на стороне клиента (token bucket).
    :param readonly: если True — все mutating-методы падают с ValidationError.
    :param session: свой `requests.Session` (для переиспользования/тестов).
    :param report_timeout: максимум секунд ожидания готовности отчёта.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        client_login: Optional[str] = None,
        *,
        api_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        rate_limit_rps: Optional[float] = None,
        readonly: Optional[bool] = None,
        session: Optional[requests.Session] = None,
        report_timeout: float = DEFAULT_REPORT_TIMEOUT,
    ) -> None:
        env = Settings.from_env()
        self._settings: Settings = env.merged_with(
            token=token,
            client_login=client_login,
            api_url=api_url,
            timeout=timeout,
            max_retries=max_retries,
            rate_limit_rps=rate_limit_rps,
            readonly=readonly,
        )
        if not self._settings.token:
            raise ValidationError(
                "Не задан token (передан аргументом или через YANDEX_DIRECT_TOKEN)"
            )
        if not self._settings.client_login:
            raise ValidationError(
                "Не задан client_login (передан аргументом или через "
                "YANDEX_DIRECT_CLIENT_LOGIN)"
            )

        self._transport = Transport(
            self._settings,
            session=session,
            report_timeout=report_timeout,
        )

        ro = self._settings.readonly
        self._campaigns = CampaignService(self._transport, readonly=ro)
        self._ads = AdService(self._transport, readonly=ro)
        self._ad_groups = AdGroupService(self._transport)
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
    def client_login(self) -> str:
        login = self._settings.client_login
        if login is None:  # pragma: no cover
            raise ValidationError("client_login не задан")
        return login

    @property
    def api_url(self) -> str:
        return self._transport.api_url

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
    def reports(self) -> ReportService:
        """Отчёты и статистика."""
        return self._reports


__all__ = ["YandexDirectClient"]
