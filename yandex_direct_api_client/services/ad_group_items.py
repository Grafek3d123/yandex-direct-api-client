"""Сервис ключевых фраз: list, get, add, set_bids, delete."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .._transport import Transport
from ..exceptions import ApiError, ValidationError
from ..models.ad_group_item import AdGroupItem, AdGroupItemBids
from ._base import (
    MAX_GET_IDS,
    MAX_MUTATE_IDS,
    chunked,
    ensure_confirmed,
    fetch_all_pages,
)

_DEFAULT_FIELDS = ["Id", "CampaignId", "AdGroupId", "Item", "Bid", "Context"]

AdGroupItemInput = Union[AdGroupItem, Mapping[str, Any]]
AdGroupItemBidsInput = Union[AdGroupItemBids, Mapping[str, Any]]


class AdGroupItemService:
    """Операции над ключевыми фразами (criteria)."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        if self._readonly:
            raise ValidationError(
                f"Метод criteria.{method_name} запрещён в readonly-режиме"
            )

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        page_limit: int = 10000,
    ) -> List[AdGroupItem]:
        """Список ключевых фраз с авто-пагинацией.

        :param campaign_ids: фильтр по ID кампаний.
        :param ad_group_ids: фильтр по ID групп объявлений.
        :param page_limit: размер страницы.
        """
        criteria: Dict[str, Any] = {}
        if campaign_ids:
            criteria["CampaignIds"] = list(campaign_ids)
        if ad_group_ids:
            criteria["AdGroupIds"] = list(ad_group_ids)

        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": _DEFAULT_FIELDS,
            },
        }
        raw_list = fetch_all_pages(
            self._transport, "criteria", payload, page_limit=page_limit
        )
        return [AdGroupItem.from_dict(i) for i in raw_list]

    def get(
        self,
        ids: Sequence[int],
        *,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[AdGroupItem]:
        """Получить ключевые фразы по ID (авто-чанкинг по 1000).

        :param ids: список ID ключевых фраз.
        :param field_names: кастомные поля.
        """
        if not ids:
            return []
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[AdGroupItem] = []
        for chunk in chunked(list(ids), MAX_GET_IDS):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": fields,
                },
            }
            result = self._transport.post_result("criteria", payload)
            for raw in result.get("AdGroupItems") or []:
                results.append(AdGroupItem.from_dict(raw))
        return results

    def add(self, items: Sequence[AdGroupItemInput]) -> List[Dict[str, Any]]:
        """Добавить ключевые фразы (batch, до 200 за запрос).

        :param items: типизированные модели или тела AdGroupItemNew.
        :return: список элементов AddResults.
        """
        self._ensure_writable("add")
        item_list = [_item_body(i) for i in items]
        if not item_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(item_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "add",
                "params": {"AdGroupItems": list(chunk)},
            }
            result = self._transport.post_result("criteria", payload)
            for item in result.get("AddResults") or []:
                _check_item_errors(
                    item, f"добавления ключевой фразы id={item.get('Id')}"
                )
                results.append(item)
        return results

    def set_bids(
        self,
        bids: Sequence[AdGroupItemBidsInput],
        *,
        confirm: bool = False,
    ) -> List[Dict[str, Any]]:
        """Изменить ставки ключевых фраз (batch, до 200 за запрос).

        :param bids: типизированные модели или тела {Id, Bids}.
        :param confirm: явное подтверждение массового изменения.
        :return: список элементов SetBidsResults.
        """
        self._ensure_writable("set_bids")
        ensure_confirmed("criteria.set_bids", confirm)
        bid_list = [_bids_body(b) for b in bids]
        if not bid_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(bid_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "setbids",
                "params": {"AdGroupItems": list(chunk)},
            }
            result = self._transport.post_result("criteria", payload)
            for item in result.get("SetBidsResults") or []:
                _check_item_errors(
                    item, f"изменения ставки id={item.get('Id')}"
                )
                results.append(item)
        return results

    def set_bid(
        self,
        item_id: int,
        bid: float,
        *,
        auto_bid_fixed: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Изменить ставку одной ключевой фразы (одиночная операция).

        :param item_id: ID ключевой фразы.
        :param bid: новая ставка.
        :param auto_bid_fixed: фиксированная ставка автобiddingа.
        :return: элемент SetBidsResults.
        """
        self._ensure_writable("set_bid")
        single = AdGroupItemBids(
            id=int(item_id), bid=bid, auto_bid_fixed=auto_bid_fixed
        )
        return self.set_bids([single], confirm=True)[0]

    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
    ) -> List[Dict[str, Any]]:
        """Удалить ключевые фразы по ID (авто-чанкинг по 200).

        :param ids: список ID ключевых фраз.
        :param confirm: явное подтверждение необратимой операции удаления.
        :return: список элементов DeleteResults.
        """
        self._ensure_writable("delete")
        ensure_confirmed("criteria.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(id_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "delete",
                "params": {"Ids": list(chunk)},
            }
            result = self._transport.post_result("criteria", payload)
            for item in result.get("DeleteResults") or []:
                _check_item_errors(
                    item, f"удаления ключевой фразы id={item.get('Id')}"
                )
                results.append(item)
        return results


def _item_body(item: AdGroupItemInput) -> Dict[str, Any]:
    if isinstance(item, AdGroupItem):
        return item.to_new_payload()
    return dict(item)


def _bids_body(bids: AdGroupItemBidsInput) -> Dict[str, Any]:
    if isinstance(bids, AdGroupItemBids):
        return bids.to_payload()
    return dict(bids)


def _check_item_errors(item: Dict[str, Any], action: str) -> None:
    errors = item.get("Errors") or []
    if errors:
        raise ApiError(
            f"Ошибка {action}: {errors[0].get('Message') or errors[0].get('Code')}",
            details=errors,
            status_code=200,
            response_body=item,
        )


__all__ = ["AdGroupItemService", "AdGroupItemInput", "AdGroupItemBidsInput"]
