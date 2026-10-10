"""Пред-отправочная валидация payload'ов Yandex.Direct.

Цель — не отправлять заведомо невалидные данные: платный round-trip на битой
кампании дороже локальной проверки. Все проверки бросают `ValidationError`
**до** HTTP-запроса (F-0.7).

Валидацию можно отключить глобально: `YandexDirectClient(validate=False)` или
`YANDEX_DIRECT_VALIDATE=0` — escape-hatch для отладки и сырых payload'ов,
которые клиент пока не умеет проверять.

Проверки делятся на три группы:

- **структурные** — обязательные поля, типы, отсутствие `None`;
- **бизнес-валидация** — лимиты символов, форматы URL, положительность
  денег и ставок, порядок дат, непустота списков;
- **кросс-сущностные** — проверки, требующие обращения к API (например,
  существование `campaign_id`); по умолчанию не выполняются, чтобы не
  делать лишний round-trip — см. `cross_entity_checks_enabled`.
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Iterable, Optional, Sequence

from .exceptions import ValidationError

#: Имя переменной окружения, включающей кросс-сущностные проверки.
ENV_CROSS_CHECKS = "YANDEX_DIRECT_CROSS_CHECKS"

#: Лимиты символов имён кампаний/групп (справочник Yandex.Direct).
NAME_MAX_LENGTH = 60
#: Лимит символов имени кампании (docs: campaigns/add — до 255 символов).
CAMPAIGN_NAME_MAX_LENGTH = 255
#: Лимит символов имени группы объявлений (docs: adgroups/add — 1..255).
AD_GROUP_NAME_MAX_LENGTH = 255
#: Лимит символов имени креатива (docs: adimages/add — до 255 символов).
AD_IMAGE_NAME_MAX_LENGTH = 255
#: Лимит символов ссылки объявления (docs: ads/add — до 1024).
AD_HREF_MAX_LENGTH = 1024
#: Лимиты символов имён наборов минус-фраз и расширений.
SHORT_NAME_MAX_LENGTH = 100
#: Лимиты символов заголовка/текста поискового объявления.
AD_TITLE_MAX_LENGTH = 56
AD_TEXT_MAX_LENGTH = 81
#: Максимальная длина ключевой фразы.
KEYWORD_MAX_LENGTH = 50


class Validator:
    """Набор проверок с переключателем ``enabled``.

    :param enabled: если False, все проверки молча пропускаются
        (режим escape-hatch `validate=False`).
    """

    __slots__ = ("enabled",)

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    # ---------------- структурные проверки ----------------
    def name(
        self,
        value: Optional[str],
        *,
        field: str = "Name",
        max_length: int = NAME_MAX_LENGTH,
    ) -> None:
        """Проверить имя объекта: непустое, без хвостовых пробелов, по длине.

        :param value: проверяемое имя.
        :param field: имя поля для сообщения об ошибке.
        :param max_length: максимум символов.
        :raises ValidationError: при нарушении (если валидация включена).
        """
        if not self.enabled:
            return
        if value is None or not str(value).strip():
            raise ValidationError(f"{field} обязателен и не может быть пустым")
        text = str(value)
        if len(text) > max_length:
            raise ValidationError(
                f"{field} длиннее {max_length} символов ({len(text)})"
            )
        if text != text.strip():
            raise ValidationError(f"{field} не должен начинаться/заканчиваться пробелом")

    def text(
        self,
        value: Optional[str],
        *,
        field: str,
        max_length: int,
        required: bool = True,
    ) -> None:
        """Проверить ограничение по длине текстового поля.

        :param value: проверяемый текст.
        :param field: имя поля для сообщения об ошибке.
        :param max_length: максимум символов.
        :param required: если True — пустое значение недопустимо.
        """
        if not self.enabled:
            return
        if value is None or not str(value).strip():
            if required:
                raise ValidationError(f"{field} обязателен и не может быть пустым")
            return
        if len(str(value)) > max_length:
            raise ValidationError(
                f"{field} длиннее {max_length} символов ({len(str(value))})"
            )

    def ids(
        self,
        values: Optional[Iterable[Any]],
        *,
        field: str,
        allow_empty: bool = False,
    ) -> None:
        """Проверить список идентификаторов: целые > 0, без пустого списка.

        :param values: проверяемые ID.
        :param field: имя поля для сообщения об ошибке.
        :param allow_empty: допустим пустой список.
        """
        if not self.enabled:
            return
        if values is None:
            if allow_empty:
                return
            raise ValidationError(f"{field} обязателен")
        items = list(values)
        if not items and not allow_empty:
            raise ValidationError(f"{field} не может быть пустым")
        for item in items:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValidationError(f"{field}: ожидаются целые ID, получено {item!r}")
            if item <= 0:
                raise ValidationError(
                    f"{field}: идентификаторы должны быть положительными, получено {item}"
                )

    def region_ids(self, values: Optional[Iterable[Any]]) -> None:
        """Проверить `RegionIds`.

        Пустой список и значение `0` недопустимы: API отвергает `RegionIds=[0]`
        («Geotargeting set incorrectly»), а пустой список означает «без гео»,
        что для рекламной кампании — ошибка конфигурации.

        Отрицательные ID допустимы: Яндекс кодирует ими удалённые регионы
        (например, `-219` — Калининградская область).

        :param values: список ID регионов.
        """
        if not self.enabled:
            return
        if values is None:
            raise ValidationError("RegionIds обязателен")
        items = list(values)
        if not items:
            raise ValidationError(
                "RegionIds не может быть пустым: укажите хотя бы один регион"
            )
        for item in items:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValidationError(f"RegionIds: ожидаются целые ID, получено {item!r}")
            if item == 0:
                raise ValidationError(
                    "RegionIds: значение 0 недопустимо — перечислите реальные "
                    "ID регионов из dictionaries/getGeoRegions"
                )

    def positive_amount(
        self,
        value: Any,
        *,
        field: str,
        allow_zero: bool = False,
    ) -> None:
        """Проверить денежную сумму или ставку: число и больше нуля.

        :param value: проверяемое значение.
        :param field: имя поля для сообщения об ошибке.
        :param allow_zero: допустим ноль.
        """
        if not self.enabled or value is None:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"{field}: ожидается число, получено {value!r}")
        if value < 0 or (value == 0 and not allow_zero):
            raise ValidationError(f"{field} должен быть больше нуля (получено {value})")

    def date_range(
        self,
        start: Optional[_dt.date],
        end: Optional[_dt.date],
        *,
        start_field: str = "StartDate",
        end_field: str = "EndDate",
    ) -> None:
        """Проверить, что `end_date` позже `start_date`.

        :param start: дата начала.
        :param end: дата окончания (None — бессрочная кампания).
        :param start_field: имя поля начала.
        :param end_field: имя поля окончания.
        """
        if not self.enabled:
            return
        if start is None and end is None:
            return
        if start is not None and not isinstance(start, _dt.date):
            raise ValidationError(f"{start_field}: ожидается datetime.date")
        if end is not None and not isinstance(end, _dt.date):
            raise ValidationError(f"{end_field}: ожидается datetime.date")
        if start is not None and end is not None and end <= start:
            raise ValidationError(
                f"{end_field} должен быть позже {start_field} "
                f"({end.isoformat()} <= {start.isoformat()})"
            )

    def href(self, value: Optional[str], *, field: str = "Href") -> None:
        """Проверить URL объявления: непустой и со схемой http(s).

        :param value: URL.
        :param field: имя поля для сообщения об ошибке.
        """
        if not self.enabled:
            return
        if value is None:
            return
        text = str(value).strip()
        if not text:
            raise ValidationError(f"{field} не может быть пустым")
        if not (text.startswith("http://") or text.startswith("https://")):
            raise ValidationError(f"{field} должен начинаться с http:// или https://")

    def one_of(
        self,
        value: Optional[str],
        allowed: Sequence[str],
        *,
        field: str,
    ) -> None:
        """Проверить, что значение входит в список допустимых enum-значений.

        :param value: проверяемое значение (None — проверка пропускается).
        :param allowed: допустимые значения.
        :param field: имя поля для сообщения об ошибке.
        """
        if not self.enabled or value is None:
            return
        if value not in allowed:
            raise ValidationError(
                f"{field}: недопустимое значение {value!r}; "
                f"разрешено: {', '.join(allowed)}"
            )


#: Валидатор по умолчанию (проверки включены).
DEFAULT_VALIDATOR = Validator(True)


def cross_entity_checks_enabled() -> bool:
    """Включены ли кросс-сущностные проверки (существование чужих ID).

    По умолчанию выключены: каждый вызов стоит денег и времени, а существование
    `campaign_id`/`ad_group_id` проверяет сам API (возвращая item-ошибку).
    Включается отдельно, когда вызывающему коду нужны гарантии до запроса.
    """
    raw = os.environ.get(ENV_CROSS_CHECKS)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "AD_GROUP_NAME_MAX_LENGTH",
    "AD_HREF_MAX_LENGTH",
    "AD_IMAGE_NAME_MAX_LENGTH",
    "AD_TEXT_MAX_LENGTH",
    "AD_TITLE_MAX_LENGTH",
    "CAMPAIGN_NAME_MAX_LENGTH",
    "DEFAULT_VALIDATOR",
    "ENV_CROSS_CHECKS",
    "KEYWORD_MAX_LENGTH",
    "NAME_MAX_LENGTH",
    "SHORT_NAME_MAX_LENGTH",
    "Validator",
    "cross_entity_checks_enabled",
]
