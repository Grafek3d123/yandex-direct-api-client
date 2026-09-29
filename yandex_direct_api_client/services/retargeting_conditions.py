"""Сервис условий ретаргетинга (RetargetingConditions).

ВАЖНО про имя эндпоинта. Отдельный сервис ``retargetingconditions`` НЕ
подтверждается актуальным официальным справочником Yandex Direct API v5
(страницы ``.../retargetingconditions/...`` отдают 404). После обновления до
единой перфоманс-кампании условия ретаргетинга управляются сервисом
``audiencetargets``: условие нацеливания привязывается к ретаргетинг-списку
полем ``RetargetingListId``.

Справочник (подтверждён):
https://yandex.ru/dev/direct/doc/ru/audiencetargets/audiencetargets.html
https://yandex.ru/dev/direct/doc/en/objects/audience-target

Этот сервис — удобная обёртка над ``audiencetargets`` для условий,
привязанных к ретаргетинг-списку, с фильтрами по ``RetargetingListIds``.
Не путать с ``retargeting_adjustments`` — это корректировки ставок.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .._transport import Transport
from ..models.retargeting_condition import RetargetingCondition
from ._base import (
    MAX_GET_IDS,
    MAX_MUTATE_IDS,
    check_item_errors,
    chunked,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
)

_DEFAULT_FIELDS = [
    "Id",
    "AdGroupId",
    "CampaignId",
    "RetargetingListId",
    "ContextBid",
    "StrategyPriority",
    "State",
]

RetargetingConditionInput = Union[RetargetingCondition, Mapping[str, Any]]


class RetargetingConditionService:
    """Операции над условиями ретаргетинга (через API audiencetargets)."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("retargeting_conditions", method_name, self._readonly)

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        retargeting_list_ids: Optional[Sequence[int]] = None,
        page_limit: int = 10000,
    ) -> List[RetargetingCondition]:
        """Список условий ретаргетинга с авто-пагинацией.

        :param campaign_ids: фильтр по ID кампаний.
        :param ad_group_ids: фильтр по ID групп объявлений.
        :param retargeting_list_ids: фильтр по ID ретаргетинг-списков.
        :param page_limit: размер страницы.
        """
        criteria: Dict[str, Any] = {}
        if campaign_ids:
            criteria["CampaignIds"] = list(campaign_ids)
        if ad_group_ids:
            criteria["AdGroupIds"] = list(ad_group_ids)
        if retargeting_list_ids:
            criteria["RetargetingListIds"] = list(retargeting_list_ids)

        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": _DEFAULT_FIELDS,
            },
        }
        raw_list = fetch_all_pages(
            self._transport, "audiencetargets", payload, page_limit=page_limit
        )
        return [RetargetingCondition.from_dict(x) for x in raw_list]

    def get(
        self,
        ids: Sequence[int],
        *,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[RetargetingCondition]:
        """Получить условия ретаргетинга по ID (авто-чанкинг по 1000).

        :param ids: список ID условий.
        :param field_names: кастомные поля.
        """
        if not ids:
            return []
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[RetargetingCondition] = []
        for chunk in chunked(list(ids), MAX_GET_IDS):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": fields,
                },
            }
            result = self._transport.post_result("audiencetargets", payload)
            for raw in result.get("AudienceTargets") or []:
                results.append(RetargetingCondition.from_dict(raw))
        return results

    def create(
        self, conditions: Sequence[RetargetingConditionInput]
    ) -> List[Dict[str, Any]]:
        """Создать условия ретаргетинга (audiencetargets/add, до 200 за запрос).

        :param conditions: типизированные модели или тела AudienceTargetAddItem.
        :return: список элементов AddResults.
        """
        self._ensure_writable("create")
        body_list = [_new_body(x) for x in conditions]
        if not body_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(body_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "add",
                "params": {"AudienceTargets": list(chunk)},
            }
            result = self._transport.post_result("audiencetargets", payload)
            for item in result.get("AddResults") or []:
                check_item_errors(
                    item, f"создания условия ретаргетинга id={item.get('Id')}"
                )
                results.append(item)
        return results

    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
    ) -> List[Dict[str, Any]]:
        """Удалить условия ретаргетинга по ID (audiencetargets/delete).

        :param ids: список ID условий.
        :param confirm: явное подтверждение необратимой операции удаления.
        :return: список элементов DeleteResults.
        """
        self._ensure_writable("delete")
        ensure_confirmed("retargeting_conditions.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(id_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "delete",
                "params": {"SelectionCriteria": {"Ids": list(chunk)}},
            }
            result = self._transport.post_result("audiencetargets", payload)
            for item in result.get("DeleteResults") or []:
                check_item_errors(
                    item, f"удаления условия ретаргетинга id={item.get('Id')}"
                )
                results.append(item)
        return results


def _new_body(item: RetargetingConditionInput) -> Dict[str, Any]:
    if isinstance(item, RetargetingCondition):
        return item.to_new_payload()
    return dict(item)


__all__ = ["RetargetingConditionService", "RetargetingConditionInput"]
