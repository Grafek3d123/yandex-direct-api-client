"""Слой таргетинга: разрешение имён в ID и сборка условий нацеливания.

Модуль связывает три вещи, которые по отдельности живут в разных сервисах:

1. справочники (`dictionaries`) — откуда берутся ID сегментов демографии,
   поведения и интересов;
2. `retargetinglists` — куда кладутся сегменты `AUDIENCE`;
3. `audiencetargets` — куда добавляется условие нацеливания на сегмент.

Прямая причина такого разделения — документация (снимок 30.09.2026):
в `audiencetargets` есть только `RetargetingListId` и `InterestId`, а демография
и пользовательские интересы существуют лишь как правила ретаргетинг-листа.

Типичный сценарий:

    target = client.targeting.resolve_demographics(
        DemographicsSpec(age_ranges=["25-34"], gender=GENDER_FEMALE),
        name="Женщины 25-34",
    )
    result = client.targeting.create_audience_target(
        ad_group_id=123, target=target, context_bid=500_000
    )
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .._transport import Transport
from ..exceptions import ApiError, ValidationError
from ..models.targeting import (
    DemographicsSpec,
    DemographicsTarget,
    InterestSpec,
    InterestTarget,
    RetargetingList,
    RetargetingSpec,
    RetargetingTarget,
)
from .dictionaries import DictionariesService
from .retargeting_lists import RetargetingListService

#: Названия характеристик демографии в `AudienceCriteriaTypes`.
CRITERIA_TYPE_AGE = "AGE"
CRITERIA_TYPE_GENDER = "GENDER"


@dataclass
class AudienceTargetCreated:
    """Результат создания демографического сегмента и условия нацеливания.

    :param retargeting_list_id: ID созданного сегмента.
    :param audience_target_id: ID созданного условия нацеливания.
    :param segment: созданный сегмент (для последующего `update`/`delete`).
    """

    retargeting_list_id: int
    audience_target_id: int
    segment: RetargetingList


class TargetingService:
    """Разрешение имён в ID и сборка условий нацеливания."""

    def __init__(
        self,
        transport: Transport,
        *,
        dictionaries: DictionariesService,
        retargeting_lists: RetargetingListService,
        readonly: bool = False,
    ) -> None:
        self._transport = transport
        self._dictionaries = dictionaries
        self._retargeting_lists = retargeting_lists
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        if self._readonly:
            raise ValidationError(
                f"Метод targeting.{method_name} запрещён в readonly-режиме"
            )

    # ---------------- разрешение имён ----------------
    def resolve_demographics(
        self,
        spec: DemographicsSpec,
        *,
        name: Optional[str] = None,
    ) -> DemographicsTarget:
        """Превратить демографическую спеку в готовый билдер условия.

        Названия возрастных сегментов и пола ищутся в справочнике
        `AudienceDemographicProfiles` (справочник кэшируется на диске).

        :param spec: демографическая спека.
        :param name: имя будущего сегмента; по умолчанию собирается из входа.
        :return: `DemographicsTarget` с уже разрешёнными ID сегментов.
        :raises ValidationError: сегмент не найден или название неоднозначно.
        """
        segments = self._dictionaries.audience_demographic_profiles()
        segment_ids = spec.resolve(segments)
        return DemographicsTarget(
            ad_group_id=0,
            segment_ids=segment_ids,
            name=name or _default_segment_name(spec),
        )

    def resolve_interest(
        self,
        name: str,
        *,
        importance: str = "SHORT_TERM",
    ) -> InterestSpec:
        """Найти интерес по названию через справочник `Interests`.

        :param name: название интереса, например «Авиабилеты».
        :param importance: тип интереса для последующей сборки `ExternalId`.
        :return: спека с найденным `InterestId`.
        :raises ValidationError: интерес не найден или название неоднозначно.
        """
        resolved = InterestSpec.resolve(name, self._dictionaries.interests())
        return InterestSpec(
            interest_ids=resolved.interest_ids,
            importance=importance,
        )

    def demographic_segment_names(
        self, criteria_type: str = CRITERIA_TYPE_AGE
    ) -> List[str]:
        """Названия доступных сегментов одной характеристики.

        Нужно, чтобы показать пользователю варианты до составления спеки:
        поиск по всему справочнику приводит к совпадениям вроде «Мужчины».

        :param criteria_type: `AGE` (по умолчанию) или `GENDER`.
        :return: отсортированные названия сегментов.
        :raises ValidationError: неизвестный тип характеристики.
        """
        segments = self._dictionaries.audience_profiles_of_type(criteria_type)
        return sorted(segment.name for segment in segments)

    # ---------------- сборка условий ----------------
    def retargeting_target(
        self,
        ad_group_id: int,
        spec: RetargetingSpec,
        *,
        context_bid: Optional[int] = None,
        strategy_priority: Optional[str] = None,
        ad_group_type: Optional[str] = None,
    ) -> RetargetingTarget:
        """Собрать условие нацеливания по готовому сегменту.

        :param ad_group_id: ID группы объявлений.
        :param spec: спека ретаргетинга с `list_id`.
        :param context_bid: ставка в сетях для ручной стратегии.
        :param strategy_priority: приоритет для автоматической стратегии.
        :param ad_group_type: тип группы для проверки допустимости.
        :return: готовый билдер условия.
        """
        target = spec.to_target(ad_group_id)
        target.context_bid = context_bid
        target.strategy_priority = strategy_priority
        target.ad_group_type = ad_group_type
        return target

    def interest_target(
        self,
        ad_group_id: int,
        interest: InterestSpec,
        *,
        context_bid: Optional[int] = None,
        strategy_priority: Optional[str] = None,
        ad_group_type: Optional[str] = None,
    ) -> InterestTarget:
        """Собрать условие нацеливания по категории мобильного приложения.

        :param ad_group_id: ID группы объявлений.
        :param interest: спека с одним `InterestId` (`resolve_interest`).
        :param context_bid: ставка в сетях для ручной стратегии.
        :param strategy_priority: приоритет для автоматической стратегии.
        :param ad_group_type: тип группы; по умолчанию `MOBILE_APP_AD_GROUP`.
        :return: готовый билдер условия.
        :raises ValidationError: в спеке больше одного интереса.
        """
        if len(interest.interest_ids) != 1:
            raise ValidationError(
                "InterestTarget принимает ровно один InterestId: условие "
                "нацеливания по интересу — это один элемент audiencetargets"
            )
        return InterestTarget(
            ad_group_id=ad_group_id,
            interest_id=interest.interest_ids[0],
            context_bid=context_bid,
            strategy_priority=strategy_priority,
            ad_group_type=ad_group_type or "MOBILE_APP_AD_GROUP",
        )

    def create_audience_target(
        self,
        ad_group_id: int,
        target: DemographicsTarget,
        *,
        context_bid: Optional[int] = None,
        strategy_priority: Optional[str] = None,
    ) -> AudienceTargetCreated:
        """Создать сегмент типа `AUDIENCE` и условие нацеливания на него.

        Два вызова API: `retargetinglists/add`, затем `audiencetargets/add`.
        Если второй вызов падает, сегмент остаётся созданным — исключение
        пробрасывается как есть, поэтому перед повтором сегмент стоит найти
        через `retargeting_lists.get()` по имени.

        :param ad_group_id: ID группы объявлений.
        :param target: билдер с разрешёнными ID сегментов
            (см. `resolve_demographics`).
        :param context_bid: ставка в сетях для ручной стратегии.
        :param strategy_priority: приоритет для автоматической стратегии.
        :return: ID созданного сегмента, ID условия и сама модель сегмента.
        :raises ValidationError: readonly-режим или нарушения правил отбора.
        :raises ApiError: ошибка API на любом из двух шагов.
        """
        self._ensure_writable("create_audience_target")
        target.ad_group_id = int(ad_group_id)
        if context_bid is not None:
            target.context_bid = int(context_bid)
        if strategy_priority is not None:
            target.strategy_priority = strategy_priority
        list_body = target.to_retargeting_list()
        segment = RetargetingList(
            name=list_body["Name"],
            description=list_body.get("Description"),
            type=list_body["Type"],
            rules=list_body["Rules"],
        )
        added = self._retargeting_lists.create([segment], on_item_error="raise")
        list_id = int(added[0]["Id"])
        segment.id = list_id
        audience_target = target.to_audience_target(list_id).to_payload()
        result = self._transport.post_result(
            "audiencetargets",
            {
                "method": "add",
                "params": {"AudienceTargets": [audience_target]},
            },
        )
        item = (result.get("AddResults") or [{}])[0]
        errors = item.get("Errors") or []
        if errors:
            raise ApiError(
                f"Ошибка создания условия нацеливания: {errors[0].get('Message')}",
                details=tuple(errors),
                object_id=list_id,
                status_code=200,
                response_body=item,
            )
        return AudienceTargetCreated(
            retargeting_list_id=list_id,
            audience_target_id=int(item.get("Id") or 0),
            segment=segment,
        )


def _default_segment_name(spec: DemographicsSpec) -> str:
    """Собрать имя сегмента по умолчанию из демографической спеки.

    Имя всё равно можно задать вручную — оно лишь помогает ориентироваться
    в списке сегментов аккаунта.

    :param spec: демографическая спека.
    :return: читаемое имя сегмента.
    """
    parts: List[str] = list(spec.age_ranges)
    if spec.gender != "ALL":
        label = (
            spec.gender_names[spec.gender]
            if spec.gender_names and spec.gender in spec.gender_names
            else spec.gender
        )
        parts.append(label)
    return ", ".join(parts) if parts else "SDK audience"


__all__ = [
    "CRITERIA_TYPE_AGE",
    "CRITERIA_TYPE_GENDER",
    "AudienceTargetCreated",
    "TargetingService",
]
