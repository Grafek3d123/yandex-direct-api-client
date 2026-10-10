"""Сервис справочников Yandex.Direct (F-1.1).

Официальный справочник:
https://yandex.ru/dev/direct/doc/ru/dictionaries/dictionaries.html

Справочник — это единственный метод `get` сервиса `dictionaries`, у которого
набор запрашиваемых словарей задаётся ключами в `params`. Типичные вызовы:

- ``{"getGeoRegions": {"CountryRegion": "RUC", "GeoRegionFieldNames": [...]}}``;
- ``{"getInterests": {"GeoId": 225, "InterestFieldNames": [...]}}``;
- ``{"getRetargetingLists": {"RetargetingListFieldNames": [...]}}``.

Поэтому сервис построен на одном внутреннем методе `_dictionary()`, который
принимает имя словаря, параметры и имя списка в ответе. Все публичные методы —
тонкие обёртки с типизированными моделями; для нестандартных справочников есть
эскапирующий `dicts()`.

Результаты справочников кэшируются на диске (7 суток) — см. `cache.JsonCache`.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Type, TypeVar

from .._transport import Transport
from ..cache import DEFAULT_TTL_SECONDS, JsonCache
from ..exceptions import ApiError
from ..limits import DICTIONARIES_GET_MAX
from ..models.dictionaries import (
    AdType,
    AudienceCriteriaType,
    AudienceDemographicProfile,
    AudienceInterestSegment,
    Currency,
    DictEntry,
    GeoRegion,
    Interest,
    RetargetingList,
    Site,
    TimeZone,
)

_T = TypeVar("_T")

#: Поля, которые нужны для работы `RegionSelector` и проверок лимитов.
_GEO_FIELDS = ["GeoRegionId", "GeoRegionName", "ParentGeoRegionId", "CountryRegion"]
_INTEREST_FIELDS = ["InterestId", "InterestName"]
_RETARGETING_FIELDS = [
    "RetargetingListId",
    "Name",
    "Type",
    "Subtype",
    "GoalId",
    "SiteId",
]
_SITE_FIELDS = ["Id", "Name", "Url", "Status"]
_AD_TYPE_FIELDS = ["AdType", "Name", "AdGroupType"]
_TIME_ZONE_FIELDS = ["Name", "Offset", "TimeZoneId"]
_CURRENCY_FIELDS = ["Currency", "Name"]


class DictionariesService:
    """Доступ к справочникам Директа (гео, интересы, сегменты, типы ads)."""

    def __init__(
        self,
        transport: Transport,
        *,
        cache: Optional[JsonCache] = None,
    ) -> None:
        self._transport = transport
        self._cache = cache if cache is not None else JsonCache()

    # ---------------- инфраструктура ----------------
    def clear_cache(self) -> bool:
        """Очистить локальный кэш справочников.

        :return: True, если кэш очищен.
        """
        return self._cache.clear()

    def _dictionary(
        self,
        dictionary: str,
        params: Dict[str, Any],
        result_key: str,
        *,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """Загрузить один справочник с кэшированием.

        :param dictionary: имя словаря как ключ в `params`
            (`getGeoRegions`, `getInterests`, ...).
        :param params: параметры словаря (поля выбираются здесь).
        :param result_key: имя списка в `result` ответа.
        :param use_cache: использовать ли дисковый кэш.
        :return: список сырых записей справочника.
        :raises ApiError: если в ответе нет ожидаемого списка.
        """
        cache_key: Dict[str, Any] = {"dictionary": dictionary, "params": params}
        if use_cache:
            cached = self._cache.get(dictionary, cache_key)
            if cached is not None:
                return list(cached)

        payload: Dict[str, Any] = {
            "method": "get",
            "params": {dictionary: params},
        }
        result = self._transport.post_result("dictionaries", payload)
        items = result.get(result_key)
        if not isinstance(items, list):
            raise ApiError(
                f"Справочник {dictionary} не вернул список {result_key}",
                response_body=result,
            )
        raw_items: List[Dict[str, Any]] = [i for i in items if isinstance(i, dict)]
        if use_cache:
            self._cache.set(dictionary, cache_key, raw_items)
        return raw_items

    @staticmethod
    def _parse(
        items: Sequence[Dict[str, Any]], model: Type[_T]
    ) -> List[_T]:
        """Разобрать сырые записи в типизированные модели."""
        return [model.from_dict(item) for item in items]  # type: ignore[attr-defined]

    # ---------------- география ----------------
    def geo_regions(
        self,
        country_region: str = "RUC",
        *,
        use_cache: bool = True,
    ) -> List[GeoRegion]:
        """Регионы страны (`getGeoRegions`).

        :param country_region: код страны, например `RUC` (Россия).
        :param use_cache: использовать ли дисковый кэш (по умолчанию да).
        :return: список регионов с `id`, `name`, `parent_id`.
        """
        items = self._dictionary(
            "getGeoRegions",
            {
                "CountryRegion": country_region,
                "GeoRegionFieldNames": _GEO_FIELDS,
            },
            "GeoRegions",
            use_cache=use_cache,
        )
        return self._parse(items, GeoRegion)

    def geo_hierarchy(
        self,
        geo_ids: Sequence[int],
        *,
        use_cache: bool = True,
    ) -> List[GeoRegion]:
        """Иерархия регионов с потомками (`getGeoHierarchy`).

        :param geo_ids: ID регионов-корней.
        :param use_cache: использовать ли дисковый кэш.
        :return: плоский список регионов вместе с потомками.
        """
        if not geo_ids:
            return []
        items = self._dictionary(
            "getGeoHierarchy",
            {
                "GeoRegionIds": list(geo_ids),
                "GeoRegionFieldNames": _GEO_FIELDS,
            },
            "GeoRegions",
            use_cache=use_cache,
        )
        return self._parse(items, GeoRegion)

    # ---------------- интересы и ключевые фразы ----------------
    def interests(
        self,
        geo_id: Optional[int] = None,
        *,
        use_cache: bool = True,
    ) -> List[Interest]:
        """Интересы (`getInterests`), опционально для одного региона.

        :param geo_id: ID региона; None — справочник по умолчанию.
        :param use_cache: использовать ли дисковый кэш.
        :return: список интересов.
        """
        params: Dict[str, Any] = {"InterestFieldNames": _INTEREST_FIELDS}
        if geo_id is not None:
            params["GeoId"] = int(geo_id)
        items = self._dictionary(
            "getInterests", params, "Interests", use_cache=use_cache
        )
        return self._parse(items, Interest)

    def keywords(
        self,
        keyword: str,
        geo_ids: Optional[Sequence[int]] = None,
        ad_types: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Подсказки ключевых фраз (`getKeywords`).

        Ответ — плоский словарь (не список), поэтому метод отдаёт сырые данные.

        :param keyword: начало фразы.
        :param geo_ids: регионы, для которых нужны подсказки.
        :param ad_types: типы объявлений (см. `ad_types()`).
        :return: сырые подсказки из `result` (значения API не приводятся к
            типизированным моделям — формат ответа зависит от AdTypes).
        """
        if not keyword.strip():
            raise ApiError("keyword для getKeywords не может быть пустым")
        params: Dict[str, Any] = {"Keyword": keyword}
        if geo_ids:
            params["GeoIds"] = list(geo_ids)[:DICTIONARIES_GET_MAX]
        if ad_types:
            params["AdTypes"] = list(ad_types)
        payload: Dict[str, Any] = {
            "method": "get",
            "params": {"getKeywords": params},
        }
        result: Dict[str, Any] = self._transport.post_result("dictionaries", payload)
        return result

    # ---------------- ретаргетинг и сайты ----------------
    def retargeting_lists(self, *, use_cache: bool = True) -> List[RetargetingList]:
        """Сегменты ретаргетинга (`getRetargetingLists`).

        :param use_cache: использовать ли дисковый кэш.
        :return: список доступных сегментов.
        """
        items = self._dictionary(
            "getRetargetingLists",
            {"RetargetingListFieldNames": _RETARGETING_FIELDS},
            "RetargetingLists",
            use_cache=use_cache,
        )
        return self._parse(items, RetargetingList)

    def sites(self, *, use_cache: bool = True) -> List[Site]:
        """Сайты клиента (`getSites`).

        :param use_cache: использовать ли дисковый кэш.
        :return: список сайтов.
        """
        items = self._dictionary(
            "getSites",
            {"SiteFieldNames": _SITE_FIELDS},
            "Sites",
            use_cache=use_cache,
        )
        return self._parse(items, Site)

    # ---------------- прочие справочники ----------------
    def ad_types(self, *, use_cache: bool = True) -> List[AdType]:
        """Типы объявлений (`getAdTypes`).

        :param use_cache: использовать ли дисковый кэш.
        :return: список типов объявлений.
        """
        items = self._dictionary(
            "getAdTypes",
            {"AdTypeFieldNames": _AD_TYPE_FIELDS},
            "AdTypes",
            use_cache=use_cache,
        )
        return self._parse(items, AdType)

    def time_zones(self, *, use_cache: bool = True) -> List[TimeZone]:
        """Часовые пояса (`getTimeZones`).

        :param use_cache: использовать ли дисковый кэш.
        :return: список часовых поясов.
        """
        items = self._dictionary(
            "getTimeZones",
            {"TimeZoneFieldNames": _TIME_ZONE_FIELDS},
            "TimeZones",
            use_cache=use_cache,
        )
        return self._parse(items, TimeZone)

    def currency(self) -> Currency:
        """Валюта аккаунта (`getCurrency`).

        Ответ — объект, а не список, поэтому кэш здесь не используется.

        :return: валюта аккаунта.
        :raises ApiError: если ответ не содержит валюту.
        """
        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "getCurrency": {"CurrencyFieldNames": _CURRENCY_FIELDS},
            },
        }
        result = self._transport.post_result("dictionaries", payload)
        currencies = result.get("Currencies")
        if not isinstance(currencies, list) or not currencies:
            raise ApiError("Справочник getCurrency не вернул Currencies", response_body=result)
        first = currencies[0]
        if not isinstance(first, dict):
            raise ApiError("Некорректная запись валюты", response_body=result)
        return Currency.from_dict(first)

    # ---------------- сегменты аудитории (слой 4) ----------------
    def _audience_dictionary(
        self,
        dictionary: str,
        result_key: str,
        *,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """Загрузить справочник по `DictionaryNames` (новый формат `dictionaries`).

        Справочники сегментов (`AudienceDemographicProfiles`, `AudienceInterests`,
        `AudienceCriteriaTypes`) запрашиваются не объектом-ключом в `params`, а
        элементом массива `DictionaryNames`, и не имеют `*FieldNames`.

        :param dictionary: имя справочника.
        :param result_key: имя списка в `result` ответа.
        :param use_cache: использовать ли дисковый кэш.
        :return: список сырых записей справочника.
        :raises ApiError: если в ответе нет ожидаемого списка.
        """
        cache_key: Dict[str, Any] = {"dictionary": dictionary, "params": {}}
        if use_cache:
            cached = self._cache.get(dictionary, cache_key)
            if cached is not None:
                return list(cached)

        payload: Dict[str, Any] = {
            "method": "get",
            "params": {"DictionaryNames": [dictionary]},
        }
        result = self._transport.post_result("dictionaries", payload)
        items = result.get(result_key)
        if not isinstance(items, list):
            raise ApiError(
                f"Справочник {dictionary} не вернул список {result_key}",
                response_body=result,
            )
        raw_items: List[Dict[str, Any]] = [i for i in items if isinstance(i, dict)]
        if use_cache:
            self._cache.set(dictionary, cache_key, raw_items)
        return raw_items

    def audience_criteria_types(
        self, *, use_cache: bool = True
    ) -> List[AudienceCriteriaType]:
        """Характеристики аудитории (`AudienceCriteriaTypes`).

        По ним видно, какие сегменты бывают (возраст, пол, доход и т. д.) и
        можно ли выбрать сразу все сегменты характеристики (`CanSelect`).

        :param use_cache: использовать ли дисковый кэш.
        :return: список характеристик.
        """
        items = self._audience_dictionary(
            "AudienceCriteriaTypes", "AudienceCriteriaTypes", use_cache=use_cache
        )
        return self._parse(items, AudienceCriteriaType)

    def audience_demographic_profiles(
        self, *, use_cache: bool = True
    ) -> List[AudienceDemographicProfile]:
        """Сегменты по демографии и поведению (`AudienceDemographicProfiles`).

        Эти сегменты кладутся в правила ретаргетинг-листа типа `AUDIENCE`
        как `ExternalId`.

        :param use_cache: использовать ли дисковый кэш.
        :return: список сегментов.
        """
        items = self._audience_dictionary(
            "AudienceDemographicProfiles",
            "AudienceDemographicProfiles",
            use_cache=use_cache,
        )
        return self._parse(items, AudienceDemographicProfile)

    def audience_interests(
        self, *, use_cache: bool = True
    ) -> List[AudienceInterestSegment]:
        """Сегменты по пользовательским интересам (`AudienceInterests`).

        Уже содержит префикс типа интереса в `id` — в правило ретаргетинг-листа
        кладётся `id`, а не `interest_key`.

        :param use_cache: использовать ли дисковый кэш.
        :return: список сегментов интересов.
        """
        items = self._audience_dictionary(
            "AudienceInterests", "AudienceInterests", use_cache=use_cache
        )
        return self._parse(items, AudienceInterestSegment)

    def audience_profiles_of_type(
        self, criteria_type: str, *, use_cache: bool = True
    ) -> List[AudienceDemographicProfile]:
        """Сегменты одной характеристики (например, только возраст или пол).

        :param criteria_type: тип характеристики из `AudienceCriteriaTypes`.
        :param use_cache: использовать ли дисковый кэш.
        :return: отфильтрованный список сегментов.
        """
        return [
            segment
            for segment in self.audience_demographic_profiles(use_cache=use_cache)
            if segment.type == criteria_type
        ]

    def bing_types(self, *, use_cache: bool = True) -> List[Dict[str, Any]]:
        """Типы площадок Bing (`getBingTypes`).

        :param use_cache: использовать ли дисковый кэш.
        :return: сырые записи справочника.
        """
        return self._dictionary(
            "getBingTypes",
            {"BingTypesFieldNames": ["BingType", "Name"]},
            "BingTypes",
            use_cache=use_cache,
        )

    def dicts(
        self,
        field: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        use_cache: bool = True,
        parser: Optional[Callable[[Dict[str, Any]], List[_T]]] = None,
    ) -> Any:
        """Эскапирующий доступ к любому словарю `dictionaries`.

        Нужен для справочников, которых нет в типизированных методах
        (`getDictionaries`, `getCampaignRegions`, новые словаря Яндекса).

        :param field: имя словаря (ключ в `params` запроса).
        :param params: параметры словаря; если не заданы — запрашиваются все
            поля справочника (`<Field>FieldNames` не передаётся).
        :param use_cache: использовать ли дисковый кэш.
        :param parser: необязательная функция разбора `result`;
            по умолчанию возвращаются `DictEntry` (по одной на список ответа).
        :return: результат парсера либо список `DictEntry`.
        """
        dictionary_params: Dict[str, Any] = dict(params or {})
        result = self._transport.post_result(
            "dictionaries",
            {"method": "get", "params": {field: dictionary_params}},
        )
        if parser is not None:
            return parser(result)
        return DictEntry.from_result(result)


__all__ = ["DictionariesService", "DEFAULT_TTL_SECONDS"]
