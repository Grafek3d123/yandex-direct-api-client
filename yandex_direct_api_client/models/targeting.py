"""Таргетинг: демография, интересы и ретаргетинг (слой 4).

Важное ограничение API, которое определяет всю конструкцию модуля
(снимок документации 30.09.2026):
https://yandex.com/dev/direct/doc/en/objects/retargeting-list.md

Условия нацеливания в `audiencetargets` бывают только двух видов:

- `RetargetingListId` — ссылка на **ретаргетинг-лист**;
- `InterestId` — категория мобильного приложения, причём только для
  группы `MOBILE_APP_AD_GROUP`.

Демография, поведение и пользовательские интересы — это **не** поля
`audiencetargets`. Они задаются сегментами (`AudienceDemographicProfiles`,
`AudienceInterests`) внутри правил ретаргетинг-листа типа `AUDIENCE`.
Поэтому здесь четыре разных билдера:

- `RetargetingTarget` — условие по готовому сегменту (`RetargetingListId`);
- `InterestTarget` — условие по категории мобильного приложения;
- `DemographicsTarget` — набор демографических/поведенческих сегментов,
  который сначала превращается в ретаргетинг-лист типа `AUDIENCE`
  (`to_retargeting_list()`), затем в условие нацеливания
  (`to_audience_target(list_id)`);
- `ContextTarget` — нацеливание по контексту (странице сайта). В API v5 его
  **нет**: `audiencetargets` такого поля не содержит, поэтому билдер честно
  сообщает об этом `ValidationError`, а не молча игнорирует условие.

Спеки (`DemographicsSpec`, `InterestSpec`, `RetargetingSpec`) — это
пользовательский слой: они хранят осмысленные значения (пол, диапазоны возраста,
названия интересов), а билдеры превращают их в точные тела API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..constants import (
    AD_GROUP_TYPE_MOBILE_APP,
    AUDIENCE_LIST_ALLOWED_AD_GROUP_TYPES,
    INTEREST_ALLOWED_AD_GROUP_TYPES,
    RETARGETING_ALLOWED_AD_GROUP_TYPES,
    RETARGETING_LIST_TYPE_AUDIENCE,
    RETARGETING_LIST_TYPE_RETARGETING,
    RETARGETING_RULE_ANY,
    RETARGETING_RULE_OPERATORS,
    TARGET_KIND_DEMOGRAPHICS,
    TARGET_KIND_INTEREST,
    TARGET_KIND_RETARGETING,
    explain,
    is_allowed,
    keyword_conflict,
    segment_external_id,
)
from ..exceptions import ValidationError
from ..validation import Validator
from ._helpers import to_int, to_str

#: Значение `StrategyPriority` для автоматических стратегий.
PRIORITY_LOW = "LOW"
PRIORITY_NORMAL = "NORMAL"
PRIORITY_HIGH = "HIGH"
PRIORITIES = (PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH)

#: Пол аудитории. `ALL` в API не передаётся: значит «не ограничивать».
GENDER_MALE = "MALE"
GENDER_FEMALE = "FEMALE"
GENDER_ALL = "ALL"
GENDERS = (GENDER_MALE, GENDER_FEMALE, GENDER_ALL)

#: Тип характеристики демографии в справочнике `AudienceCriteriaTypes`.
CRITERIA_TYPE_AGE = "AGE"
CRITERIA_TYPE_GENDER = "GENDER"

#: Максимум правил в ретаргетинг-листе типа `RETARGETING` (docs: 1..50).
RETARGETING_RULES_MAX = 50

#: Максимум аргументов (целей/сегментов) в одном правиле (docs: 1..250).
RETARGETING_ARGUMENTS_MAX = 250

#: Диапазон `MembershipLifeSpan` в днях (docs: retargetinglists/add).
MEMBERSHIP_LIFE_SPAN_MIN = 1
MEMBERSHIP_LIFE_SPAN_MAX = 540

#: Тип сегмента по краткосрочным интересам мобильных приложений.
INTEREST_TYPE_SHORT_TERM = "SHORT_TERM"
INTEREST_TYPE_LONG_TERM = "LONG_TERM"
INTEREST_TYPE_ANY = "ANY"
INTEREST_TYPES = (INTEREST_TYPE_SHORT_TERM, INTEREST_TYPE_LONG_TERM, INTEREST_TYPE_ANY)


# ---------------------------------------------------------------- demographics


@dataclass
class DemographicsSpec:
    """Демографическое нацеливание: пол и диапазоны возраста.

    Значения `age_ranges` и `gender` — **названия сегментов** из справочника
    `AudienceDemographicProfiles` (например, «18-24», «Женщины»). Разрешаются
    в ID через `TargetingService.resolve_demographics()`, который ходит в
    справочник и кэширует его. `resolve()` на самой спеке работает, если
    сегменты уже загружены.

    Спека не локализуется сама: справочник `AudienceDemographicProfiles`
    возвращает названия сегментов на языке аккаунта, поэтому соответствие
    константе пола (`MALE`/`FEMALE`) должно задавать вызывающий через
    `gender_names` — SDK не зашивает русские (и не русские) строки. Список
    доступных названий можно получить через
    `TargetingService.demographic_segment_names("GENDER")`.

    :param age_ranges: названия возрастных сегментов.
    :param gender: пол аудитории; `ALL` — без ограничения.
    :param gender_names: сопоставление `gender` → название сегмента из
        справочника; обязательно, когда `gender != ALL`.
    """

    age_ranges: List[str] = field(default_factory=list)
    gender: str = GENDER_ALL
    gender_names: Optional[Mapping[str, str]] = None

    def __post_init__(self) -> None:
        """Нормализовать и проверить входные значения.

        :raises ValidationError: неизвестный пол или пустой набор сегментов.
        """
        self.age_ranges = [str(x) for x in self.age_ranges]
        Validator(True).one_of(self.gender, GENDERS, field="DemographicsSpec.gender")
        if not self.age_ranges and self.gender == GENDER_ALL:
            raise ValidationError(
                "DemographicsSpec пуст: укажите хотя бы один возрастной сегмент "
                "или gender, отличный от ALL"
            )


    def resolve(
        self, segments: Sequence[Any]
    ) -> List[int]:
        """Преобразовать названия сегментов в ID.

        :param segments: записи `AudienceDemographicProfile` из справочника
            (у каждой есть `id`, `type` и `name`).
        :return: список ID сегментов, подходящих спецификации.
        :raises ValidationError: сегмент не найден или найден с неоднозначным
            совпадением.
        """
        by_name: Dict[str, List[int]] = {}
        for segment in segments:
            by_name.setdefault(segment.name, []).append(int(segment.id))

        resolved: List[int] = []
        for age_range in self.age_ranges:
            resolved.append(_single_segment_id(by_name, age_range, CRITERIA_TYPE_AGE))
        if self.gender != GENDER_ALL:
            if not self.gender_names or self.gender not in self.gender_names:
                raise ValidationError(
                    "DemographicsSpec: укажите gender_names[cfg.gender]"
                    " — справочник AudienceDemographicProfiles локализован, "
                    "SDK не подставляет название пола за бизнес "
                    "(подсказка: "
                    "TargetingService.demographic_segment_names('GENDER'))"
                )
            gender_name = self.gender_names[self.gender]
            resolved.append(
                _single_segment_id(by_name, gender_name, CRITERIA_TYPE_GENDER)
            )
        return resolved


def _single_segment_id(
    by_name: Mapping[str, List[int]], name: str, criteria_type: str
) -> int:
    """Найти единственный ID сегмента по имени.

    :param by_name: карта «название → список ID».
    :param name: искомое название сегмента.
    :param criteria_type: ожидаемый тип характеристики (для сообщения).
    :return: ID сегмента.
    :raises ValidationError: сегмент не найден или найден несколько раз.
    """
    matches = by_name.get(name, [])
    if not matches:
        raise ValidationError(
            f"Сегмент {name!r} не найден в AudienceDemographicProfiles; "
            f"доступные примеры: {', '.join(sorted(by_name)[:5])}"
        )
    if len(matches) > 1:
        raise ValidationError(
            f"Сегмент {name!r} неоднозначен: подходит несколько ID "
            f"({', '.join(str(x) for x in matches)}). Уточните запрос "
            f"({criteria_type}) или укажите ID вручную"
        )
    return matches[0]


# ------------------------------------------------------------------- interests


@dataclass
class InterestSpec:
    """Нацеливание по интересам.

    Два разных смысла поля `interest_ids`, поэтому класс требует явного
    `interest_type`:

    - для `audiencetargets` — это `InterestId` из справочника `Interests`
      (категории мобильных приложений), применимо **только** к
      `MOBILE_APP_AD_GROUP`;
    - для ретаргетинг-листа типа `AUDIENCE` — это сегменты
      `AudienceInterests`, и их ID собирается из префикса типа интереса.

    :param interest_ids: ID интересов (либо названия для `resolve`).
    :param importance: тип интереса — `SHORT_TERM`, `LONG_TERM` или `ANY`.
    :param use_segment_ids: True — `interest_ids` это уже готовые ID
        сегментов `AudienceInterests`; False — это `InterestId` из `Interests`.
    """

    interest_ids: List[int] = field(default_factory=list)
    importance: str = INTEREST_TYPE_SHORT_TERM
    use_segment_ids: bool = False

    def __post_init__(self) -> None:
        """Проверить список ID и тип интереса.

        :raises ValidationError: пустой список или неизвестный тип интереса.
        """
        self.interest_ids = [int(x) for x in self.interest_ids]
        Validator(True).one_of(
            self.importance, INTEREST_TYPES, field="InterestSpec.importance"
        )
        if not self.interest_ids:
            raise ValidationError("InterestSpec.interest_ids не может быть пустым")
        Validator(True).ids(self.interest_ids, field="InterestSpec.interest_ids")

    @classmethod
    def resolve(cls, name: str, interests: Sequence[Any]) -> "InterestSpec":
        """Найти интерес по названию через справочник `Interests`.

        :param name: название интереса (например, «Авиабилеты»).
        :param interests: записи `Interest` из справочника.
        :return: спека с найденным `InterestId`.
        :raises ValidationError: интерес не найден или название неоднозначно.
        """
        matches = [
            int(item.id)
            for item in interests
            if str(item.name).strip().casefold() == name.strip().casefold()
        ]
        if not matches:
            raise ValidationError(
                f"Интерес {name!r} не найден в справочнике Interests; "
                "проверьте название или передайте InterestId вручную"
            )
        if len(set(matches)) > 1:
            raise ValidationError(
                f"Интерес {name!r} неоднозначен: подходит несколько ID "
                f"({', '.join(str(x) for x in sorted(set(matches)))}); "
                "укажите InterestId вручную"
            )
        return cls(interest_ids=[matches[0]])

    def segment_ids(self) -> List[int]:
        """Собрать ID сегментов `AudienceInterests` с префиксом типа.

        :return: список `ExternalId` для правила ретаргетинг-листа.
        :raises ValidationError: `use_segment_ids=True` и `importance` задан —
            тогда префикс применяться не должен.
        """
        if self.use_segment_ids:
            if self.importance != INTEREST_TYPE_SHORT_TERM:
                raise ValidationError(
                    "InterestSpec с use_segment_ids=True уже содержит готовые "
                    "ID сегментов; importance применять нельзя"
                )
            return list(self.interest_ids)
        return [
            segment_external_id(interest_id, self.importance)
            for interest_id in self.interest_ids
        ]


# ----------------------------------------------------------------- retargeting


@dataclass
class RetargetingSpec:
    """Сегмент ретаргетинга: ссылка на готовый список или на цель Метрики.

    :param list_id: `RetargetingListId` существующего сегмента.
    :param goal_id: `GoalId` цели Метрики — используется, когда сегмент создаётся
        из цели, а не берётся из `getRetargetingLists`.
    :param membership_life_span: срок жизни в днях (1..540) для цели Метрики.
    """

    list_id: Optional[int] = None
    goal_id: Optional[int] = None
    membership_life_span: Optional[int] = None

    def __post_init__(self) -> None:
        """Проверить, что задан ровно один источник сегмента.

        :raises ValidationError: не задан или задан оба идентификатора.
        """
        if self.list_id is None and self.goal_id is None:
            raise ValidationError(
                "RetargetingSpec: укажите list_id (готовый сегмент) или "
                "goal_id (цель Метрики)"
            )
        if self.list_id is not None and self.goal_id is not None:
            raise ValidationError(
                "RetargetingSpec: укажите либо list_id, либо goal_id, не оба"
            )
        if self.list_id is not None:
            Validator(True).ids([self.list_id], field="RetargetingSpec.list_id")
        if self.goal_id is not None:
            Validator(True).ids([self.goal_id], field="RetargetingSpec.goal_id")
        if self.membership_life_span is not None and not (
            MEMBERSHIP_LIFE_SPAN_MIN <= self.membership_life_span <= MEMBERSHIP_LIFE_SPAN_MAX
        ):
            raise ValidationError(
                f"RetargetingSpec.membership_life_span должен быть в диапазоне "
                f"{MEMBERSHIP_LIFE_SPAN_MIN}..{MEMBERSHIP_LIFE_SPAN_MAX}"
            )

    def to_target(self, ad_group_id: int) -> "RetargetingTarget":
        """Превратить спеку в условие нацеливания для группы.

        :param ad_group_id: ID группы объявлений.
        :return: готовый билдер `RetargetingTarget`.
        :raises ValidationError: задан `goal_id` — сначала нужно создать сегмент.
        """
        if self.list_id is None:
            raise ValidationError(
                "RetargetingSpec с goal_id ещё не является сегментом: создайте "
                "ретаргетинг-лист через retargeting_lists.create() и передайте "
                "его list_id"
            )
        return RetargetingTarget(
            ad_group_id=ad_group_id,
            retargeting_list_id=int(self.list_id),
        )

    def to_rule_argument(self) -> Dict[str, Any]:
        """Собрать аргумент правила ретаргетинг-листа из цели Метрики.

        :return: `{"ExternalId": GoalId, "MembershipLifeSpan": ...}`.
        :raises ValidationError: задан `list_id`, а не `goal_id`.
        """
        if self.goal_id is None:
            raise ValidationError(
                "Аргумент правила строится только из goal_id; для list_id "
                "используйте готовый сегмент из retargetinglists"
            )
        argument: Dict[str, Any] = {"ExternalId": int(self.goal_id)}
        if self.membership_life_span is not None:
            argument["MembershipLifeSpan"] = int(self.membership_life_span)
        return argument


# ------------------------------------------------------------- payload builders


def _bid_fields(
    context_bid: Optional[int], strategy_priority: Optional[str]
) -> Dict[str, Any]:
    """Собрать общие поля ставки/приоритета для `audiencetargets`.

    :param context_bid: ставка в сетях (единицы ×1 000 000) для ручных стратегий.
    :param strategy_priority: приоритет для автоматических стратегий.
    :return: словарь с непустыми полями.
    :raises ValidationError: неизвестный приоритет или отрицательная ставка.
    """
    body: Dict[str, Any] = {}
    if context_bid is not None:
        if isinstance(context_bid, bool) or not isinstance(context_bid, int):
            raise ValidationError(
                f"context_bid должен быть целым числом единиц ×1 000 000, "
                f"получено {context_bid!r}"
            )
        if context_bid < 0:
            raise ValidationError(f"context_bid не может быть отрицательным: {context_bid}")
        body["ContextBid"] = int(context_bid)
    if strategy_priority is not None:
        Validator(True).one_of(
            strategy_priority, PRIORITIES, field="StrategyPriority"
        )
        body["StrategyPriority"] = strategy_priority
    return body


@dataclass
class _TargetBase:
    """Общая часть условия нацеливания: группа, ставка, приоритет.

    :param ad_group_id: ID группы объявлений (обязателен для add).
    :param context_bid: ставка в сетях для ручной стратегии.
    :param strategy_priority: приоритет для автоматической стратегии.
    :param ad_group_type: тип группы; нужен для матрицы допустимости.
    """

    ad_group_id: int
    context_bid: Optional[int] = None
    strategy_priority: Optional[str] = None
    ad_group_type: Optional[str] = None

    def _check_group(self, kind: str) -> None:
        """Проверить допустимость нацеливания для типа группы, если он известен.

        :param kind: вид нацеливания (см. `constants.TARGET_KINDS`).
        :raises ValidationError: комбинация запрещена документацией.
        """
        if self.ad_group_type is None:
            return
        if not is_allowed(self.ad_group_type, kind):
            raise ValidationError(
                f"Недопустимое нацеливание для группы {self.ad_group_type}: "
                f"{explain(self.ad_group_type, kind)}"
            )

    def _body(self) -> Dict[str, Any]:
        """Собрать тело элемента `audiencetargets`.

        :return: словарь с `AdGroupId` и полями ставки/приоритета.
        :raises ValidationError: некорректный ID группы.
        """
        Validator(True).ids([self.ad_group_id], field="AdGroupId")
        body: Dict[str, Any] = {"AdGroupId": int(self.ad_group_id)}
        body.update(_bid_fields(self.context_bid, self.strategy_priority))
        return body

    def to_payload(self) -> Dict[str, Any]:
        """Тело элемента `audiencetargets/add`.

        :return: словарь для `params.AudienceTargets`.
        """
        return self._body()


@dataclass
class RetargetingTarget(_TargetBase):
    """Условие нацеливания по готовому ретаргетинг-сегменту.

    :param retargeting_list_id: `RetargetingListId` сегмента.
    """

    retargeting_list_id: int = 0

    def to_payload(self) -> Dict[str, Any]:
        """Тело `AudienceTargetAddItem` с `RetargetingListId`.

        :return: словарь для `params.AudienceTargets`.
        :raises ValidationError: не задан сегмент или группа несовместима.
        """
        self._check_group(TARGET_KIND_RETARGETING)
        Validator(True).ids(
            [self.retargeting_list_id], field="RetargetingListId"
        )
        body = self._body()
        body["RetargetingListId"] = int(self.retargeting_list_id)
        return body


@dataclass
class InterestTarget(_TargetBase):
    """Условие нацеливания по категории мобильного приложения.

    Применимо только к группе `MOBILE_APP_AD_GROUP` и только к интересам
    с `IsTargetable: YES` в справочнике `Interests`.
    """

    interest_id: int = 0

    def to_payload(self) -> Dict[str, Any]:
        """Тело `AudienceTargetAddItem` с `InterestId`.

        :return: словарь для `params.AudienceTargets`.
        :raises ValidationError: не задан интерес или группа несовместима.
        """
        self._check_group(TARGET_KIND_INTEREST)
        Validator(True).ids([self.interest_id], field="InterestId")
        body = self._body()
        body["InterestId"] = int(self.interest_id)
        return body


@dataclass
class DemographicsTarget(_TargetBase):
    """Демография/поведение/интересы как ретаргетинг-лист типа `AUDIENCE`.

    В `audiencetargets` таких полей нет, поэтому условие создаётся в два
    шага: сначала `to_retargeting_list()` создаёт сегмент, затем
    `to_audience_target(list_id)` — условие нацеливания на этот сегмент.

    :param spec: демографическая спека.
    :param name: имя сегмента обязательно (1..250 символов); SDK не
        придумывает имя за бизнес.
    :param segment_ids: уже разрешённые ID сегментов (если резолв не нужен).
    :param rules: дополнительные правила отбора (сегменты, цели).
    """

    spec: Optional[DemographicsSpec] = None
    name: Optional[str] = None
    segment_ids: List[int] = field(default_factory=list)
    rules: List[Dict[str, Any]] = field(default_factory=list)

    def resolved_segment_ids(self) -> List[int]:
        """Получить ID сегментов: из поля либо через резолв спеки.

        :return: список ID сегментов.
        :raises ValidationError: не заданы ни `segment_ids`, ни `spec`.
        """
        if self.segment_ids:
            return [int(x) for x in self.segment_ids]
        if self.spec is None:
            raise ValidationError(
                "DemographicsTarget: укажите spec или готовые segment_ids"
            )
        raise ValidationError(
            "DemographicsTarget: segment_ids не заданы. Разрешите спеку через "
            "TargetingService.resolve_demographics(spec) — самостоятельно "
            "обратиться к справочнику модель не может"
        )

    def to_retargeting_list(self) -> Dict[str, Any]:
        """Тело `retargetinglists/add` для сегмента типа `AUDIENCE`.

        :return: словарь с `Name`, `Type` и `Rules`.
        :raises ValidationError: не задано ни одного сегмента или превышены
            лимиты документации, либо не задано `name`.
        """
        self._check_group(TARGET_KIND_DEMOGRAPHICS)
        segment_ids = self.resolved_segment_ids()
        if self.name is None:
            raise ValidationError(
                "DemographicsTarget: обязательно укажите name сегмента "
                "(SDK не придумывает имя за бизнес)"
            )
        Validator(True).name(self.name, field="Name", max_length=250)
        arguments = [{"ExternalId": segment_id} for segment_id in segment_ids]
        all_rules: List[Dict[str, Any]] = [
            {"Arguments": arguments, "Operator": RETARGETING_RULE_ANY},
            *self.rules,
        ]
        _validate_rules(all_rules)
        return {
            "Name": self.name,
            "Type": RETARGETING_LIST_TYPE_AUDIENCE,
            "Rules": all_rules,
        }

    def to_audience_target(self, list_id: int) -> RetargetingTarget:
        """Условие нацеливания на созданный сегмент.

        :param list_id: `RetargetingListId` созданного ретаргетинг-листа.
        :return: билдер `RetargetingTarget` с теми же ставкой и приоритетом.
        """
        return RetargetingTarget(
            ad_group_id=self.ad_group_id,
            retargeting_list_id=int(list_id),
            context_bid=self.context_bid,
            strategy_priority=self.strategy_priority,
            ad_group_type=self.ad_group_type,
        )


@dataclass
class ContextTarget(_TargetBase):
    """Нацеливание по контексту страницы — **не поддерживается API v5**.

    В `audiencetargets` нет поля для контекстного нацеливания: доступны только
    `RetargetingListId` и `InterestId`. Вместо молчаливого игнорирования
    условия билдер сообщает об этом явной ошибкой — так дефект настройки
    обнаруживается на клиенте, а не после модерации объявления.
    """

    url: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        """Всегда бросает `ValidationError`.

        :raises ValidationError: контекстное нацеливание недоступно в API v5.
        """
        raise ValidationError(
            "Нацеливание по контексту (странице сайта) в Yandex Direct API v5 "
            "отсутствует: audiencetargets поддерживает только RetargetingListId "
            "и InterestId. Используйте ретаргетинг по сегментам "
            "(RetargetingTarget) либо интерес мобильного приложения "
            "(InterestTarget)"
        )


def _validate_rules(rules: Sequence[Mapping[str, Any]]) -> None:
    """Проверить правила ретаргетинг-листа по ограничениям документации.

    :param rules: правила отбора.
    :raises ValidationError: превышены лимиты или неверный оператор/аргументы.
    """
    if not rules:
        raise ValidationError("Rules ретаргетинг-листа не может быть пустым")
    if len(rules) > RETARGETING_RULES_MAX:
        raise ValidationError(
            f"Не более {RETARGETING_RULES_MAX} правил в ретаргетинг-листе, "
            f"получено {len(rules)}"
        )
    for index, rule in enumerate(rules):
        operator = rule.get("Operator")
        Validator(True).one_of(
            operator,
            RETARGETING_RULE_OPERATORS,
            field=f"Rules[{index}].Operator",
        )
        arguments = rule.get("Arguments") or []
        if not arguments:
            raise ValidationError(f"Rules[{index}].Arguments не может быть пустым")
        if len(arguments) > RETARGETING_ARGUMENTS_MAX:
            raise ValidationError(
                f"Не более {RETARGETING_ARGUMENTS_MAX} аргументов в правиле, "
                f"получено {len(arguments)}"
            )
        for arg in arguments:
            external_id = arg.get("ExternalId")
            if external_id is None:
                raise ValidationError(
                    f"Rules[{index}].Arguments[].ExternalId обязателен"
                )
            Validator(True).ids(
                [to_int(external_id)], field=f"Rules[{index}].Arguments[].ExternalId"
            )
            life_span = arg.get("MembershipLifeSpan")
            if life_span is not None and not (
                MEMBERSHIP_LIFE_SPAN_MIN
                <= int(life_span)
                <= MEMBERSHIP_LIFE_SPAN_MAX
            ):
                raise ValidationError(
                    f"MembershipLifeSpan должен быть в диапазоне "
                    f"{MEMBERSHIP_LIFE_SPAN_MIN}..{MEMBERSHIP_LIFE_SPAN_MAX}"
                )


# ------------------------------------------------- модель ретаргетинг-листа


@dataclass
class RetargetingList:
    """Ретаргетинг-лист (сегмент) с правилами отбора пользователей.

    Тип задаётся при создании и **не меняется**: `RETARGETING` — цели и сегменты
    Метрики/Аудитории, `AUDIENCE` — любые сегменты, включая демографию,
    поведение и пользовательские интересы (только для медийных кампаний).

    :param name: имя сегмента (1..250 символов).
    :param rules: правила отбора; каждый — `{"Arguments": [...], "Operator": ...}`.
    :param type: `RETARGETING` или `AUDIENCE`.
    :param id: ID существующего сегмента (для `update`/`delete`).
    :param description: текстовая заметка (до 4096 символов).
    """

    name: str
    rules: List[Dict[str, Any]] = field(default_factory=list)
    type: str = RETARGETING_LIST_TYPE_RETARGETING
    id: Optional[int] = None
    description: Optional[str] = None
    is_available: Optional[bool] = None
    scope: Optional[str] = None
    available_for_ad_group_types: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Проверить имя, тип и правила отбора.

        :raises ValidationError: неизвестный тип, пустые правила или нарушение
            лимитов документации.
        """
        Validator(True).name(self.name, field="Name", max_length=250)
        Validator(True).one_of(
            self.type,
            (RETARGETING_LIST_TYPE_RETARGETING, RETARGETING_LIST_TYPE_AUDIENCE),
            field="RetargetingList.Type",
        )
        if self.description is not None and len(self.description) > 4096:
            raise ValidationError("RetargetingList.Description длиннее 4096 символов")
        _validate_rules(self.rules)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "RetargetingList":
        """Разобрать сегмент из ответа `retargetinglists/get`.

        :param d: JSON-запись сегмента.
        :return: типизированная модель.
        """
        raw_rules = d.get("Rules") or []
        return cls(
            id=to_int(d.get("Id")) or None,
            name=to_str(d.get("Name")),
            description=d.get("Description"),
            type=to_str(d.get("Type")) or RETARGETING_LIST_TYPE_RETARGETING,
            rules=[dict(rule) for rule in raw_rules if isinstance(rule, Mapping)],
            is_available=d.get("IsAvailable"),
            scope=d.get("Scope"),
            available_for_ad_group_types=[
                str(x) for x in (d.get("AvailableForTargetsInAdGroupTypes") or [])
            ],
        )

    def to_add_payload(self) -> Dict[str, Any]:
        """Тело `retargetinglists/add`.

        :return: словарь с `Name`, `Type` и `Rules`.
        """
        body: Dict[str, Any] = {
            "Name": self.name,
            "Type": self.type,
            "Rules": [dict(rule) for rule in self.rules],
        }
        if self.description is not None:
            body["Description"] = self.description
        return body

    def to_update_payload(self) -> Dict[str, Any]:
        """Тело `retargetinglists/update`: `Id` плюс изменяемые поля.

        :return: словарь для `params.RetargetingLists`.
        :raises ValidationError: не задан `id`.
        """
        if self.id is None:
            raise ValidationError(
                "RetargetingList.to_update_payload требует заполненного id"
            )
        body = self.to_add_payload()
        body["Id"] = int(self.id)
        return body


# ------------------------------------------------- совместимость ключевых фраз


def check_keywords_allowed(ad_group_type: str) -> None:
    """Проверить, что ключевые фразы применимы к типу группы.

    Ключевые фразы (`ad_group_items`) неприменимы к медийным группам: показы
    в РСЯ задаются сегментами, а не фразами. Ошибку удобно получить до сети.

    :param ad_group_type: тип группы из `adgroups/get`.
    :raises ValidationError: ключевые фразы неприменимы к этой группе.
    """
    message = keyword_conflict(ad_group_type)
    if message is not None:
        raise ValidationError(message)


__all__ = [
    "AD_GROUP_TYPE_MOBILE_APP",
    "AUDIENCE_LIST_ALLOWED_AD_GROUP_TYPES",
    "CRITERIA_TYPE_AGE",
    "CRITERIA_TYPE_GENDER",
    "GENDER_ALL",
    "GENDER_FEMALE",
    "GENDER_MALE",
    "GENDERS",
    "INTEREST_ALLOWED_AD_GROUP_TYPES",
    "INTEREST_TYPE_ANY",
    "INTEREST_TYPE_LONG_TERM",
    "INTEREST_TYPE_SHORT_TERM",
    "INTEREST_TYPES",
    "MEMBERSHIP_LIFE_SPAN_MAX",
    "MEMBERSHIP_LIFE_SPAN_MIN",
    "PRIORITIES",
    "PRIORITY_HIGH",
    "PRIORITY_LOW",
    "PRIORITY_NORMAL",
    "RETARGETING_ALLOWED_AD_GROUP_TYPES",
    "RETARGETING_ARGUMENTS_MAX",
    "RETARGETING_RULES_MAX",
    "ContextTarget",
    "DemographicsSpec",
    "DemographicsTarget",
    "InterestSpec",
    "InterestTarget",
    "RetargetingList",
    "RetargetingSpec",
    "RetargetingTarget",
    "check_keywords_allowed",
]
