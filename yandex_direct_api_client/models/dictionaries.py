"""Типизированные модели справочников Yandex.Direct.

Модели покрывают основные словари API `dictionaries`: география, интересы,
ретаргетинг-списки, сайты, типы объявлений, часовые пояса, валюты и
универсальные записи произвольных словарей.

У каждой модели есть `raw` — исходный JSON-запись без изменений, чтобы новые
поля Яндекса не терялись.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ._helpers import to_bool, to_int, to_optional_int, to_str


@dataclass
class GeoRegion:
    """Регион из справочника `getGeoRegions`."""

    id: int
    name: str
    parent_id: Optional[int] = None
    country_region: Optional[str] = None
    is_area: bool = False
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GeoRegion":
        """Разобрать запись справочника регионов.

        :param d: JSON-запись региона.
        :return: типизированная модель региона.
        """
        return cls(
            id=to_int(d.get("GeoRegionId")),
            name=to_str(d.get("GeoRegionName")),
            parent_id=to_optional_int(d.get("ParentGeoRegionId")),
            country_region=d.get("CountryRegion"),
            is_area=to_bool(d.get("IsArea")),
            raw=d,
        )

    @property
    def is_top_level(self) -> bool:
        """Регион верхнего уровня (область/край, без родителя)."""
        return self.parent_id is None


@dataclass
class Interest:
    """Интерес из справочника `getInterests`."""

    id: int
    name: str
    intent_id: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Interest":
        """Разобрать запись справочника интересов.

        :param d: JSON-запись интереса.
        :return: типизированная модель интереса.
        """
        return cls(
            id=to_int(d.get("InterestId")),
            name=to_str(d.get("InterestName")),
            intent_id=to_optional_int(d.get("IntentId")),
            raw=d,
        )


@dataclass
class RetargetingList:
    """Сегмент ретаргетинга из справочника `getRetargetingLists`."""

    id: int
    name: str
    type: Optional[str] = None
    subtype: Optional[str] = None
    goal_id: Optional[int] = None
    site_id: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RetargetingList":
        """Разобрать запись справочника ретаргетинг-списков.

        :param d: JSON-запись сегмента.
        :return: типизированная модель сегмента.
        """
        return cls(
            id=to_int(d.get("RetargetingListId") or d.get("Id")),
            name=to_str(d.get("Name")),
            type=d.get("Type"),
            subtype=d.get("Subtype"),
            goal_id=to_optional_int(d.get("GoalId")),
            site_id=to_optional_int(d.get("SiteId")),
            raw=d,
        )


@dataclass
class Site:
    """Сайт из справочника `getSites`."""

    id: int
    name: str
    url: Optional[str] = None
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Site":
        """Разобрать запись справочника сайтов.

        :param d: JSON-запись сайта.
        :return: типизированная модель сайта.
        """
        return cls(
            id=to_int(d.get("Id") or d.get("SiteId")),
            name=to_str(d.get("Name")),
            url=d.get("Url"),
            status=d.get("Status"),
            raw=d,
        )


@dataclass
class AdType:
    """Тип объявления из справочника `getAdTypes`."""

    ad_type: str
    name: Optional[str] = None
    ad_group_type: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AdType":
        """Разобрать запись справочника типов объявлений.

        :param d: JSON-запись типа объявления.
        :return: типизированная модель типа объявления.
        """
        return cls(
            ad_type=to_str(d.get("AdType")),
            name=d.get("Name"),
            ad_group_type=d.get("AdGroupType"),
            raw=d,
        )


@dataclass
class TimeZone:
    """Часовой пояс из справочника `getTimeZones`."""

    name: str
    offset: Optional[int] = None
    zone_id: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TimeZone":
        """Разобрать запись справочника часовых поясов.

        :param d: JSON-запись часового пояса.
        :return: типизированная модель часового пояса.
        """
        return cls(
            name=to_str(d.get("Name")),
            offset=to_optional_int(d.get("Offset")),
            zone_id=to_optional_int(d.get("TimeZoneId")),
            raw=d,
        )


@dataclass
class Currency:
    """Валюта клиента/аккаунта из справочника `getCurrency`."""

    currency: str
    name: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Currency":
        """Разобрать запись справочника валют.

        :param d: JSON-запись валюты.
        :return: типизированная модель валюты.
        """
        return cls(
            currency=to_str(d.get("Currency") or d.get("Code")),
            name=d.get("Name"),
            raw=d,
        )


@dataclass
class AudienceCriteriaType:
    """Демографическая или поведенческая характеристика (`AudienceCriteriaTypes`).

    :param type: ID характеристики (например, `AGE`, `GENDER`).
    :param can_select: можно ли выбрать **все** сегменты характеристики
        (`ALL`) или требуется исключение хотя бы одного (`EXCEPT_ALL`).
    """

    type: str
    name: str
    block_element: Optional[str] = None
    description: Optional[str] = None
    can_select: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AudienceCriteriaType":
        """Разобрать запись справочника характеристик.

        :param d: JSON-запись характеристики.
        :return: типизированная модель.
        """
        return cls(
            type=to_str(d.get("Type")),
            name=to_str(d.get("Name")),
            block_element=d.get("BlockElement"),
            description=d.get("Description"),
            can_select=d.get("CanSelect"),
            raw=d,
        )


@dataclass
class AudienceDemographicProfile:
    """Сегмент по демографической или поведенческой характеристике.

    Сегменты этого справочника используются как `ExternalId` в правилах
    ретаргетинг-листа типа `AUDIENCE` (docs: objects/retargeting-list).
    """

    id: int
    type: str
    name: str
    description: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AudienceDemographicProfile":
        """Разобрать запись справочника сегментов.

        :param d: JSON-запись сегмента.
        :return: типизированная модель.
        """
        return cls(
            id=to_int(d.get("Id")),
            type=to_str(d.get("Type")),
            name=to_str(d.get("Name")),
            description=d.get("Description"),
            raw=d,
        )


@dataclass
class AudienceInterestSegment:
    """Сегмент по пользовательскому интересу (`AudienceInterests`).

    У `id` уже встроен префикс типа интереса: так `Id` = 102499001182 означает
    краткосрочный интерес `InterestKey` = 2499001182. Поэтому в правило
    ретаргетинг-листа кладётся именно `id`, а не `interest_key`.
    """

    id: int
    interest_key: int
    name: str
    parent_id: Optional[int] = None
    interest_type: Optional[str] = None
    description: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AudienceInterestSegment":
        """Разобрать запись справочника сегментов интересов.

        :param d: JSON-запись сегмента.
        :return: типизированная модель.
        """
        return cls(
            id=to_int(d.get("Id")),
            interest_key=to_int(d.get("InterestKey")),
            name=to_str(d.get("Name")),
            parent_id=to_optional_int(d.get("ParentId")),
            interest_type=d.get("InterestType"),
            description=d.get("Description"),
            raw=d,
        )


@dataclass
class DictEntry:
    """Универсальная запись произвольного словаря.

    Используется эскапирующим методом `DictionariesService.dicts()`: имя
    первого ключа ответа (например, `BingTypes`) сохраняется, чтобы вызывающий
    код мог работать с новыми справочниками без изменений SDK.
    """

    key: str
    values: List[Dict[str, Any]] = field(default_factory=list)
    raw: Any = field(default=None, repr=False)

    @classmethod
    def from_result(cls, result: Dict[str, Any]) -> List["DictEntry"]:
        """Разобрать тело ответа `dictionaries` в список записей.

        :param result: `result` из ответа API.
        :return: по одной `DictEntry` на каждый список в ответе.
        """
        entries: List[DictEntry] = []
        for key, value in result.items():
            if isinstance(value, list):
                entries.append(
                    cls(
                        key=key,
                        values=[v for v in value if isinstance(v, dict)],
                        raw=value,
                    )
                )
        return entries

    def values_of(self, field_name: str) -> List[Any]:
        """Собрать одно поле из всех записей.

        :param field_name: имя поля записи.
        :return: список значений поля в порядке записей.
        """
        return [item.get(field_name) for item in self.values]


def dedupe_ids(ids: Sequence[int]) -> List[int]:
    """Убрать повторы из списка ID, сохранив порядок первого появления.

    :param ids: исходный список идентификаторов.
    :return: список уникальных идентификаторов в исходном порядке.
    """
    seen = set()
    result: List[int] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


__all__ = [
    "AdType",
    "AudienceCriteriaType",
    "AudienceDemographicProfile",
    "AudienceInterestSegment",
    "Currency",
    "DictEntry",
    "GeoRegion",
    "Interest",
    "RetargetingList",
    "Site",
    "TimeZone",
    "dedupe_ids",
]
