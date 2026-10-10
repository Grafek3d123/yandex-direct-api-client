"""Типизация денежных величин Yandex.Direct.

Директ принимает и возвращает деньги **целыми числами в единицах ×1 000 000**
(1 ₽ = 1 000 000 единиц, 1 000 000 ₽ = 1 единица). Хранение сумм в `float`
приводит к тихим ошибкам округления, поэтому конвертация идёт через `Decimal`
и возвращает `int` — ровно то, что ожидает API.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Union

from .config import MONEY_UNITS_MULTIPLIER
from .exceptions import ValidationError

#: Что можно передать в качестве денежной суммы.
Money = Union[int, float, str, Decimal]

_MULTIPLIER = Decimal(MONEY_UNITS_MULTIPLIER)
#: Точность ответа API: единицы ×1 000 000 → шесть знаков после точки.
_UNITS_STEP = Decimal("0.000001")
#: Точность недельного бюджета — копейки.
_CENT = Decimal("0.01")


def to_decimal(value: Money) -> Decimal:
    """Привести значение суммы к `Decimal` без потери точности.

    :param value: сумма (int, float, str или Decimal).
    :return: значение как `Decimal`.
    :raises ValidationError: значение не является числом или `NaN`/бесконечность.
    """
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool):
        raise ValidationError(f"Денежная сумма не может быть bool: {value!r}")
    elif isinstance(value, (int, float, str)):
        try:
            # str(Decimal) не даёт артефактов float: 0.1 -> "0.1".
            result = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValidationError(f"Некорректная денежная сумма: {value!r}") from exc
    else:
        raise ValidationError(f"Некорректная денежная сумма: {value!r}")
    if not result.is_finite():
        raise ValidationError(f"Денежная сумма должна быть конечной: {value!r}")
    return result


def to_money_units(value: Money) -> int:
    """Перевести сумму в единицы API (×1 000 000).

    :param value: сумма в рублях/единицах валюты аккаунта.
    :return: целое число единиц, которое принимает API.
    :raises ValidationError: некорректное значение.
    """
    return int((to_decimal(value) * _MULTIPLIER).to_integral_value(ROUND_HALF_UP))


def from_money_units(value: Any) -> Decimal:
    """Перевести единицы API обратно в сумму.

    :param value: единицы из ответа API.
    :return: сумма как `Decimal`.
    :raises ValidationError: значение не является числом.
    """
    if value is None:
        return Decimal(0)
    units = to_decimal(value)
    return (units / _MULTIPLIER).quantize(_UNITS_STEP, rounding=ROUND_HALF_UP)


def monthly_to_weekly(monthly: Money) -> Decimal:
    """Перевести месячный бюджет в недельный (для ЕПК).

    Расчёт приблизительный: в месяце ~4,345 недели. Значение **не скрывается**
    от вызывающего кода — результат округляется до копеек и возвращается явно,
    чтобы пользователь видел, что именно уйдёт в API.

    :param monthly: месячный бюджет.
    :return: эквивалентный недельный бюджет.
    :raises ValidationError: некорректное или неположительное значение.
    """
    amount = to_decimal(monthly)
    if amount <= 0:
        raise ValidationError(
            f"Месячный бюджет должен быть больше нуля, получено {monthly!r}"
        )
    weekly = amount * Decimal(7) / Decimal(30.4375)
    return weekly.quantize(_CENT, rounding=ROUND_HALF_UP)


__all__ = [
    "Money",
    "from_money_units",
    "monthly_to_weekly",
    "to_decimal",
    "to_money_units",
]
