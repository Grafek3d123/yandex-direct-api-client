"""Операции над бюджетами и стратегиями кампаний (слой 3, D6/D7).

Бюджеты в Директе живут в стратегии, а не «поверх» кампании:

- недельный бюджет ЕПК — `UnifiedCampaign.BiddingStrategy.Search.<Стратегия>.WeeklySpendLimit`;
- недельный бюджет CPM-РСЯ — `CpmBannerCampaign.BiddingStrategy.Network.ManualCpm.WeeklySpendLimit`;
- `DailyBudget` кампании — deprecated и оставлен escape-hatch'ом.

Поэтому `set_weekly_budget` требует знать **тип** кампании и её текущую
стратегию: тип берётся из `campaigns/get`, стратегия — из ответа там же.
После изменения (по умолчанию) выполняется `campaigns/get` и значения
сверяются: расхождение — `ApiError` с обоими числами, а не тихий успех.

Предохранители (F-3.4):
- `daily_budget_cap` (env `YANDEX_DIRECT_BUDGET_CAP`) — превышение даёт
  `ValidationError` **до** сети;
- `require_confirm_for_money=True` по умолчанию — денежные мутации требуют
  `confirm=True`.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..exceptions import ApiError, ValidationError
from ..models.bid_strategy import (
    STRATEGY_MANUAL_CPM,
    BidStrategy,
    strategy_payload,
    weekly_budget_of,
)
from ..money import Money, from_money_units, to_decimal, to_money_units
from ._base import ensure_confirmed

#: Куда класть недельный бюджет в теле `campaigns/update` для каждого типа.
_WEEKLY_BUDGET_PATHS: Dict[str, Sequence[str]] = {
    "CPM_BANNER_CAMPAIGN": ("CpmBannerCampaign", "BiddingStrategy", "Network", "ManualCpm"),
    "UNIFIED_CAMPAIGN": ("UnifiedCampaign", "BiddingStrategy", "Search"),
}

#: Типы кампаний, поддерживающие недельный бюджет.
WEEKLY_BUDGET_CAMPAIGN_TYPES = tuple(_WEEKLY_BUDGET_PATHS)


@dataclass
class CampaignBudget:
    """Бюджет кампании, прочитанный из ответа API.

    :param campaign_id: ID кампании.
    :param type: тип кампании (`CPM_BANNER_CAMPAIGN`, `UNIFIED_CAMPAIGN`, ...).
    :param weekly: недельный бюджет (`Decimal`) либо None.
    :param daily: дневной бюджет (`Decimal`, deprecated) либо None.
    :param strategy: тип текущей стратегии, если удалось определить.
    """

    campaign_id: int
    type: Optional[str] = None
    weekly: Optional[Decimal] = None
    daily: Optional[Decimal] = None
    strategy: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Представить бюджет словарём для логов и отчётов.

        :return: словарь с полями бюджета.
        """
        return {
            "CampaignId": self.campaign_id,
            "Type": self.type,
            "Weekly": str(self.weekly) if self.weekly is not None else None,
            "Daily": str(self.daily) if self.daily is not None else None,
            "Strategy": self.strategy,
        }


def _dig(data: Mapping[str, Any], path: Sequence[str]) -> Optional[Mapping[str, Any]]:
    """Пройти по вложенным словарям, не падая на отсутствующих ключах.

    :param data: корневой словарь.
    :param path: путь по ключам.
    :return: вложенный словарь либо None.
    """
    current: Any = data
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current if isinstance(current, Mapping) else None


def _strategy_type_of(campaign: Mapping[str, Any]) -> Optional[str]:
    """Определить тип текущей стратегии кампании.

    Приоритет у секции, где реально лежит недельный бюджет: у CPM-кампании
    поиск всегда выключен (`SERVING_OFF`), и без этого приоритета вернётся
    не та стратегия, которой управляет бюджет.

    :param campaign: запись кампании из `campaigns/get`.
    :return: значение `BiddingStrategyType` либо None.
    """
    fallback: Optional[str] = None
    for block_name in ("CpmBannerCampaign", "TextCampaign", "UnifiedCampaign"):
        strategy = _dig(campaign.get(block_name) or {}, ("BiddingStrategy",))
        if not strategy:
            continue
        for placement in ("Network", "Search"):
            section = strategy.get(placement)
            if not isinstance(section, Mapping):
                continue
            strategy_type = section.get("BiddingStrategyType")
            if not strategy_type:
                continue
            if "WeeklySpendLimit" in section:
                return str(strategy_type)
            for value in section.values():
                if isinstance(value, Mapping) and "WeeklySpendLimit" in value:
                    return str(strategy_type)
            if fallback is None:
                fallback = str(strategy_type)
    return fallback


def _weekly_block_of(campaign: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """Найти секцию стратегии, в которой лежит недельный бюджет.

    :param campaign: запись кампании из `campaigns/get`.
    :return: секция стратегии с `WeeklySpendLimit` либо None.
    """
    for block_name in ("CpmBannerCampaign", "TextCampaign", "UnifiedCampaign"):
        strategy = _dig(campaign.get(block_name) or {}, ("BiddingStrategy",))
        if not strategy:
            continue
        for placement in ("Search", "Network"):
            section = strategy.get(placement)
            if not isinstance(section, Mapping):
                continue
            if "WeeklySpendLimit" in section:
                return section
            for value in section.values():
                if isinstance(value, Mapping) and "WeeklySpendLimit" in value:
                    return value
    return None


def set_weekly_budget_in_campaign(
    campaign: Dict[str, Any], amount: Money, *, strategy: Optional[str] = None
) -> Dict[str, Any]:
    """Проставить недельный бюджет в теле `campaigns/update` на месте.

    Функция чистая: принимает готовое тело и возвращает новое. Это позволяет
    проверять логику без HTTP.

    :param campaign: тело `CampaignUpdateItem` (с `Id` и типом).
    :param amount: недельный бюджет в валюте аккаунта.
    :param strategy: сетевая стратегия CPM (`MANUAL_CPM`). По умолчанию ставится
        `MANUAL_CPM`, но только если сеть ещё не задана иным типом — иное
        значение не перезаписывается молча, а бросает `ValidationError`.
    :return: то же тело с обновлённым недельным бюджетом.
    :raises ValidationError: бюджет неположителен, тип кампании не поддерживает
        недельный бюджет, либо сетевая стратегия CPM уже задана иначе, чем
        `strategy` (SDK не меняет стратегию за бизнес).
    """
    units = to_money_units(amount)
    if units <= 0:
        raise ValidationError("Бюджет должен быть больше нуля")
    campaign_type = campaign.get("Type") or ""
    if campaign_type == "CPM_BANNER_CAMPAIGN":
        block = campaign.setdefault("CpmBannerCampaign", {})
        bidding_strategy = block.setdefault("BiddingStrategy", {})
        bidding_strategy.setdefault(
            "Search", {"BiddingStrategyType": "SERVING_OFF"}
        )
        network = bidding_strategy.setdefault("Network", {})
        existing = network.get("BiddingStrategyType")
        desired = strategy or STRATEGY_MANUAL_CPM
        if existing not in (None, desired):
            raise ValidationError(
                f"Сетевая стратегия CPM-кампании {existing!r} ≠ {desired!r}: "
                f"set_weekly_budget_in_campaign не перезаписывает стратегию "
                f"молча. Передайте strategy={desired!r} явно или измените "
                f"стратегию кампании заранее"
            )
        network["BiddingStrategyType"] = desired
        network.setdefault("ManualCpm", {})["WeeklySpendLimit"] = units
        return campaign
    if campaign_type == "UNIFIED_CAMPAIGN":
        block = campaign.setdefault("UnifiedCampaign", {})
        bidding_strategy = block.setdefault("BiddingStrategy", {})
        search = bidding_strategy.get("Search")
        if not isinstance(search, Mapping) or not search.get("BiddingStrategyType"):
            raise ValidationError(
                "Чтобы сменить недельный бюджет ЕПК, нужна текущая поисковая "
                "стратегия: прочитайте кампанию через get_unified() и передайте "
                "её поля в тело обновления"
            )
        strategy_type = str(search["BiddingStrategyType"])
        if strategy_type in ("SERVING_OFF", "NETWORK_DEFAULT"):
            raise ValidationError(
                f"Стратегия {strategy_type} не имеет недельного бюджета — "
                "сначала задайте стратегию с бюджетом"
            )
        updated = False
        for value in list(search.values()):
            if isinstance(value, dict):
                value["WeeklySpendLimit"] = units
                updated = True
        if not updated:
            raise ValidationError(
                f"В секции стратегии {strategy_type} нет места для недельного "
                "бюджета; используйте set_bid_strategy()"
            )
        return campaign
    raise ValidationError(
        f"Недельный бюджет в этой форме не поддерживается для типа "
        f"{campaign_type or 'неизвестного'}"
    )


def read_budget(campaign: Mapping[str, Any]) -> CampaignBudget:
    """Разобрать бюджет кампании из ответа `campaigns/get`.

    :param campaign: запись кампании.
    :return: модель `CampaignBudget`.
    """
    weekly_block = _weekly_block_of(campaign)
    daily_block = campaign.get("DailyBudget")
    daily_value = daily_block.get("Amount") if isinstance(daily_block, Mapping) else None
    return CampaignBudget(
        campaign_id=int(campaign.get("Id") or 0),
        type=campaign.get("Type"),
        weekly=weekly_budget_of(weekly_block),
        daily=from_money_units(daily_value) if daily_value is not None else None,
        strategy=_strategy_type_of(campaign),
    )


def _validate_budget(value: Money, *, cap: Optional[Decimal], field: str) -> Decimal:
    """Проверить бюджет и предостерегательный лимит.

    :param value: сумма в валюте аккаунта.
    :param cap: максимум (`daily_budget_cap`) либо None.
    :param field: имя поля для сообщения об ошибке.
    :return: сумма как `Decimal`.
    :raises ValidationError: сумма неположительна или превышает cap.
    """
    amount = to_decimal(value)
    if amount <= 0:
        raise ValidationError(f"{field} должен быть больше нуля, получено {value!r}")
    if cap is not None and amount > to_decimal(cap):
        raise ValidationError(
            f"{field}={amount} превышает предохранительный лимит "
            f"daily_budget_cap={cap}. Повышайте лимит осознанно "
            "(YANDEX_DIRECT_BUDGET_CAP или daily_budget_cap клиента)"
        )
    return amount


def ensure_money_confirmed(service: str, method: str, confirm: bool, required: bool) -> None:
    """Проверить `confirm` для денежной мутации.

    :param service: имя сервиса для сообщения об ошибке.
    :param method: имя метода.
    :param confirm: переданное подтверждение.
    :param required: требовать ли подтверждение (настройка клиента).
    :raises ValidationError: подтверждение обязательно, но не передано.
    """
    if required and not confirm:
        raise ValidationError(
            f"{service}.{method} меняет деньги и требует confirm=True "
            "(require_confirm_for_money)"
        )
    if confirm:
        ensure_confirmed(f"{service}.{method}", True)


def verify_weekly_budget(
    budgets: Mapping[int, CampaignBudget], expected: Mapping[int, Decimal]
) -> None:
    """Сверить прочитанные бюджеты с запрошенными.

    :param budgets: бюджеты, прочитанные из `campaigns/get`.
    :param expected: ожидаемые бюджеты по ID кампаний.
    :raises ApiError: значения различаются (в тексте — оба числа).
    """
    mismatches: List[str] = []
    for campaign_id, wanted in expected.items():
        actual = budgets.get(campaign_id)
        actual_value = actual.weekly if actual is not None else None
        if actual_value is None or actual_value != wanted:
            mismatches.append(
                f"CampaignId={campaign_id}: ожидалось {wanted}, получено "
                f"{actual_value if actual_value is not None else 'None'}"
            )
    if mismatches:
        raise ApiError(
            "Недельный бюджет не совпал после обновления: " + "; ".join(mismatches)
        )


__all__ = [
    "WEEKLY_BUDGET_CAMPAIGN_TYPES",
    "BidStrategy",
    "CampaignBudget",
    "ensure_money_confirmed",
    "read_budget",
    "set_weekly_budget_in_campaign",
    "strategy_payload",
    "verify_weekly_budget",
]
