"""Сервис условий нацеливания на аудиторию (AudienceTargets).

Официальный справочник:
https://yandex.ru/dev/direct/doc/ru/audiencetargets/audiencetargets.html
Методы API: add, delete, suspend, resume, get, setBids.

Примечание: у audiencetargets НЕТ метода update — изменение ставки/приоритета
выполняется методом setBids, а смена состава условия — create + delete.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .._transport import Transport
from ..models.audience_target import AudienceTarget
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

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        states: Optional[Sequence[str]] = None,
        page_limit: int = 10000,
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
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[AudienceTarget] = []
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
                results.append(AudienceTarget.from_dict(raw))
        return results

    def create(
        self, targets: Sequence[AudienceTargetInput]
    ) -> List[Dict[str, Any]]:
        """Создать условия нацеливания (batch, до 200 за запрос).

        :param targets: типизированные модели или тела AudienceTargetAddItem.
        :return: список элементов AddResults.
        """
        self._ensure_writable("create")
        body_list = [_new_body(x) for x in targets]
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
                    item, f"создания условия нацеливания id={item.get('Id')}"
                )
                results.append(item)
        return results

    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
    ) -> List[Dict[str, Any]]:
        """Удалить условия нацеливания по ID (авто-чанкинг по 200).

        :param ids: список ID условий.
        :param confirm: явное подтверждение необратимой операции удаления.
        :return: список элементов DeleteResults.
        """
        self._ensure_writable("delete")
        ensure_confirmed("audience_targets.delete", confirm)
        return self._ids_action(
            "delete", "DeleteResults", "удаления условия нацеливания", ids
        )

    def suspend(self, ids: Sequence[int]) -> List[Dict[str, Any]]:
        """Остановить показы условий нацеливания (audiencetargets/suspend).

        :param ids: список ID условий.
        :return: список элементов SuspendResults.
        """
        return self._ids_action(
            "suspend", "SuspendResults", "остановки условия нацеливания", ids
        )

    def resume(self, ids: Sequence[int]) -> List[Dict[str, Any]]:
        """Возобновить показы условий нацеливания (audiencetargets/resume).

        :param ids: список ID условий.
        :return: список элементов ResumeResults.
        """
        return self._ids_action(
            "resume", "ResumeResults", "возобновления условия нацеливания", ids
        )

    def _ids_action(
        self,
        method_name: str,
        result_key: str,
        action_label: str,
        ids: Sequence[int],
    ) -> List[Dict[str, Any]]:
        """Общий batch-вызов метода по SelectionCriteria.Ids."""
        self._ensure_writable(method_name)
        id_list = list(ids)
        if not id_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(id_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": method_name,
                "params": {"SelectionCriteria": {"Ids": list(chunk)}},
            }
            result = self._transport.post_result("audiencetargets", payload)
            for item in result.get(result_key) or []:
                check_item_errors(item, f"{action_label} id={item.get('Id')}")
                results.append(item)
        return results

    def set_bids(
        self, bids: Sequence[AudienceTargetInput]
    ) -> List[Dict[str, Any]]:
        """Назначить ставки/приоритеты (audiencetargets/setBids, до 200 за запрос).

        :param bids: типизированные модели с Id и ContextBid/StrategyPriority
            или тела AudienceTargetSetBidsItem {Id, ContextBid, StrategyPriority}.
        :return: список элементов SetBidsResults.
        """
        self._ensure_writable("set_bids")
        body_list = [_set_bid_body(x) for x in bids]
        if not body_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(body_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "setBids",
                "params": {"Bids": list(chunk)},
            }
            result = self._transport.post_result("audiencetargets", payload)
            for item in result.get("SetBidsResults") or []:
                check_item_errors(
                    item, f"назначения ставки условия нацеливания id={item.get('Id')}"
                )
                results.append(item)
        return results


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
