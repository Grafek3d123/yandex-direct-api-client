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

from typing import (
    Any,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Union,
    overload,
)

from .._transport import Transport
from ..limits import AUDIENCE_TARGETS_GET_MAX, GET_PAGE_MAX
from ..models.batch import BatchResult
from ..models.retargeting_condition import RetargetingCondition
from ..validation import Validator
from ._base import (
    OnItemError,
    chunked,
    empty_result,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
    run_batches,
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

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        retargeting_list_ids: Optional[Sequence[int]] = None,
        page_limit: int = GET_PAGE_MAX,
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
        self._validator().ids(ids, field="Ids")
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[RetargetingCondition] = []
        for chunk in chunked(list(ids), AUDIENCE_TARGETS_GET_MAX):
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

    @overload
    def create(
        self,
        conditions: Sequence[RetargetingConditionInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def create(
        self,
        conditions: Sequence[RetargetingConditionInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def create(
        self,
        conditions: Sequence[RetargetingConditionInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Создать условия ретаргетинга (audiencetargets/add, до 200 за запрос).

        :param conditions: типизированные модели или тела AudienceTargetAddItem.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов AddResults (или `BatchResult`).
        """
        self._ensure_writable("create")
        body_list = [_new_body(x) for x in conditions]
        return run_batches(
            self._transport,
            "audiencetargets",
            method="add",
            params_key="AudienceTargets",
            items=body_list,
            on_item_error=on_item_error,
            action="создания условия ретаргетинга",
            result_key="AddResults",
        )

    @overload
    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Удалить условия ретаргетинга по ID (audiencetargets/delete).

        :param ids: список ID условий.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete")
        ensure_confirmed("retargeting_conditions.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return empty_result(on_item_error)
        self._validator().ids(id_list, field="SelectionCriteria.Ids")
        return run_batches(
            self._transport,
            "audiencetargets",
            method="delete",
            params_key="SelectionCriteria",
            items=id_list,
            on_item_error=on_item_error,
            action="удаления условия ретаргетинга",
            result_key="DeleteResults",
            wrap_id=True,
        )


def _new_body(item: RetargetingConditionInput) -> Dict[str, Any]:
    if isinstance(item, RetargetingCondition):
        return item.to_new_payload()
    return dict(item)


__all__ = ["RetargetingConditionService", "RetargetingConditionInput"]
