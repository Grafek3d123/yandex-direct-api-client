"""Билдеры payload'ов рекламных кампаний (F-2A.1).

Состав полей сверен с официальной документацией (снимок 30.09.2026):

- https://yandex.ru/dev/direct/doc/ru/campaigns/add-cpm-banner-campaign.md
- https://yandex.ru/dev/direct/doc/ru/campaigns/update-cpm-banner-campaign.md
- https://yandex.ru/dev/direct/doc/ru/campaigns/add-text-campaign.md

Ключевые отличия от «наивного» payload'а:

- типоспецифичные поля лежат во **вложенной** структуре (`CpmBannerCampaign`,
  `TextCampaign`), а не в корне элемента `Campaigns[]`;
- бюджет CPM-кампании — **недельный** и задаётся стратегией:
  `CpmBannerCampaign.BiddingStrategy.Network.ManualCpm.WeeklySpendLimit`;
  `DailyBudget` у кампании — deprecated и оставлен escape-hatch'ом;
- показы на поиске у CPM-кампании выключены: `Search.BiddingStrategyType`
  допускает единственное значение `SERVING_OFF`;
- имя кампании — до 255 символов, `StartDate` при создании обязателен.

`SMART_CAMPAIGN` через API **не создаётся** (только статистика), поэтому
билдера для него нет — есть константа типа для чтения ответов.

Неизвестные и редкие поля передаются через `extra`/`bidding_strategy` —
escape-hatch вместо угадывания состава полей Яндекса (D7).
"""
from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from ..exceptions import ValidationError
from ..money import Money, to_money_units
from ..validation import CAMPAIGN_NAME_MAX_LENGTH, Validator

_logger = logging.getLogger(__name__)

#: Тип классической РСЯ-кампании (CPM).
CAMPAIGN_TYPE_CPM_BANNER = "CPM_BANNER_CAMPAIGN"

#: Тип текстовой (поисковой) кампании.
CAMPAIGN_TYPE_TEXT = "TEXT_CAMPAIGN"

#: Тип ЕПК-кампании (доступна только через v501, см. слой 2Б).
CAMPAIGN_TYPE_UNIFIED = "UNIFIED_CAMPAIGN"

#: Тип смарт-кампании: через API не создаётся, доступна только статистика.
CAMPAIGN_TYPE_SMART = "SMART_CAMPAIGN"

#: Показы на поиске у CPM-кампании всегда выключены.
CPM_SEARCH_STRATEGY_SERVING_OFF = "SERVING_OFF"

#: Ручное управление CPM в сетях — стратегия по умолчанию.
CPM_NETWORK_STRATEGY_MANUAL_CPM = "MANUAL_CPM"

#: Типы сетевой стратегии CPM-кампании (docs: CpmBannerCampaignNetworkStrategyTypeEnum).
CPM_NETWORK_STRATEGY_TYPES = (
    "MANUAL_CPM",
    "CP_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS",
    "WB_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS",
    "CP_MAXIMUM_IMPRESSIONS",
    "WB_MAXIMUM_IMPRESSIONS",
    "CP_AVERAGE_CPV",
    "WB_AVERAGE_CPV",
)

#: Типы поисковой стратегии текстовой кампании (docs: TextCampaignStrategyTypeEnum).
TEXT_SEARCH_STRATEGY_TYPES = (
    "HIGHEST_POSITION",
    "WB_MAXIMUM_CLICKS",
    "WB_MAXIMUM_CONVERSION_RATE",
    "AVERAGE_CPC",
    "AVERAGE_CPA",
    "AVERAGE_CRR",
    "PAY_FOR_CONVERSION",
    "PAY_FOR_CONVERSION_CRR",
    "WEEKLY_CLICK_PACKAGE",
    "SERVING_OFF",
)

#: Допустимые настройки CPM-кампании (docs: CpmBannerCampaignSettingsEnum).
CPM_SETTINGS_OPTIONS = (
    "ADD_METRICA_TAG",
    "ADD_OPENSTAT_TAG",
    "ADD_TO_FAVORITES",
    "ENABLE_SITE_MONITORING",
    "REQUIRE_SERVICING",
)

#: Цель показов видеоролика (docs: VideoTargetEnum).
VIDEO_TARGETS = ("VIEWS", "CLICKS")

#: Режим дневного бюджета (docs: DailyBudgetModeEnum).
DAILY_BUDGET_MODES = ("STANDARD", "DISTRIBUTED")

#: Максимум элементов в `ExcludedSitesForVideoAds`.
EXCLUDED_SITES_MAX = 100

#: Максимальная длина элемента `ExcludedSitesForVideoAds`.
EXCLUDED_SITE_MAX_LENGTH = 255


def _format_date(value: Optional[_dt.date]) -> Optional[str]:
    """Привести дату к строке `YYYY-MM-DD` для API.

    :param value: дата или None.
    :return: строка даты или None.
    """
    return value.isoformat() if value is not None else None


def _weekly_amount(value: Money, field: str) -> int:
    """Проверить бюджет и перевести его в единицы API (×1 000 000).

    :param value: сумма в валюте аккаунта.
    :param field: имя поля для сообщения об ошибке.
    :return: целое число единиц.
    :raises ValidationError: сумма неположительна или не является числом.
    """
    try:
        amount = to_money_units(value)
    except ValidationError as exc:
        raise ValidationError(f"{field}: {exc}") from exc
    if amount <= 0:
        raise ValidationError(f"{field} должен быть больше нуля")
    return amount


@dataclass
class FrequencyCap:
    """Ограничение частоты показов (`FrequencyCapSetting`).

    :param impressions: максимум показов одному пользователю за период.
    :param period_days: период в днях (1..30); None — на всю кампанию.
    """

    impressions: int
    period_days: Optional[int] = None

    def to_payload(self) -> Dict[str, Any]:
        """Тело `FrequencyCap`.

        :return: словарь для `CpmBannerCampaign.FrequencyCap`.
        :raises ValidationError: некорректное число показов или период.
        """
        if isinstance(self.impressions, bool) or self.impressions <= 0:
            raise ValidationError(
                f"FrequencyCap.Impressions должен быть положительным, "
                f"получено {self.impressions!r}"
            )
        payload: Dict[str, Any] = {"Impressions": int(self.impressions)}
        if self.period_days is not None:
            if not 1 <= self.period_days <= 30:
                raise ValidationError(
                    f"FrequencyCap.PeriodDays должен быть в диапазоне 1..30, "
                    f"получено {self.period_days}"
                )
            payload["PeriodDays"] = int(self.period_days)
        return payload


@dataclass
class CampaignBase:
    """Общие поля кампании: имя, даты, часовой пояс, уведомления.

    :param name: имя кампании (1..255 символов).
    :param start_date: дата старта; обязательна при создании.
    :param end_date: дата окончания; None — бессрочная кампания.
    :param time_zone: часовой пояс (`Europe/Moscow`); None — время клиента.
    :param tracking_params: UTM-метки одной строкой (`TrackingParams`).
    :param notification: уведомления (`Notification`: Sms/Email/Push).
    :param daily_budget: deprecated `DailyBudget` кампании (структура
        `{Amount, Mode}`); None — не передавать.
    :param extra: дополнительные поля тела запроса (escape-hatch).
    :param raw: неизвестные поля ответа кампании (заполняется `from_dict`).
    """

    name: str
    start_date: Optional[_dt.date] = None
    end_date: Optional[_dt.date] = None
    time_zone: Optional[str] = None
    tracking_params: Optional[str] = None
    notification: Optional[Mapping[str, Any]] = None
    daily_budget: Optional[Money] = None
    daily_budget_mode: Optional[str] = None
    extra: Mapping[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def _common_payload(self, *, require_start_date: bool) -> Dict[str, Any]:
        """Собрать общую часть тела (без типоспецифичного блока).

        :param require_start_date: требовать ли `StartDate` (при `add` — да).
        :return: словарь с общими полями.
        :raises ValidationError: если `StartDate` обязателен, но не задан.
        """
        payload: Dict[str, Any] = {"Name": self.name}
        if require_start_date and self.start_date is None:
            raise ValidationError(
                "StartDate обязателен при создании кампании (campaigns/add)"
            )
        if self.start_date is not None:
            payload["StartDate"] = _format_date(self.start_date)
        if self.end_date is not None:
            payload["EndDate"] = _format_date(self.end_date)
        if self.time_zone is not None:
            payload["TimeZone"] = self.time_zone
        if self.tracking_params:
            payload["TrackingParams"] = self.tracking_params
        if self.notification:
            payload["Notification"] = dict(self.notification)
        if self.daily_budget is not None:
            mode = self.daily_budget_mode or "STANDARD"
            if self.daily_budget_mode is None:
                _logger.warning(
                    "CampaignBase: daily_budget задан без daily_budget_mode — "
                    "SDK выбирает режим STANDARD за бизнес (передайте режим "
                    "явно: STANDARD/DISTRIBUTED)"
                )
            payload["DailyBudget"] = {
                "Amount": _weekly_amount(self.daily_budget, "DailyBudget.Amount"),
                "Mode": mode,
            }
        return payload

    def to_payload(self) -> Dict[str, Any]:
        """Тело кампании без типоспецифичного блока (общая часть).

        :return: словарь с общими полями.
        """
        return self._common_payload(require_start_date=True)

    def validate(self, *, enabled: bool = True) -> None:
        """Проверить общие поля кампании.

        :param enabled: False — пропустить проверки (режим `validate=False`).
        :raises ValidationError: при нарушении.
        """
        if not enabled:
            return
        validator = Validator(True)
        validator.name(self.name, field="Campaign.Name", max_length=CAMPAIGN_NAME_MAX_LENGTH)
        validator.date_range(self.start_date, self.end_date)
        if self.daily_budget_mode is not None and (
            self.daily_budget_mode not in DAILY_BUDGET_MODES
        ):
            raise ValidationError(
                f"DailyBudget.Mode: недопустимое значение {self.daily_budget_mode!r}; "
                f"разрешено: {', '.join(DAILY_BUDGET_MODES)}"
            )
        if self.daily_budget is not None:
            _weekly_amount(self.daily_budget, "DailyBudget.Amount")


@dataclass
class CpmBannerCampaign(CampaignBase):
    """Классическая РСЯ-кампания (`CPM_BANNER_CAMPAIGN`).

    Бюджет задаётся недельной суммой внутри сетевой стратегии. Ручная
    стратегия (`MANUAL_CPM`) — типовой сценарий: недельный бюджет равен
    `ManualCpm.WeeklySpendLimit`. Для остальных стратегий (максимум показов,
    снижение цены повторных показов, максимум просмотров видео) передаётся
    escape-hatch `bidding_strategy` — целиком секция `Network`.

    :param weekly_budget: недельный бюджет в валюте аккаунта.
    :param bidding_strategy: готовая секция `BiddingStrategy.Network`
        (escape-hatch для редких стратегий); взаимоисключающе с
        `weekly_budget`.
    :param counter_ids: счётчики Яндекс Метрики (`CounterIds.Items`).
    :param settings: настройки кампании (список `{Option, Value}`).
    :param frequency_cap: ограничение частоты показов.
    :param video_target: цель показов видеоролика (`VIEWS`/`CLICKS`).
    :param excluded_sites_for_video_ads: места показа, где видео не нужно.
    """

    weekly_budget: Optional[Money] = None
    bidding_strategy: Optional[Mapping[str, Any]] = None
    counter_ids: Optional[Sequence[int]] = None
    settings: Optional[Sequence[Mapping[str, Any]]] = None
    frequency_cap: Optional[FrequencyCap] = None
    video_target: Optional[str] = None
    excluded_sites_for_video_ads: Optional[Sequence[str]] = None

    def _search_strategy(self) -> Dict[str, Any]:
        """Секция стратегии показа на поиске (всегда выключена).

        :return: словарь `Search` секции `BiddingStrategy`.
        """
        return {"BiddingStrategyType": CPM_SEARCH_STRATEGY_SERVING_OFF}

    def _network_strategy(self) -> Dict[str, Any]:
        """Секция стратегии показа в сетях.

        :return: словарь `Network` секции `BiddingStrategy`.
        :raises ValidationError: не задана ни недельная сумма, ни готовая
            секция стратегии, либо заданы обе.
        """
        if self.bidding_strategy is not None:
            if self.weekly_budget is not None:
                raise ValidationError(
                    "Задайте либо weekly_budget, либо bidding_strategy, не оба"
                )
            return dict(self.bidding_strategy)
        if self.weekly_budget is None:
            raise ValidationError(
                "CpmBannerCampaign требует недельный бюджет: укажите "
                "weekly_budget или передайте готовую секцию bidding_strategy"
            )
        _logger.warning(
            "CpmBannerCampaign: weekly_budget задан без bidding_strategy — "
            "SDK выбирает сетевую стратегию MANUAL_CPM за бизнес. Чтобы "
            "выбрать стратегию явно, передайте bidding_strategy "
            "(полная секция BiddingStrategy.Network)"
        )
        return {
            "BiddingStrategyType": CPM_NETWORK_STRATEGY_MANUAL_CPM,
            "ManualCpm": {
                "WeeklySpendLimit": _weekly_amount(
                    self.weekly_budget, "WeeklySpendLimit"
                )
            },
        }

    def _type_payload(self) -> Dict[str, Any]:
        """Вложенный блок `CpmBannerCampaign`.

        :return: словарь типоспецифичных полей кампании.
        :raises ValidationError: при некорректных настройках или счётчиках.
        """
        block: Dict[str, Any] = {
            "BiddingStrategy": {
                "Search": self._search_strategy(),
                "Network": self._network_strategy(),
            }
        }
        validator = Validator(True)
        if self.counter_ids is not None:
            validator.ids(list(self.counter_ids), field="CounterIds")
            block["CounterIds"] = {"Items": [int(x) for x in self.counter_ids]}
        if self.settings is not None:
            items: List[Dict[str, Any]] = []
            for setting in self.settings:
                option = setting.get("Option")
                value = setting.get("Value")
                validator.one_of(
                    option, CPM_SETTINGS_OPTIONS, field="Settings.Option"
                )
                validator.one_of(value, ("YES", "NO"), field="Settings.Value")
                items.append({"Option": option, "Value": value})
            if items:
                block["Settings"] = items
        if self.frequency_cap is not None:
            block["FrequencyCap"] = self.frequency_cap.to_payload()
        if self.video_target is not None:
            validator.one_of(self.video_target, VIDEO_TARGETS, field="VideoTarget")
            block["VideoTarget"] = self.video_target
        if self.excluded_sites_for_video_ads is not None:
            sites = list(self.excluded_sites_for_video_ads)
            if len(sites) > EXCLUDED_SITES_MAX:
                raise ValidationError(
                    f"ExcludedSitesForVideoAds: не более {EXCLUDED_SITES_MAX} "
                    f"элементов, передано {len(sites)}"
                )
            for site in sites:
                if not site or len(site) > EXCLUDED_SITE_MAX_LENGTH:
                    raise ValidationError(
                        f"ExcludedSitesForVideoAds: элементы должны быть непустыми "
                        f"и не длиннее {EXCLUDED_SITE_MAX_LENGTH} символов"
                    )
            block["ExcludedSitesForVideoAds"] = {"Items": sites}
        return block

    def to_payload(self) -> Dict[str, Any]:
        """Тело `campaigns/add` для РСЯ-кампании.

        :return: словарь, готовый к отправке.
        :raises ValidationError: если не задана стратегия или нарушены
            ограничения на настройки/счётчики.
        """
        payload = self._common_payload(require_start_date=True)
        payload["CpmBannerCampaign"] = self._type_payload()
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload

    def to_update_payload(self, campaign_id: int) -> Dict[str, Any]:
        """Тело `campaigns/update` (Id + изменяемые поля).

        Структура `CpmBannerCampaign` при обновлении совпадает с созданием,
        поэтому блок собирается тем же кодом.

        :param campaign_id: ID обновляемой кампании.
        :return: словарь для запроса обновления.
        """
        payload: Dict[str, Any] = {"Id": int(campaign_id)}
        payload.update(self._common_payload(require_start_date=False))
        if self.weekly_budget is not None or self.bidding_strategy is not None:
            payload["CpmBannerCampaign"] = self._type_payload()
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload


@dataclass
class TextCampaign(CampaignBase):
    """Текстовая (поисковая) кампания (`TEXT_CAMPAIGN`).

    Типовой сценарий — ручная стратегия в сетях: `AVERAGE_CPC` с недельным
    бюджетом `AverageCpc.WeeklySpendLimit`. Показы в сетях по умолчанию
    выключены (`Network.BiddingStrategyType = SERVING_OFF`).

    :param weekly_budget: недельный бюджет в валюте аккаунта.
    :param bidding_strategy: готовая секция `BiddingStrategy.Search`
        (escape-hatch); взаимоисключающе с `weekly_budget`.
    :param counter_ids: счётчики Яндекс Метрики.
    :param network_enabled: включить ли показы в сетях у текстовой кампании.
        `None` — выключить за бизнес с `logging.warning`; `True`/`False` — явно.
    """

    weekly_budget: Optional[Money] = None
    bidding_strategy: Optional[Mapping[str, Any]] = None
    counter_ids: Optional[Sequence[int]] = None
    network_enabled: Optional[bool] = None

    def _search_strategy(self) -> Dict[str, Any]:
        """Секция стратегии показа на поиске.

        :return: словарь `Search` секции `BiddingStrategy`.
        :raises ValidationError: не задана недельная сумма или готовая секция.
        """
        if self.bidding_strategy is not None:
            if self.weekly_budget is not None:
                raise ValidationError(
                    "Задайте либо weekly_budget, либо bidding_strategy, не оба"
                )
            return dict(self.bidding_strategy)
        if self.weekly_budget is None:
            raise ValidationError(
                "TextCampaign требует недельный бюджет: укажите weekly_budget "
                "или передайте готовую секцию bidding_strategy"
            )
        _logger.warning(
            "TextCampaign: weekly_budget задан без bidding_strategy — "
            "SDK выбирает поисковую стратегию AVERAGE_CPC за бизнес. "
            "Чтобы выбрать стратегию явно, передайте bidding_strategy "
            "(полная секция BiddingStrategy.Search)"
        )
        return {
            "BiddingStrategyType": "AVERAGE_CPC",
            "AverageCpc": {
                "WeeklySpendLimit": _weekly_amount(
                    self.weekly_budget, "WeeklySpendLimit"
                )
            },
        }

    def _type_payload(self) -> Dict[str, Any]:
        """Вложенный блок `TextCampaign`.

        :return: словарь типоспецифичных полей кампании.
        """
        network_enabled = self.network_enabled
        if network_enabled is None:
            _logger.warning(
                "TextCampaign: network_enabled не задан — SDK выключает сеть "
                "(SERVING_OFF) за бизнес; передайте network_enabled=True, чтобы "
                "включить показы в сетях"
            )
            network_enabled = False
        block: Dict[str, Any] = {
            "BiddingStrategy": {
                "Search": self._search_strategy(),
                "Network": {
                    "BiddingStrategyType": (
                        "SERVING_OFF" if not network_enabled else "MAX_CPM"
                    )
                },
            }
        }
        if self.counter_ids is not None:
            Validator(True).ids(list(self.counter_ids), field="CounterIds")
            block["CounterIds"] = {"Items": [int(x) for x in self.counter_ids]}
        return block

    def to_payload(self) -> Dict[str, Any]:
        """Тело `campaigns/add` для текстовой кампании.

        :return: словарь, готовый к отправке.
        :raises ValidationError: если не задана стратегия или бюджет.
        """
        payload = self._common_payload(require_start_date=True)
        payload["TextCampaign"] = self._type_payload()
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload

    def to_update_payload(self, campaign_id: int) -> Dict[str, Any]:
        """Тело `campaigns/update` (Id + изменяемые поля).

        :param campaign_id: ID обновляемой кампании.
        :return: словарь для запроса обновления.
        """
        payload: Dict[str, Any] = {"Id": int(campaign_id)}
        payload.update(self._common_payload(require_start_date=False))
        if self.weekly_budget is not None or self.bidding_strategy is not None:
            payload["TextCampaign"] = self._type_payload()
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload


#: Соответствие «тип стратегии ЕПК → ключ в BiddingStrategy».
UNIFIED_STRATEGY_KEYS: Mapping[str, str] = {
    "WB_MAXIMUM_CLICKS": "WbMaximumClicks",
    "WB_MAXIMUM_CONVERSION_RATE": "WbMaximumConversionRate",
    "AVERAGE_CPC": "AverageCpc",
    "AVERAGE_CPA": "AverageCpa",
    "AVERAGE_CRR": "AverageCrr",
    "PAY_FOR_CONVERSION": "PayForConversion",
    "PAY_FOR_CONVERSION_CRR": "PayForConversionCrr",
    "HIGHEST_POSITION": "HighestPosition",
}

#: Стратегии ЕПК без собственной структуры параметров.
UNIFIED_STRATEGIES_WITHOUT_BLOCK = ("SERVING_OFF", "NETWORK_DEFAULT")

#: Стратегии ЕПК, которым обязателен `GoalId`.
UNIFIED_STRATEGY_REQUIRES_GOAL = (
    "WB_MAXIMUM_CONVERSION_RATE",
    "AVERAGE_CPA",
    "AVERAGE_CRR",
    "PAY_FOR_CONVERSION",
    "PAY_FOR_CONVERSION_CRR",
)

#: Стратегии ЕПК, которым обязателен `WeeklySpendLimit`.
UNIFIED_STRATEGY_REQUIRES_BUDGET = (
    "WB_MAXIMUM_CLICKS",
    "WB_MAXIMUM_CONVERSION_RATE",
    "AVERAGE_CPA",
    "AVERAGE_CRR",
    "PAY_FOR_CONVERSION",
    "PAY_FOR_CONVERSION_CRR",
)

#: Допустимые настройки ЕПК (docs: UnifiedCampaignSettingsEnum).
UNIFIED_SETTINGS_OPTIONS = (
    "ADD_METRICA_TAG",
    "ADD_TO_FAVORITES",
    "ENABLE_SITE_MONITORING",
    "REQUIRE_SERVICING",
    "ENABLE_COMPANY_INFO",
    "CAMPAIGN_EXACT_PHRASE_MATCHING_ENABLED",
    "ALTERNATIVE_TEXTS_ENABLED",
)

#: Модели атрибуции (docs: AttributionModelEnum).
ATTRIBUTION_MODELS = ("FCCD", "LC", "LSCCD", "AUTO")

#: Максимум целей в `PriorityGoals.Items` (docs: campaigns/get-unified-campaign).
PRIORITY_GOALS_MAX = 30


@dataclass
class PriorityGoal:
    """Ключевая цель Метрики ЕПК (`PriorityGoals.Items`).

    Цели хранятся по ID: SDK не выбирает цели за пользователя.

    :param goal_id: ID цели Метрики.
    :param value: вес цели (обычно 1; до 100 при нескольких целях).
        По умолчанию `None` → SDK назначает `1` с `logging.warning`.
    :param is_metrika_source_of_value: брать ли значение из Метрики.
    :param operation: операция обновления (только `SET`); None — не указывать.
    """

    goal_id: int
    value: Optional[int] = None
    is_metrika_source_of_value: Optional[bool] = None
    operation: Optional[str] = None

    def __post_init__(self) -> None:
        """Подставить вес цели по умолчанию, если не задан.

        :raises ValidationError: нет (вес проверяется в `to_payload`).
        """
        if self.value is None:
            _logger.warning(
                "PriorityGoal: value не задан — SDK назначает вес 1 "
                "(передайте value явно)"
            )
            self.value = 1

    def to_payload(self) -> Dict[str, Any]:
        """Тело одной цели.

        :return: словарь цели для `UnifiedCampaign.PriorityGoals`.
        :raises ValidationError: некорректные ID, значение или операция.
        """
        validator = Validator(True)
        validator.ids([self.goal_id], field="PriorityGoals.GoalId")
        value = self.value
        if value is None:
            raise ValidationError(
                "PriorityGoals.Value: не задан (ожидалось нормализовано)"
            )
        if isinstance(value, bool) or value <= 0:
            raise ValidationError(
                f"PriorityGoals.Value должен быть положительным, получено {value!r}"
            )
        payload: Dict[str, Any] = {
            "GoalId": int(self.goal_id),
            "Value": int(value),
        }
        if self.is_metrika_source_of_value is not None:
            payload["IsMetrikaSourceOfValue"] = (
                "YES" if self.is_metrika_source_of_value else "NO"
            )
        if self.operation is not None:
            if self.operation != "SET":
                raise ValidationError(
                    f"PriorityGoals.Operation: допустимо только 'SET', получено "
                    f"{self.operation!r}"
                )
            payload["Operation"] = "SET"
        return payload


@dataclass
class UnifiedStrategy:
    """Стратегия показа ЕПК для одного места показа (поиск или сети).

    :param strategy: тип стратегии (см. `UNIFIED_STRATEGY_KEYS` и
        `UNIFIED_STRATEGIES_WITHOUT_BLOCK`).
    :param weekly_budget: недельный бюджет (обязателен для стратегий из
        `UNIFIED_STRATEGY_REQUIRES_BUDGET`).
    :param goal_id: цель Метрики (обязательна для стратегий из
        `UNIFIED_STRATEGY_REQUIRES_GOAL`).
    :param bid_ceiling: ограничение ставки (`BidCeiling`), если поддерживается.
    :param average_cpc: ставка для `AVERAGE_CPC` (обязательна у этой стратегии).
    :param extra: дополнительные поля стратегии (escape-hatch, D7).
    """

    strategy: str
    weekly_budget: Optional[Money] = None
    goal_id: Optional[int] = None
    bid_ceiling: Optional[Money] = None
    average_cpc: Optional[Money] = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self, *, placement: str) -> Dict[str, Any]:
        """Секция стратегии для `Search` или `Network`.

        :param placement: `Search` или `Network`.
        :return: словарь `BiddingStrategyType` плюс структура стратегии.
        :raises ValidationError: неизвестная стратегия, стратегия не
            поддерживается в этом месте показа или не хватает обязательных
            полей.
        """
        allowed = tuple(UNIFIED_STRATEGY_KEYS) + UNIFIED_STRATEGIES_WITHOUT_BLOCK
        Validator(True).one_of(self.strategy, allowed, field="BiddingStrategyType")
        if placement == "Search" and self.strategy == "NETWORK_DEFAULT":
            raise ValidationError(
                "NETWORK_DEFAULT применим только к показу в сетях"
            )
        if placement == "Network" and self.strategy == "HIGHEST_POSITION":
            raise ValidationError(
                "HIGHEST_POSITION применим только к показу на поиске"
            )
        payload: Dict[str, Any] = {"BiddingStrategyType": self.strategy}
        if self.strategy in UNIFIED_STRATEGIES_WITHOUT_BLOCK:
            if self.weekly_budget is not None or self.goal_id is not None:
                raise ValidationError(
                    f"Стратегия {self.strategy} не принимает недельный бюджет "
                    "или цель"
                )
            return payload
        key = UNIFIED_STRATEGY_KEYS[self.strategy]
        block: Dict[str, Any] = {}
        if self.strategy in UNIFIED_STRATEGY_REQUIRES_BUDGET:
            if self.weekly_budget is None:
                raise ValidationError(
                    f"Стратегия {self.strategy} требует недельный бюджет "
                    "(weekly_budget)"
                )
            block["WeeklySpendLimit"] = _weekly_amount(
                self.weekly_budget, f"{key}.WeeklySpendLimit"
            )
        elif self.weekly_budget is not None:
            block["WeeklySpendLimit"] = _weekly_amount(
                self.weekly_budget, f"{key}.WeeklySpendLimit"
            )
        if self.strategy in UNIFIED_STRATEGY_REQUIRES_GOAL:
            if self.goal_id is None:
                raise ValidationError(
                    f"Стратегия {self.strategy} требует goal_id — цели Метрики "
                    "выбирает пользователь"
                )
            Validator(True).ids([self.goal_id], field=f"{key}.GoalId")
            block["GoalId"] = int(self.goal_id)
        if self.strategy == "AVERAGE_CPC" and self.average_cpc is None:
            raise ValidationError(
                "Стратегия AVERAGE_CPC требует ставку average_cpc "
                "(BiddingStrategy.AverageCpc.AverageCpc)"
            )
        if self.bid_ceiling is not None:
            block["BidCeiling"] = _weekly_amount(
                self.bid_ceiling, f"{key}.BidCeiling"
            )
        if self.average_cpc is not None:
            block["AverageCpc"] = _weekly_amount(
                self.average_cpc, f"{key}.AverageCpc"
            )
        for extra_key, extra_value in self.extra.items():
            block.setdefault(extra_key, extra_value)
        payload[key] = block
        return payload


@dataclass
class UnifiedCampaign(CampaignBase):
    """Единая перфоманс-кампания (`UNIFIED_CAMPAIGN`, слой 2Б).

    Создаётся и обновляется через **v501**: `campaigns/add` с вложенным
    блоком `UnifiedCampaign`. Гео задаётся не в кампании, а в группе
    (`UnifiedAdGroup.RegionIds`), поэтому в билдере кампании его нет.

    :param search: стратегия показа на поиске.
    :param network: стратегия показа в сетях.
    :param counter_ids: счётчики Яндекс Метрики (`CounterIds.Items`).
    :param priority_goals: ключевые цели Метрики (по ID, не по названиям).
    :param settings: настройки кампании (список `{Option, Value}`).
    :param attribution_model: модель атрибуции.
    :param negative_keywords_shared_set_ids: наборы минус-фраз.
    """

    search: Optional[UnifiedStrategy] = None
    network: Optional[UnifiedStrategy] = None
    counter_ids: Optional[Sequence[int]] = None
    priority_goals: Optional[Sequence[PriorityGoal]] = None
    settings: Optional[Sequence[Mapping[str, Any]]] = None
    attribution_model: Optional[str] = None
    negative_keywords_shared_set_ids: Optional[Sequence[int]] = None

    def _type_payload(self) -> Dict[str, Any]:
        """Вложенный блок `UnifiedCampaign`.

        :return: словарь типоспецифичных полей кампании.
        :raises ValidationError: при нарушении ограничений API.
        """
        validator = Validator(True)
        search = self.search
        if search is None:
            _logger.warning(
                "UnifiedCampaign: search стратегия не задана — SDK выбирает "
                "AVERAGE_CPC за бизнес (передайте search явно)"
            )
            search = UnifiedStrategy(strategy="AVERAGE_CPC")
        network = self.network
        if network is None:
            _logger.warning(
                "UnifiedCampaign: network стратегия не задана — SDK выбирает "
                "NETWORK_DEFAULT за бизнес (передайте network явно)"
            )
            network = UnifiedStrategy(strategy="NETWORK_DEFAULT")
        block: Dict[str, Any] = {
            "BiddingStrategy": {
                "Search": search.to_payload(placement="Search"),
                "Network": network.to_payload(placement="Network"),
            }
        }
        if self.counter_ids is not None:
            validator.ids(list(self.counter_ids), field="CounterIds")
            block["CounterIds"] = {"Items": [int(x) for x in self.counter_ids]}
        if self.priority_goals is not None:
            goals = list(self.priority_goals)
            if len(goals) > PRIORITY_GOALS_MAX:
                raise ValidationError(
                    f"PriorityGoals: не более {PRIORITY_GOALS_MAX} целей, "
                    f"передано {len(goals)}"
                )
            block["PriorityGoals"] = {
                "Items": [goal.to_payload() for goal in goals]
            }
        if self.settings is not None:
            items: List[Dict[str, Any]] = []
            for setting in self.settings:
                option = setting.get("Option")
                value = setting.get("Value")
                validator.one_of(option, UNIFIED_SETTINGS_OPTIONS, field="Settings.Option")
                validator.one_of(value, ("YES", "NO"), field="Settings.Value")
                items.append({"Option": option, "Value": value})
            if items:
                block["Settings"] = items
        if self.attribution_model is not None:
            validator.one_of(
                self.attribution_model, ATTRIBUTION_MODELS, field="AttributionModel"
            )
            block["AttributionModel"] = self.attribution_model
        if self.negative_keywords_shared_set_ids is not None:
            validator.ids(
                list(self.negative_keywords_shared_set_ids),
                field="NegativeKeywordSharedSetIds",
            )
            block["NegativeKeywordSharedSetIds"] = {
                "Items": [int(x) for x in self.negative_keywords_shared_set_ids]
            }
        return block

    def to_payload(self) -> Dict[str, Any]:
        """Тело `campaigns/add` для ЕПК (маршрутизируется на v501).

        :return: словарь, готовый к отправке.
        :raises ValidationError: если нарушены ограничения стратегии или полей.
        """
        self.validate()
        payload = self._common_payload(require_start_date=True)
        payload["UnifiedCampaign"] = self._type_payload()
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload

    def to_update_payload(self, campaign_id: int) -> Dict[str, Any]:
        """Тело `campaigns/update` для ЕПК (Id + изменяемые поля).

        :param campaign_id: ID обновляемой ЕПК-кампании.
        :return: словарь для запроса обновления.
        :raises ValidationError: если нарушены ограничения стратегии или полей.
        """
        self.validate()
        payload: Dict[str, Any] = {"Id": int(campaign_id)}
        payload.update(self._common_payload(require_start_date=False))
        payload["UnifiedCampaign"] = self._type_payload()
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload


#: Тип билдера кампании, принимаемый `build_campaign` и `campaigns.create`.
CampaignBuilder = Union[CpmBannerCampaign, TextCampaign, UnifiedCampaign]

#: Соответствие «вид кампании → класс-билдер».
CAMPAIGN_BUILDERS: Mapping[str, Any] = {
    CAMPAIGN_TYPE_CPM_BANNER: CpmBannerCampaign,
    CAMPAIGN_TYPE_TEXT: TextCampaign,
    CAMPAIGN_TYPE_UNIFIED: UnifiedCampaign,
}


def campaign_type_of(builder: CampaignBase) -> str:
    """Определить тип кампании по классу-билдеру.

    :param builder: билдер кампании.
    :return: строка типа кампании для API.
    :raises ValidationError: неизвестный класс-билдер.
    """
    for kind, cls in CAMPAIGN_BUILDERS.items():
        if isinstance(builder, cls):
            return kind
    raise ValidationError(
        f"Неизвестный тип билдера кампании: {type(builder).__name__}"
    )


def build_campaign(kind: str, **kwargs: Any) -> CampaignBuilder:
    """Собрать билдер кампании по её типу.

    :param kind: тип кампании: `CPM_BANNER_CAMPAIGN`, `TEXT_CAMPAIGN` или
        `UNIFIED_CAMPAIGN` (ЕПК, только v501).
    :param kwargs: поля конструктора выбранного билдера.
    :return: экземпляр билдера с провалидированными полями.
    :raises ValidationError: неизвестный тип кампании или нарушение полей.
    """
    builder_cls = CAMPAIGN_BUILDERS.get(kind)
    if builder_cls is None:
        known = ", ".join(sorted(CAMPAIGN_BUILDERS))
        raise ValidationError(f"Неизвестный тип кампании {kind!r}; доступно: {known}")
    builder: CampaignBuilder = builder_cls(**kwargs)
    builder.validate()
    return builder


def campaign_payloads(
    builders: Sequence[CampaignBuilder],
) -> List[Dict[str, Any]]:
    """Собрать тела для batch-запроса `campaigns/add`.

    :param builders: билдеры кампаний.
    :return: список словарей для `params.Campaigns`.
    :raises ValidationError: если какой-либо билдер невалиден.
    """
    payloads: List[Dict[str, Any]] = []
    for builder in builders:
        builder.validate()
        payloads.append(builder.to_payload())
    return payloads


__all__ = [
    "ATTRIBUTION_MODELS",
    "CAMPAIGN_BUILDERS",
    "CAMPAIGN_TYPE_CPM_BANNER",
    "CAMPAIGN_TYPE_SMART",
    "CAMPAIGN_TYPE_TEXT",
    "CAMPAIGN_TYPE_UNIFIED",
    "CPM_NETWORK_STRATEGY_MANUAL_CPM",
    "CPM_NETWORK_STRATEGY_TYPES",
    "CPM_SEARCH_STRATEGY_SERVING_OFF",
    "CPM_SETTINGS_OPTIONS",
    "CampaignBase",
    "CampaignBuilder",
    "CpmBannerCampaign",
    "FrequencyCap",
    "PRIORITY_GOALS_MAX",
    "PriorityGoal",
    "TextCampaign",
    "UNIFIED_SETTINGS_OPTIONS",
    "UNIFIED_STRATEGIES_WITHOUT_BLOCK",
    "UNIFIED_STRATEGY_KEYS",
    "UNIFIED_STRATEGY_REQUIRES_BUDGET",
    "UNIFIED_STRATEGY_REQUIRES_GOAL",
    "UnifiedCampaign",
    "UnifiedStrategy",
    "VIDEO_TARGETS",
    "build_campaign",
    "campaign_payloads",
    "campaign_type_of",
]
