"""Матрица допустимости нацеливания и константы таргетинга (слой 4).

Единое место, где зафиксировано, какое условие нацеливания можно применить
к группе объявлений. Значения сверены с документацией (снимок 30.09.2026):

- https://yandex.com/dev/direct/doc/en/objects/audience-target.md
- https://yandex.com/dev/direct/doc/en/objects/retargeting-list.md
- https://yandex.com/dev/direct/doc/en/audiencetargets/add.md

Ключевые ограничения из документации:

- условия нацеливания показываются **только в сетях** (РСЯ и внешние сети),
  в поиске они не работают;
- `InterestId` (категории мобильных приложений) допустим **только** для
  `MOBILE_APP_AD_GROUP`, и только для интересов с `IsTargetable: YES`;
- `CPM_BANNER_AD_GROUP` с подтипом `KEYWORDS` не принимает условия нацеливания
  вообще, с подтипом `USER_PROFILE` — не больше одного;
- `CPM_VIDEO_AD_GROUP` — не больше одного условия;
- `TEXT_AD_GROUP` — не больше 50 условий, при этом условие типа `AUDIENCE`
  (демография, поведение, интересы) — **не больше одного**;
- демография, поведение и пользовательские интересы — это не отдельные поля
  `audiencetargets`, а **ретаргетинг-листы типа `AUDIENCE`** с правилами
  отбора по сегментам (`retargetinglists`).
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Optional

from .exceptions import ValidationError

#: Вид условия нацеливания.
TARGET_KIND_RETARGETING = "retargeting"
TARGET_KIND_DEMOGRAPHICS = "demographics"
TARGET_KIND_INTEREST = "interest"
TARGET_KIND_KEYWORD = "keyword"

#: Все известные виды условий.
TARGET_KINDS = (
    TARGET_KIND_RETARGETING,
    TARGET_KIND_DEMOGRAPHICS,
    TARGET_KIND_INTEREST,
    TARGET_KIND_KEYWORD,
)

#: Тип группы: мобильные приложения.
AD_GROUP_TYPE_MOBILE_APP = "MOBILE_APP_AD_GROUP"

#: Тип группы: динамические объявления по сайту.
AD_GROUP_TYPE_DYNAMIC_SITE = "DYNAMIC_SITE_AD_GROUP"

#: Тип группы: динамические объявления по фиду.
AD_GROUP_TYPE_DYNAMIC_FEED = "DYNAMIC_FEED_AD_GROUP"

#: Префикс `ExternalId` для сегмента пользовательского интереса.
#: Сегмент = префикс типа интереса + ID интереса (docs: retargetinglists/add).
INTEREST_PREFIX_SHORT_TERM = 10
INTEREST_PREFIX_LONG_TERM = 20
INTEREST_PREFIX_ANY = 30

#: Тип сегмента в `AudienceInterests` (docs: dictionaries/get).
INTEREST_TYPE_SHORT_TERM = "SHORT_TERM"
INTEREST_TYPE_LONG_TERM = "LONG_TERM"
INTEREST_TYPE_ANY = "ANY"

#: Префикс типа интереса → его строковое значение в справочнике.
INTEREST_TYPE_TO_PREFIX = MappingProxyType(
    {
        INTEREST_TYPE_SHORT_TERM: INTEREST_PREFIX_SHORT_TERM,
        INTEREST_TYPE_LONG_TERM: INTEREST_PREFIX_LONG_TERM,
        INTEREST_TYPE_ANY: INTEREST_PREFIX_ANY,
    }
)

#: Тип ретаргетинг-листа: цели/сегменты Метрики и Аудитории.
RETARGETING_LIST_TYPE_RETARGETING = "RETARGETING"

#: Тип ретаргетинг-листа: любые цели, демография, поведение, интересы.
RETARGETING_LIST_TYPE_AUDIENCE = "AUDIENCE"

#: Логический оператор правила отбора пользователей.
RETARGETING_RULE_ALL = "ALL"
RETARGETING_RULE_ANY = "ANY"
RETARGETING_RULE_NONE = "NONE"
RETARGETING_RULE_OPERATORS = (
    RETARGETING_RULE_ALL,
    RETARGETING_RULE_ANY,
    RETARGETING_RULE_NONE,
)

#: Настройки автотаргетинга (docs: adgroups/add, AutotargetingCategoriesEnum).
AUTOTARGETING_CATEGORIES = ("EXACT", "ALTERNATIVE", "COMPETITOR", "BROADER", "ACCESSORY")

#: Максимум условий нацеливания на группу (docs: objects/audience-target).
#: ``None`` означает, что документация лимита не устанавливает.
AUDIENCE_TARGETS_PER_AD_GROUP: Mapping[str, Optional[int]] = MappingProxyType(
    {
        "TEXT_AD_GROUP": 50,
        "MOBILE_APP_AD_GROUP": 50,
        "CPM_BANNER_AD_GROUP": 1,
        "CPM_VIDEO_AD_GROUP": 1,
        "SMART_AD_GROUP": None,
        "UNIFIED_AD_GROUP": None,
        "DYNAMIC_SITE_AD_GROUP": None,
        "DYNAMIC_FEED_AD_GROUP": None,
    }
)

#: Лимит условий типа `AUDIENCE` (демография/поведение/интересы) на группу.
#: Для `TEXT_AD_GROUP` это 1, для медийных групп ограничение общее — 1.
AUDIENCE_TYPE_TARGETS_PER_AD_GROUP: Mapping[str, Optional[int]] = MappingProxyType(
    {
        "TEXT_AD_GROUP": 1,
        "CPM_BANNER_AD_GROUP": 1,
        "CPM_VIDEO_AD_GROUP": 1,
        "MOBILE_APP_AD_GROUP": 1,
    }
)

#: Куда можно добавлять ретаргетинг-лист (любой подтип `RETARGETING`).
#: Тип кампании/группы `CPM_BANNER_AD_GROUP` с подтипом `KEYWORDS` исключён
#: отдельной проверкой — для него ретаргетинг недопустим вовсе.
RETARGETING_ALLOWED_AD_GROUP_TYPES = (
    "TEXT_AD_GROUP",
    "MOBILE_APP_AD_GROUP",
    "CPM_BANNER_AD_GROUP",
    "CPM_VIDEO_AD_GROUP",
    "SMART_AD_GROUP",
    "UNIFIED_AD_GROUP",
)

#: Куда можно добавлять условие по категории мобильного приложения.
INTEREST_ALLOWED_AD_GROUP_TYPES = (AD_GROUP_TYPE_MOBILE_APP,)

#: Куда можно добавлять демографию/поведение/интересы (лист типа `AUDIENCE`).
#: Это медийные группы (профиль посетителя) и текстовые группы — с ограничением
#: «не больше одного условия типа `AUDIENCE`» для текстовой группы.
AUDIENCE_LIST_ALLOWED_AD_GROUP_TYPES = (
    "TEXT_AD_GROUP",
    "CPM_BANNER_AD_GROUP",
    "CPM_VIDEO_AD_GROUP",
    "SMART_AD_GROUP",
    "UNIFIED_AD_GROUP",
)

#: Типы групп, к которым **неприменимы** ключевые фразы (`ad_group_items`).
#: Показы в РСЯ задаются сегментами, а не фразами.
KEYWORD_INCOMPATIBLE_AD_GROUP_TYPES = (
    "CPM_BANNER_AD_GROUP",
    "CPM_VIDEO_AD_GROUP",
    "UNIFIED_AD_GROUP",
)


def is_allowed(ad_group_type: str, kind: str) -> bool:
    """Проверить допустимость вида нацеливания для типа группы.

    :param ad_group_type: тип группы из `adgroups/get`.
    :param kind: вид условия (см. `TARGET_KINDS`).
    :return: True, если комбинация разрешена документацией.
    :raises ValidationError: неизвестный вид условия.
    """
    if kind not in TARGET_KINDS:
        raise ValidationError(
            f"Неизвестный вид нацеливания {kind!r}; доступно: {', '.join(TARGET_KINDS)}"
        )
    if kind == TARGET_KIND_RETARGETING:
        return ad_group_type in RETARGETING_ALLOWED_AD_GROUP_TYPES
    if kind == TARGET_KIND_INTEREST:
        return ad_group_type in INTEREST_ALLOWED_AD_GROUP_TYPES
    if kind == TARGET_KIND_DEMOGRAPHICS:
        return ad_group_type in AUDIENCE_LIST_ALLOWED_AD_GROUP_TYPES
    return ad_group_type not in KEYWORD_INCOMPATIBLE_AD_GROUP_TYPES


def explain(ad_group_type: str, kind: str) -> str:
    """Пояснить, почему комбинация «группа × нацеливание» недопустима.

    :param ad_group_type: тип группы из `adgroups/get`.
    :param kind: вид условия (см. `TARGET_KINDS`).
    :return: текст причины для сообщения `ValidationError`.
    """
    if kind == TARGET_KIND_INTEREST:
        return (
            f"нацеливание по категории мобильного приложения "
            f"({TARGET_KIND_INTEREST}) допустимо только для "
            f"{AD_GROUP_TYPE_MOBILE_APP}, а не для {ad_group_type}"
        )
    if kind == TARGET_KIND_RETARGETING:
        return (
            f"ретаргетинг недопустим для группы {ad_group_type}; "
            f"разрешено: {', '.join(RETARGETING_ALLOWED_AD_GROUP_TYPES)}"
        )
    if kind == TARGET_KIND_DEMOGRAPHICS:
        return (
            f"демография/поведение/интересы (лист типа AUDIENCE) недопустимы для "
            f"группы {ad_group_type}; разрешено: "
            f"{', '.join(AUDIENCE_LIST_ALLOWED_AD_GROUP_TYPES)}"
        )
    return (
        f"ключевые фразы неприменимы к группе {ad_group_type}: показы в РСЯ "
        f"задаются сегментами, а не ключевыми фразами"
    )


def keyword_conflict(ad_group_type: str) -> Optional[str]:
    """Проверить, что ключевые фразы применимы к группе.

    :param ad_group_type: тип группы из `adgroups/get`.
    :return: текст ошибки либо None, если тип группы подходит.
    """
    if ad_group_type in KEYWORD_INCOMPATIBLE_AD_GROUP_TYPES:
        return explain(ad_group_type, TARGET_KIND_KEYWORD)
    return None


def interest_prefix(interest_type: str) -> int:
    """Получить префикс типа интереса для `ExternalId` сегмента.

    :param interest_type: `SHORT_TERM`, `LONG_TERM` или `ANY`.
    :return: префикс (10, 20 или 30).
    :raises ValidationError: неизвестный тип интереса.
    """
    prefix = INTEREST_TYPE_TO_PREFIX.get(interest_type)
    if prefix is None:
        raise ValidationError(
            f"Неизвестный InterestType {interest_type!r}; доступно: "
            f"{', '.join(INTEREST_TYPE_TO_PREFIX)}"
        )
    return prefix


def segment_external_id(interest_id: int, interest_type: str) -> int:
    """Собрать `ExternalId` сегмента пользовательского интереса.

    По документации сегмент = префикс типа интереса + ID интереса:
    интерес `2499001182` с краткосрочным интересом даёт `102499001182`.

    :param interest_id: ID интереса (`InterestKey`).
    :param interest_type: `SHORT_TERM`, `LONG_TERM` или `ANY`.
    :return: `ExternalId` для правила ретаргетинг-листа.
    :raises ValidationError: неизвестный тип интереса или некорректный ID.
    """
    if isinstance(interest_id, bool) or not isinstance(interest_id, int):
        raise ValidationError(f"interest_id должен быть целым, получено {interest_id!r}")
    if interest_id <= 0:
        raise ValidationError(
            f"interest_id должен быть положительным, получено {interest_id}"
        )
    # Префикс приписывается к ID интереса строкой: «10» + 2499001182 = 102499001182.
    return int(f"{interest_prefix(interest_type)}{interest_id}")


__all__ = [
    "AD_GROUP_TYPE_DYNAMIC_FEED",
    "AD_GROUP_TYPE_DYNAMIC_SITE",
    "AD_GROUP_TYPE_MOBILE_APP",
    "AUDIENCE_LIST_ALLOWED_AD_GROUP_TYPES",
    "AUDIENCE_TARGETS_PER_AD_GROUP",
    "AUDIENCE_TYPE_TARGETS_PER_AD_GROUP",
    "AUTOTARGETING_CATEGORIES",
    "INTEREST_ALLOWED_AD_GROUP_TYPES",
    "INTEREST_PREFIX_ANY",
    "INTEREST_PREFIX_LONG_TERM",
    "INTEREST_PREFIX_SHORT_TERM",
    "INTEREST_TYPE_ANY",
    "INTEREST_TYPE_LONG_TERM",
    "INTEREST_TYPE_SHORT_TERM",
    "INTEREST_TYPE_TO_PREFIX",
    "KEYWORD_INCOMPATIBLE_AD_GROUP_TYPES",
    "RETARGETING_ALLOWED_AD_GROUP_TYPES",
    "RETARGETING_LIST_TYPE_AUDIENCE",
    "RETARGETING_LIST_TYPE_RETARGETING",
    "RETARGETING_RULE_ALL",
    "RETARGETING_RULE_ANY",
    "RETARGETING_RULE_NONE",
    "RETARGETING_RULE_OPERATORS",
    "TARGET_KIND_DEMOGRAPHICS",
    "TARGET_KIND_INTEREST",
    "TARGET_KIND_KEYWORD",
    "TARGET_KIND_RETARGETING",
    "TARGET_KINDS",
    "explain",
    "interest_prefix",
    "is_allowed",
    "keyword_conflict",
    "segment_external_id",
]
