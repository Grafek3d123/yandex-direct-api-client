"""Билдеры групп объявлений для классической РСЯ и поиска (F-2A.2).

Состав полей сверен с документацией (снимок 30.09.2026):
https://yandex.ru/dev/direct/doc/ru/adgroups/add.md

Что важно знать о контракте `adgroups/add`:

- поля `Type` в **запросе нет** — тип группы определяется тем, какая
  типоспецифичная структура передана (`CpmBannerKeywordsAdGroup: {}` или
  `CpmBannerUserProfileAdGroup: {}`); `Type` приходит только в ответе
  `adgroups/get`;
- обязательны `Name` (1..255 символов), `CampaignId` и непустой `RegionIds`;
- `AutotargetingSettings` в `adgroups/add` **не существует**: автотаргетинг —
  отдельная сущность. В группе задаётся только `SmartAdGroup` (ЕПК/смарт).

`RegionIds` проверяется на непустоту и на отсутствие `0`
(см. `validation.Validator.region_ids`): `RegionIds: []` и `RegionIds: [0]`
API отвергает, поэтому такую ошибку дешевле поймать до запроса.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from ..exceptions import ValidationError
from ..validation import AD_GROUP_NAME_MAX_LENGTH, AD_HREF_MAX_LENGTH, Validator
from .ad_group import AdGroup

_logger = logging.getLogger(__name__)

#: Тип группы классической РСЯ (значение из `adgroups/get`).
AD_GROUP_TYPE_BANNER = "CPM_BANNER_AD_GROUP"

#: Тип группы для текстовых (поисковых) кампаний.
AD_GROUP_TYPE_TEXT = "TEXT_AD_GROUP"

#: Тип группы смарт-кампании/ЕПК.
AD_GROUP_TYPE_SMART = "SMART_AD_GROUP"

#: Тип группы ЕПК (`v501`).
AD_GROUP_TYPE_UNIFIED = "UNIFIED_AD_GROUP"

#: Тип видео-группы РСЯ.
AD_GROUP_TYPE_CPM_VIDEO = "CPM_VIDEO_AD_GROUP"

#: Тип группы динамических объявлений по сайту.
AD_GROUP_TYPE_DYNAMIC_SITE = "DYNAMIC_SITE_AD_GROUP"

#: Тип группы динамических объявлений по фиду.
AD_GROUP_TYPE_DYNAMIC_FEED = "DYNAMIC_FEED_AD_GROUP"

#: Тип группы под мобильные приложения.
AD_GROUP_TYPE_MOBILE_APP = "MOBILE_APP_AD_GROUP"

#: Категории автотаргетинга (docs: adgroups/add, AutotargetingCategoriesEnum).
AUTOTARGETING_CATEGORIES = (
    "EXACT",
    "ALTERNATIVE",
    "COMPETITOR",
    "BROADER",
    "ACCESSORY",
)

#: Подтип CPM-группы: показы по ключевым фразам.
CPM_BANNER_SUBTYPE_KEYWORDS = "KEYWORDS"

#: Подтип CPM-группы: показы по профилю пользователя.
CPM_BANNER_SUBTYPE_USER_PROFILE = "USER_PROFILE"

#: Максимум наборов минус-фраз у группы (docs: adgroups/add).
NEGATIVE_KEYWORD_SHARED_SET_MAX = 3


@dataclass
class AdGroupBuilder:
    """Общие поля билдера группы объявлений.

    :param name: имя группы (1..255 символов).
    :param campaign_id: ID кампании (обязателен для `adgroups/add`).
    :param region_ids: ID регионов показа; обязательны и непусты.
    :param negative_keywords: минус-фразы группы (`NegativeKeywords.Items`).
    :param negative_keywords_shared_set_ids: наборы минус-фраз (ArrayOfLong).
    :param tracking_params: UTM-метки группы одной строкой (до 1024).
    :param type: тип группы (только для чтения и `to_model`, в add не
        отправляется — API определяет тип по типовой структуре).
    :param extra: дополнительные поля тела (escape-hatch).
    """

    name: str
    campaign_id: int
    region_ids: List[int] = field(default_factory=list)
    negative_keywords: Optional[Sequence[str]] = None
    negative_keywords_shared_set_ids: Optional[Sequence[int]] = None
    tracking_params: Optional[str] = None
    type: str = AD_GROUP_TYPE_TEXT
    extra: Mapping[str, Any] = field(default_factory=dict)

    # ---------------- служебное ----------------
    def _validate_common(self, *, include_campaign: bool) -> None:
        """Проверить общие поля группы.

        :param include_campaign: проверять ли `CampaignId` (только для add).
        :raises ValidationError: при нарушении.
        """
        validator = Validator(True)
        validator.name(
            self.name, field="AdGroup.Name", max_length=AD_GROUP_NAME_MAX_LENGTH
        )
        if include_campaign:
            validator.ids([self.campaign_id], field="AdGroup.CampaignId")
        validator.region_ids(self.region_ids)
        if self.tracking_params is not None and len(self.tracking_params) > AD_HREF_MAX_LENGTH:
            raise ValidationError(
                f"AdGroup.TrackingParams длиннее {AD_HREF_MAX_LENGTH} символов"
            )
        if (
            self.negative_keywords_shared_set_ids is not None
            and len(self.negative_keywords_shared_set_ids) > NEGATIVE_KEYWORD_SHARED_SET_MAX
        ):
            raise ValidationError(
                "AdGroup.NegativeKeywordSharedSetIds: не более "
                f"{NEGATIVE_KEYWORD_SHARED_SET_MAX} наборов"
            )

    def _common_body(self, *, include_campaign: bool) -> Dict[str, Any]:
        """Собрать общую часть тела группы.

        :param include_campaign: включать ли `CampaignId` (только для add).
        :return: словарь с общими полями.
        """
        body: Dict[str, Any] = {}
        if include_campaign:
            body["CampaignId"] = int(self.campaign_id)
        body["Name"] = self.name
        body["RegionIds"] = list(self.region_ids)
        if self.negative_keywords is not None:
            body["NegativeKeywords"] = {"Items": list(self.negative_keywords)}
        if self.negative_keywords_shared_set_ids is not None:
            Validator(True).ids(
                list(self.negative_keywords_shared_set_ids),
                field="AdGroup.NegativeKeywordSharedSetIds",
            )
            body["NegativeKeywordSharedSetIds"] = {
                "Items": [int(x) for x in self.negative_keywords_shared_set_ids]
            }
        if self.tracking_params:
            body["TrackingParams"] = self.tracking_params
        return body

    def _type_body(self) -> Dict[str, Any]:
        """Типоспецифичная структура группы (пусто для поисковых групп).

        :return: словарь, который нужно подмешать в тело `adgroups/add`.
        """
        return {}

    # ---------------- публичное ----------------
    def to_payload(self) -> Dict[str, Any]:
        """Тело `adgroups/add` с обязательными `CampaignId`, `Name`, `RegionIds`.

        :return: словарь для `params.AdGroups`.
        :raises ValidationError: невалидное имя, кампания или список регионов.
        """
        self._validate_common(include_campaign=True)
        body = self._common_body(include_campaign=True)
        body.update(self._type_body())
        for key, value in self.extra.items():
            body.setdefault(key, value)
        return body

    def to_model(self) -> AdGroup:
        """Представить билдер моделью `AdGroup` (удобно для чтения/обновления).

        :return: модель группы с теми же полями, что и билдер.
        """
        return AdGroup(
            id=0,
            campaign_id=int(self.campaign_id),
            name=self.name,
            type=self.type,
            region_ids=list(self.region_ids),
            negative_keywords_shared_set_ids=(
                list(self.negative_keywords_shared_set_ids)
                if self.negative_keywords_shared_set_ids
                else None
            ),
        )

    def to_update_payload(self, ad_group_id: int) -> Dict[str, Any]:
        """Тело `adgroups/update` (Id + изменяемые поля, без `CampaignId`).

        :param ad_group_id: ID обновляемой группы.
        :return: словарь для запроса обновления.
        :raises ValidationError: при нарушении ограничений.
        """
        self._validate_common(include_campaign=False)
        body = self._common_body(include_campaign=False)
        body["Id"] = int(ad_group_id)
        type_body = self._type_body()
        if type_body:
            body.update(type_body)
        return body


@dataclass
class TextAdGroup(AdGroupBuilder):
    """Группа для поисковых кампаний (`TEXT_AD_GROUP`).

    Типовой структуры у группы нет: достаточно `Name`, `CampaignId`,
    `RegionIds`.
    """

    type: str = AD_GROUP_TYPE_TEXT


@dataclass
class CpmBannerAdGroup(AdGroupBuilder):
    """Группа классической РСЯ (`CPM_BANNER_AD_GROUP`).

    Тип группы задаётся **пустой** структурой в запросе:
    `CpmBannerKeywordsAdGroup: {}` для показов по ключевым фразам либо
    `CpmBannerUserProfileAdGroup: {}` для показов по профилю пользователя.
    У профильного варианта минус-фразы на уровне группы запрещены.

    :param subtype: `KEYWORDS` (по умолчанию) или `USER_PROFILE`.
    """

    subtype: str = CPM_BANNER_SUBTYPE_KEYWORDS
    type: str = AD_GROUP_TYPE_BANNER

    def _type_body(self) -> Dict[str, Any]:
        """Пустая типовая структура CPM-группы.

        :return: словарь с одним из ключей `CpmBanner*AdGroup`.
        :raises ValidationError: неизвестный подтип или минус-фразы в
            профильном варианте.
        """
        if self.subtype == CPM_BANNER_SUBTYPE_KEYWORDS:
            return {"CpmBannerKeywordsAdGroup": {}}
        if self.subtype == CPM_BANNER_SUBTYPE_USER_PROFILE:
            if self.negative_keywords:
                raise ValidationError(
                    "CpmBannerUserProfileAdGroup не поддерживает NegativeKeywords"
                )
            return {"CpmBannerUserProfileAdGroup": {}}
        raise ValidationError(
            f"Неизвестный подтип CPM-группы {self.subtype!r}; доступно: "
            f"{CPM_BANNER_SUBTYPE_KEYWORDS}, {CPM_BANNER_SUBTYPE_USER_PROFILE}"
        )


@dataclass
class AutotargetingSetting:
    """Настройка категории автотаргетинга (`AutotargetingCategoriesAddItem`).

    Применима к динамическим группам (по сайту и по фиду). Все категории
    включены по умолчанию, поэтому `enabled=False` — осмысленное выключение
    одной категории.

    :param category: `EXACT`, `ALTERNATIVE`, `COMPETITOR`, `BROADER`
        или `ACCESSORY`.
    :param enabled: включить ли категорию (`YES`/`NO` в API). По умолчанию
        категория включена; `None` — выбрать за бизнес с предупреждением.
    """

    category: str
    enabled: Optional[bool] = None

    def __post_init__(self) -> None:
        """Проверить имя категории и подставить дефолт `enabled`.

        :raises ValidationError: неизвестная категория.
        """
        Validator(True).one_of(
            self.category, AUTOTARGETING_CATEGORIES, field="Autotargeting.Category"
        )
        if self.enabled is None:
            _logger.warning(
                "AutotargetingSetting: enabled не задан — SDK включает категорию "
                "(передайте enabled=False, чтобы выключить)"
            )
            self.enabled = True

    def to_payload(self) -> Dict[str, Any]:
        """Тело настройки категории.

        :return: словарь `{"Category": ..., "Value": ...}`.
        """
        return {"Category": self.category, "Value": "YES" if self.enabled else "NO"}


def _autotargeting_body(
    settings: Optional[Sequence[Union[AutotargetingSetting, Mapping[str, Any]]]],
) -> List[Dict[str, Any]]:
    """Собрать `AutotargetingCategories` из настроек или словарей.

    :param settings: настройки категорий либо готовые словари.
    :return: список тел настроек.
    :raises ValidationError: неверный элемент.
    """
    if not settings:
        return []
    body: List[Dict[str, Any]] = []
    for item in settings:
        if isinstance(item, AutotargetingSetting):
            body.append(item.to_payload())
        elif isinstance(item, Mapping):
            body.append(dict(item))
        else:
            raise ValidationError(
                f"AutotargetingSettings: ожидается AutotargetingSetting или dict, "
                f"получено {type(item).__name__}"
            )
    return body


@dataclass
class SmartAdGroup(AdGroupBuilder):
    """Группа смарт-кампании/ЕПК (`SMART_AD_GROUP`).

    :param feed_id: ID фида (`SmartAdGroup.FeedId`) — обязателен для групп,
        работающих по данным фида.
    :param ad_title_source: источник заголовков объявления.
    :param ad_body_source: источник текстов объявления.
    """

    feed_id: Optional[int] = None
    ad_title_source: Optional[str] = None
    ad_body_source: Optional[str] = None
    type: str = AD_GROUP_TYPE_SMART

    def _type_body(self) -> Dict[str, Any]:
        """Типовая структура `SmartAdGroup`.

        :return: словарь `SmartAdGroup` с заданными полями.
        """
        smart: Dict[str, Any] = {}
        if self.feed_id is not None:
            Validator(True).ids([self.feed_id], field="SmartAdGroup.FeedId")
            smart["FeedId"] = int(self.feed_id)
        if self.ad_title_source is not None:
            smart["AdTitleSource"] = self.ad_title_source
        if self.ad_body_source is not None:
            smart["AdBodySource"] = self.ad_body_source
        return {"SmartAdGroup": smart} if smart else {}


@dataclass
class DynamicSiteAdGroup(AdGroupBuilder):
    """Группа динамических объявлений по сайту (`DYNAMIC_SITE_AD_GROUP`).

    :param domain_url: домен сайта (до 100 символов, протокол можно опустить).
    :param autotargeting_settings: настройки категорий автотаргетинга.
    """

    domain_url: str = ""
    autotargeting_settings: Optional[
        Sequence[Union[AutotargetingSetting, Mapping[str, Any]]]
    ] = None
    type: str = AD_GROUP_TYPE_DYNAMIC_SITE

    def _type_body(self) -> Dict[str, Any]:
        """Типовая структура `DynamicTextAdGroup`.

        :return: словарь `DynamicTextAdGroup` с доменом и настройками.
        :raises ValidationError: не задан домен или он длиннее 100 символов.
        """
        Validator(True).text(
            self.domain_url, field="DynamicTextAdGroup.DomainUrl", max_length=100
        )
        dynamic: Dict[str, Any] = {"DomainUrl": self.domain_url}
        categories = _autotargeting_body(self.autotargeting_settings)
        if categories:
            dynamic["AutotargetingCategories"] = categories
        return {"DynamicTextAdGroup": dynamic}


@dataclass
class DynamicFeedAdGroup(AdGroupBuilder):
    """Группа динамических объявлений по фиду (`DYNAMIC_FEED_AD_GROUP`).

    :param feed_id: ID фида — обязателен.
    :param autotargeting_settings: настройки категорий автотаргетинга.
    """

    feed_id: Optional[int] = None
    autotargeting_settings: Optional[
        Sequence[Union[AutotargetingSetting, Mapping[str, Any]]]
    ] = None
    type: str = AD_GROUP_TYPE_DYNAMIC_FEED

    def _type_body(self) -> Dict[str, Any]:
        """Типовая структура `DynamicTextFeedAdGroup`.

        :return: словарь `DynamicTextFeedAdGroup` с фидом и настройками.
        :raises ValidationError: не задан `feed_id`.
        """
        if self.feed_id is None:
            raise ValidationError(
                "DynamicTextFeedAdGroup требует FeedId — группы по фиду без фида "
                "создать нельзя"
            )
        Validator(True).ids([self.feed_id], field="DynamicTextFeedAdGroup.FeedId")
        dynamic: Dict[str, Any] = {"FeedId": int(self.feed_id)}
        categories = _autotargeting_body(self.autotargeting_settings)
        if categories:
            dynamic["AutotargetingCategories"] = categories
        return {"DynamicTextFeedAdGroup": dynamic}


@dataclass
class UnifiedAdGroup(AdGroupBuilder):
    """Группа ЕПК (`UNIFIED_AD_GROUP`, только `v501`).

    Требует структуры `UnifiedAdGroup: {OfferRetargeting}` — она обязательна
    в `adgroups/add` для ЕПК-группы. Гео (`RegionIds`) у ЕПК задаётся здесь
    же, поэтому для ЕПК используется тот же `RegionSelector`, что и для v5.

    :param offer_retargeting: включить ли ретаргетинг по товарам (`YES`/`NO`).
    """

    offer_retargeting: str = "NO"
    type: str = AD_GROUP_TYPE_UNIFIED

    def _type_body(self) -> Dict[str, Any]:
        """Обязательная структура `UnifiedAdGroup`.

        :return: словарь `UnifiedAdGroup` с полем `OfferRetargeting`.
        :raises ValidationError: недопустимое значение `OfferRetargeting`.
        """
        Validator(True).one_of(
            self.offer_retargeting, ("YES", "NO"), field="UnifiedAdGroup.OfferRetargeting"
        )
        return {"UnifiedAdGroup": {"OfferRetargeting": self.offer_retargeting}}


#: Соответствие «тип группы → класс-билдер».
AD_GROUP_BUILDERS: Mapping[str, Any] = {
    AD_GROUP_TYPE_BANNER: CpmBannerAdGroup,
    AD_GROUP_TYPE_TEXT: TextAdGroup,
    AD_GROUP_TYPE_SMART: SmartAdGroup,
    AD_GROUP_TYPE_UNIFIED: UnifiedAdGroup,
    AD_GROUP_TYPE_DYNAMIC_SITE: DynamicSiteAdGroup,
    AD_GROUP_TYPE_DYNAMIC_FEED: DynamicFeedAdGroup,
}

#: Билдер группы, принимаемый сервисом `ad_groups.create`.
AdGroupBuilderInput = Union[AdGroupBuilder, Mapping[str, Any]]


def build_ad_group(kind: str, **kwargs: Any) -> AdGroupBuilder:
    """Собрать билдер группы объявлений по типу группы.

    :param kind: `CPM_BANNER_AD_GROUP`, `TEXT_AD_GROUP`, `SMART_AD_GROUP`
        или `UNIFIED_AD_GROUP` (ЕПК, только v501).
    :param kwargs: поля конструктора выбранного билдера.
    :return: экземпляр билдера.
    :raises ValidationError: неизвестный тип группы.
    """
    builder_cls = AD_GROUP_BUILDERS.get(kind)
    if builder_cls is None:
        known = ", ".join(sorted(AD_GROUP_BUILDERS))
        raise ValidationError(f"Неизвестный тип группы {kind!r}; доступно: {known}")
    builder: AdGroupBuilder = builder_cls(**kwargs)
    return builder


def ad_group_body(item: AdGroupBuilderInput) -> Dict[str, Any]:
    """Привести билдер или словарь к телу `adgroups/add`.

    :param item: билдер группы либо готовый dict.
    :return: словарь для отправки.
    """
    if isinstance(item, AdGroupBuilder):
        return item.to_payload()
    return dict(item)


__all__ = [
    "AD_GROUP_BUILDERS",
    "AD_GROUP_TYPE_BANNER",
    "AD_GROUP_TYPE_CPM_VIDEO",
    "AD_GROUP_TYPE_DYNAMIC_FEED",
    "AD_GROUP_TYPE_DYNAMIC_SITE",
    "AD_GROUP_TYPE_MOBILE_APP",
    "AD_GROUP_TYPE_SMART",
    "AD_GROUP_TYPE_TEXT",
    "AD_GROUP_TYPE_UNIFIED",
    "AUTOTARGETING_CATEGORIES",
    "CPM_BANNER_SUBTYPE_KEYWORDS",
    "CPM_BANNER_SUBTYPE_USER_PROFILE",
    "AdGroupBuilder",
    "AdGroupBuilderInput",
    "AutotargetingSetting",
    "CpmBannerAdGroup",
    "DynamicFeedAdGroup",
    "DynamicSiteAdGroup",
    "SmartAdGroup",
    "TextAdGroup",
    "UnifiedAdGroup",
    "ad_group_body",
    "build_ad_group",
]
