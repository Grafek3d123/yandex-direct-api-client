"""Типизированные стратегии показа и ставок (слой 3, D7).

Каждая стратегия умеет две вещи:

- `to_payload()` — собрать тело для `campaigns/add|update`
  (`BiddingStrategy.Search.<Стратегия>` / `CpmBannerCampaign.BiddingStrategy.Network.<Стратегия>`);
- `from_dict()` — разобрать секцию стратегии из ответа `campaigns/get`.

Деньги везде принимаются как `int | float | str | Decimal` и уходят в единицах
API ×1 000 000 (см. `money.py`).

Редкие и новые поля стратегий, которые SDK ещё не знает, передаются через
`extra` — escape-hatch (D7): стратегия не должна ломаться из-за того, что
Яндекс добавил поле.

Справочники (снимок 30.09.2026):
https://yandex.ru/dev/direct/doc/ru/campaigns/add-unified-campaign
https://yandex.ru/dev/direct/doc/ru/campaigns/add-cpm-banner-campaign
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Union

from ..exceptions import ValidationError
from ..money import Money, from_money_units, to_money_units
from ..validation import Validator

#: Стратегия без параметров (максимизация по позиции).
STRATEGY_HIGHEST_POSITION = "HIGHEST_POSITION"

#: Ручное управление CPC с недельным бюджетом.
STRATEGY_AVERAGE_CPC = "AVERAGE_CPC"

#: Оптимизация по конверсиям (требует `GoalId`).
STRATEGY_AVERAGE_CPA = "AVERAGE_CPA"

#: Максимум кликов в неделю (требует недельного бюджета).
STRATEGY_WB_MAXIMUM_CLICKS = "WB_MAXIMUM_CLICKS"

#: Ручное управление CPM в сетях (недельный бюджет).
STRATEGY_MANUAL_CPM = "MANUAL_CPM"

#: Без ограничения средней цены (поиск ЕПК).
STRATEGY_PAY_FOR_CONVERSION = "PAY_FOR_CONVERSION"

#: Все поддерживаемые типы стратегий.
STRATEGY_TYPES = (
    STRATEGY_HIGHEST_POSITION,
    STRATEGY_AVERAGE_CPC,
    STRATEGY_AVERAGE_CPA,
    STRATEGY_WB_MAXIMUM_CLICKS,
    STRATEGY_MANUAL_CPM,
    STRATEGY_PAY_FOR_CONVERSION,
)

#: Типы стратегий, требующие `GoalId`.
STRATEGY_REQUIRES_GOAL = (
    STRATEGY_AVERAGE_CPA,
    STRATEGY_PAY_FOR_CONVERSION,
)

#: Типы стратегий, требующие недельного бюджета.
STRATEGY_REQUIRES_WEEKLY_BUDGET = (
    STRATEGY_AVERAGE_CPA,
    STRATEGY_WB_MAXIMUM_CLICKS,
    STRATEGY_MANUAL_CPM,
    STRATEGY_PAY_FOR_CONVERSION,
)


def _weekly(value: Money, field: str) -> int:
    """Проверить бюджет и перевести в единицы API.

    :param value: сумма в валюте аккаунта.
    :param field: имя поля для сообщения об ошибке.
    :return: единицы ×1 000 000.
    :raises ValidationError: сумма неположительна или не число.
    """
    try:
        units = to_money_units(value)
    except ValidationError as exc:
        raise ValidationError(f"{field}: {exc}") from exc
    if units <= 0:
        raise ValidationError(f"{field} должен быть больше нуля")
    return units


@dataclass
class BidStrategy:
    """Стратегия показа кампании.

    :param strategy: тип стратегии (см. `STRATEGY_TYPES`).
    :param weekly_budget: недельный бюджет (обязателен для стратегий из
        `STRATEGY_REQUIRES_WEEKLY_BUDGET`).
    :param goal_id: цель Метрики (обязательна для стратегий из
        `STRATEGY_REQUIRES_GOAL`); цели выбирает пользователь.
    :param average_cpc: ставка для `AVERAGE_CPC`.
    :param bid_ceiling: ограничение ставки, если стратегия его допускает.
    :param extra: дополнительные поля стратегии (escape-hatch, D7).
    """

    strategy: str
    weekly_budget: Optional[Money] = None
    goal_id: Optional[int] = None
    average_cpc: Optional[Money] = None
    bid_ceiling: Optional[Money] = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Нормализовать стратегию сразу при создании.

        Проверяется только тип стратегии и корректность сумм; требования к
        обязательным полям (`weekly_budget`, `goal_id`) проверяются при
        сборке payload — их можно задать позже, по отдельности от стратегии.

        :raises ValidationError: неизвестный тип стратегии или некорректная сумма.
        """
        self.validate()

    def validate(self, *, for_payload: bool = False) -> None:
        """Проверить стратегию.

        :param for_payload: True — учитывать обязательные для стратегии поля
            (недельный бюджет, цель Метрики, ставка `AVERAGE_CPC`).
        :raises ValidationError: при нарушении.
        """
        validator = Validator(True)
        validator.one_of(self.strategy, STRATEGY_TYPES, field="BidStrategy.strategy")
        if for_payload:
            if self.strategy in STRATEGY_REQUIRES_WEEKLY_BUDGET and (
                self.weekly_budget is None
            ):
                raise ValidationError(
                    f"Стратегия {self.strategy} требует недельный бюджет "
                    "(weekly_budget)"
                )
            if self.strategy in STRATEGY_REQUIRES_GOAL and self.goal_id is None:
                raise ValidationError(
                    f"Стратегия {self.strategy} требует goal_id — цели Метрики "
                    "выбирает пользователь"
                )
            if self.strategy == STRATEGY_AVERAGE_CPC and self.average_cpc is None:
                raise ValidationError(
                    "Стратегия AVERAGE_CPC требует ставку average_cpc"
                )
        if self.weekly_budget is not None:
            _weekly(self.weekly_budget, "weekly_budget")
        if self.goal_id is not None:
            validator.ids([self.goal_id], field="goal_id")
        if self.average_cpc is not None:
            _weekly(self.average_cpc, "average_cpc")
        if self.bid_ceiling is not None:
            _weekly(self.bid_ceiling, "bid_ceiling")

    @property
    def weekly_spend_limit(self) -> Optional[int]:
        """Недельный бюджет в единицах API (или None).

        :return: единицы ×1 000 000, если бюджет задан.
        """
        if self.weekly_budget is None:
            return None
        return to_money_units(self.weekly_budget)

    def to_payload(self, *, require_fields: bool = True) -> Dict[str, Any]:
        """Тело секции стратегии (всё, кроме `BiddingStrategyType`).

        :param require_fields: True — требовать обязательные поля стратегии
            (недельный бюджет, цель Метрики). False использовать, когда бюджет
            или цель задаются отдельным аргументом метода обновления.
        :return: словарь с недельным бюджетом, целью и прочими полями.
        :raises ValidationError: не заданы обязательные для стратегии поля.
        """
        if require_fields:
            self.validate(for_payload=True)
        payload: Dict[str, Any] = {}
        if self.weekly_budget is not None:
            payload["WeeklySpendLimit"] = to_money_units(self.weekly_budget)
        if self.goal_id is not None:
            payload["GoalId"] = int(self.goal_id)
        if self.average_cpc is not None:
            payload["AverageCpc"] = to_money_units(self.average_cpc)
        if self.bid_ceiling is not None:
            payload["BidCeiling"] = to_money_units(self.bid_ceiling)
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload

    def to_strategy_block(self, *, require_fields: bool = True) -> Dict[str, Any]:
        """Секция стратегии вместе с `BiddingStrategyType`.

        :param require_fields: см. `to_payload`.
        :return: словарь `BiddingStrategyType` плюс поля стратегии.
        """
        return {
            "BiddingStrategyType": self.strategy,
            **self.to_payload(require_fields=require_fields),
        }

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "BidStrategy":
        """Разобрать стратегию из ответа `campaigns/get`.

        :param data: словарь с полями стратегии; None — пустая стратегия.
        :return: модель стратегии (escape-hatch-поля попадают в `extra`).
        """
        if not data:
            raise ValidationError("Секция стратегии пуста")
        raw = dict(data)
        strategy = raw.pop("BiddingStrategyType", None)
        if not strategy:
            raise ValidationError("В секции стратегии нет BiddingStrategyType")
        known = {
            "WeeklySpendLimit": "weekly_budget",
            "GoalId": "goal_id",
            "AverageCpc": "average_cpc",
            "BidCeiling": "bid_ceiling",
        }
        kwargs: Dict[str, Any] = {"strategy": strategy}
        extra: Dict[str, Any] = {}
        for key, value in raw.items():
            if key in known:
                kwargs[known[key]] = value
            else:
                extra[key] = value
        if kwargs.get("weekly_budget") is not None:
            kwargs["weekly_budget"] = from_money_units(kwargs["weekly_budget"])
        if kwargs.get("average_cpc") is not None:
            kwargs["average_cpc"] = from_money_units(kwargs["average_cpc"])
        if kwargs.get("bid_ceiling") is not None:
            kwargs["bid_ceiling"] = from_money_units(kwargs["bid_ceiling"])
        kwargs["extra"] = extra
        return cls(**kwargs)

    @classmethod
    def parse(cls, data: Optional[Mapping[str, Any]]) -> Optional["BidStrategy"]:
        """Разобрать стратегию, вернуть None при пустой секции.

        :param data: секция стратегии из ответа API либо None.
        :return: стратегия или None.
        """
        if not data:
            return None
        return cls.from_dict(data)


#: Стратегия или её тело для обновления (escape-hatch).
BidStrategyInput = Union[BidStrategy, Mapping[str, Any]]


def strategy_payload(
    strategy: BidStrategyInput, *, require_fields: bool = True
) -> Dict[str, Any]:
    """Привести стратегию или словарь к секции `BiddingStrategy`.

    :param strategy: модель стратегии либо готовая секция.
    :param require_fields: True — требовать обязательные поля стратегии;
        False использовать, когда бюджет или цель передаются отдельно.
    :return: словарь с `BiddingStrategyType` и полями стратегии.
    :raises ValidationError: неизвестный тип стратегии.
    """
    if isinstance(strategy, BidStrategy):
        return strategy.to_strategy_block(require_fields=require_fields)
    if isinstance(strategy, Mapping):
        return dict(strategy)
    raise ValidationError(
        f"Ожидалась BidStrategy или dict, получено {type(strategy).__name__}"
    )


def weekly_budget_of(data: Optional[Mapping[str, Any]]) -> Optional[Decimal]:
    """Достать недельный бюджет из произвольной секции стратегии.

    :param data: секция стратегии из ответа `campaigns/get`.
    :return: недельный бюджет как `Decimal` либо None.
    """
    if not data:
        return None
    if "WeeklySpendLimit" in data:
        return from_money_units(data["WeeklySpendLimit"])
    for value in data.values():
        if isinstance(value, Mapping) and "WeeklySpendLimit" in value:
            return from_money_units(value["WeeklySpendLimit"])
    return None


__all__ = [
    "STRATEGY_AVERAGE_CPA",
    "STRATEGY_AVERAGE_CPC",
    "STRATEGY_HIGHEST_POSITION",
    "STRATEGY_MANUAL_CPM",
    "STRATEGY_PAY_FOR_CONVERSION",
    "STRATEGY_REQUIRES_GOAL",
    "STRATEGY_REQUIRES_WEEKLY_BUDGET",
    "STRATEGY_TYPES",
    "STRATEGY_WB_MAXIMUM_CLICKS",
    "BidStrategy",
    "BidStrategyInput",
    "strategy_payload",
    "weekly_budget_of",
]
