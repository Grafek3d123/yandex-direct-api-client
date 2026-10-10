"""Сервис условий нацеливания на аудиторию (AudienceTargets).

Официальный справочник:
https://yandex.ru/dev/direct/doc/ru/audiencetargets/audiencetargets.html
Методы API: add, delete, suspend, resume, get, setBids.

Примечание: у audiencetargets НЕТ метода update — изменение ставки/приоритета
выполняется методом setBids, а смена состава условия — create + delete.
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
from ..models.audience_target import AudienceTarget
from ..models.batch import BatchResult
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
    "InterestId",
    "ContextBid",
    "StrategyPriority",
    "State",
]

AudienceTargetInput = Union[AudienceTarget, Mapping[str, Any]]


class AudienceTargetService:
    """Операции над условиями нацеливания на аудиторию Yandex.Direct."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("audience_targets", method_name, self._readonly)

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        states: Optional[Sequence[str]] = None,
        page_limit: int = GET_PAGE_MAX,
    ) -> List[AudienceTarget]:
        """Список условий нацеливания с авто-пагинацией.

        :param campaign_ids: фильтр по ID кампаний.
        :param ad_group_ids: фильтр по ID групп объявлений.
        :param states: фильтр по State (ON, SUSPENDED).
        :param page_limit: размер страницы.
        """
        criteria: Dict[str, Any] = {}
        if campaign_ids:
            criteria["CampaignIds"] = list(campaign_ids)
        if ad_group_ids:
            criteria["AdGroupIds"] = list(ad_group_ids)
        if states:
            criteria["States"] = list(states)

        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": _DEFAULT_FIELDS,
            },
        }
        raw_list = fetch_all_pages(
            self._transport,
            "audiencetargets",
            payload,
            page_limit=page_limit,
        )
        return [AudienceTarget.from_dict(x) for x in raw_list]

    def get(
        self,
        ids: Sequence[int],
        *,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[AudienceTarget]:
        """Получить условия нацеливания по ID (авто-чанкинг по 1000).

        :param ids: список ID условий.
        :param field_names: кастомные поля.
        """
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[AudienceTarget] = []
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
                results.append(AudienceTarget.from_dict(raw))
        return results

    @overload
    def create(
        self,
        targets: Sequence[AudienceTargetInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def create(
        self,
        targets: Sequence[AudienceTargetInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def create(
        self,
        targets: Sequence[AudienceTargetInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Создать условия нацеливания (batch, до 200 за запрос).

        :param targets: типизированные модели или тела AudienceTargetAddItem.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов AddResults (или `BatchResult`).
        """
        self._ensure_writable("create")
        body_list = [_new_body(x) for x in targets]
        return run_batches(
            self._transport,
            "audiencetargets",
            method="add",
            params_key="AudienceTargets",
            items=body_list,
            on_item_error=on_item_error,
            action="создания условия нацеливания",
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
        """Удалить условия нацеливания по ID (авто-чанкинг по 200).

        :param ids: список ID условий.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete")
        ensure_confirmed("audience_targets.delete", confirm)
        return self._ids_action(
            "delete",
            "DeleteResults",
            "удаления условия нацеливания",
            ids,
            on_item_error,
        )

    @overload
    def suspend(
        self, ids: Sequence[int], *, on_item_error: Literal["raise"] = ...
    ) -> List[Dict[str, Any]]: ...

    @overload
    def suspend(
        self, ids: Sequence[int], *, on_item_error: Literal["collect"]
    ) -> BatchResult: ...

    def suspend(
        self, ids: Sequence[int], *, on_item_error: OnItemError = "raise"
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Остановить показы условий нацеливания (audiencetargets/suspend).

        :param ids: список ID условий.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов SuspendResults (или `BatchResult`).
        """
        return self._ids_action(
            "suspend",
            "SuspendResults",
            "остановки условия нацеливания",
            ids,
            on_item_error,
        )

    @overload
    def resume(
        self, ids: Sequence[int], *, on_item_error: Literal["raise"] = ...
    ) -> List[Dict[str, Any]]: ...

    @overload
    def resume(
        self, ids: Sequence[int], *, on_item_error: Literal["collect"]
    ) -> BatchResult: ...

    def resume(
        self, ids: Sequence[int], *, on_item_error: OnItemError = "raise"
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Возобновить показы условий нацеливания (audiencetargets/resume).

        :param ids: список ID условий.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов ResumeResults (или `BatchResult`).
        """
        return self._ids_action(
            "resume",
            "ResumeResults",
            "возобновления условия нацеливания",
            ids,
            on_item_error,
        )

    def _ids_action(
        self,
        method_name: str,
        result_key: str,
        action_label: str,
        ids: Sequence[int],
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Общий batch-вызов метода по SelectionCriteria.Ids.

        :param method_name: имя метода API (delete/suspend/resume).
        :param result_key: ключ списка результатов в ответе.
        :param action_label: описание действия для сообщений об ошибках.
        :param ids: список ID условий нацеливания.
        :param on_item_error: `raise` или `collect`.
        :return: список элементов результата (или `BatchResult`).
        """
        self._ensure_writable(method_name)
        id_list = list(ids)
        if not id_list:
            return empty_result(on_item_error)
        self._validator().ids(id_list, field="SelectionCriteria.Ids")
        return run_batches(
            self._transport,
            "audiencetargets",
            method=method_name,
            params_key="SelectionCriteria",
            items=id_list,
            on_item_error=on_item_error,
            action=action_label,
            result_key=result_key,
            wrap_id=True,
        )

    @overload
    def set_bids(
        self,
        bids: Sequence[AudienceTargetInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def set_bids(
        self,
        bids: Sequence[AudienceTargetInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def set_bids(
        self,
        bids: Sequence[AudienceTargetInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Назначить ставки/приоритеты (audiencetargets/setBids, до 200 за запрос).

        :param bids: типизированные модели с Id и ContextBid/StrategyPriority
            или тела AudienceTargetSetBidsItem {Id, ContextBid, StrategyPriority}.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов SetBidsResults (или `BatchResult`).
        """
        self._ensure_writable("set_bids")
        body_list = [_set_bid_body(x) for x in bids]
        return run_batches(
            self._transport,
            "audiencetargets",
            method="setBids",
            params_key="Bids",
            items=body_list,
            on_item_error=on_item_error,
            action="назначения ставки условия нацеливания",
            result_key="SetBidsResults",
        )


def _new_body(item: AudienceTargetInput) -> Dict[str, Any]:
    if isinstance(item, AudienceTarget):
        return item.to_new_payload()
    return dict(item)


def _set_bid_body(item: AudienceTargetInput) -> Dict[str, Any]:
    if isinstance(item, AudienceTarget):
        body: Dict[str, Any] = {}
        if item.id:
            body["Id"] = item.id
        if item.context_bid is not None:
            body["ContextBid"] = item.context_bid
        if item.strategy_priority is not None:
            body["StrategyPriority"] = item.strategy_priority
        return body
    return dict(item)


__all__ = ["AudienceTargetService", "AudienceTargetInput"]
