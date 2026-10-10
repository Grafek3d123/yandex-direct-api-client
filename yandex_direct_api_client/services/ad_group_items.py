"""Сервис ключевых фраз: list, get, add, set_bids, delete."""
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
from ..limits import CRITERIA_GET_MAX, GET_PAGE_MAX
from ..models.ad_group_item import (
    BID_TYPE_SEARCH,
    AdGroupItem,
    AdGroupItemBids,
)
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

_DEFAULT_FIELDS = ["Id", "CampaignId", "AdGroupId", "Item", "Bid", "Context"]

AdGroupItemInput = Union[AdGroupItem, Mapping[str, Any]]
AdGroupItemBidsInput = Union[AdGroupItemBids, Mapping[str, Any]]


class AdGroupItemService:
    """Операции над ключевыми фразами (criteria)."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("criteria", method_name, self._readonly)

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        page_limit: int = GET_PAGE_MAX,
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
        self._validator().ids(ids, field="Ids")
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[AdGroupItem] = []
        for chunk in chunked(list(ids), CRITERIA_GET_MAX):
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

    @overload
    def add(
        self,
        items: Sequence[AdGroupItemInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def add(
        self,
        items: Sequence[AdGroupItemInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def add(
        self,
        items: Sequence[AdGroupItemInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Добавить ключевые фразы (batch, до 200 за запрос).

        :param items: типизированные модели или тела AdGroupItemNew.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов AddResults (или `BatchResult`).
        """
        self._ensure_writable("add")
        item_list = [_item_body(i) for i in items]
        self._validate_items(item_list, require_id=False)
        return run_batches(
            self._transport,
            "criteria",
            method="add",
            params_key="AdGroupItems",
            items=item_list,
            on_item_error=on_item_error,
            action="добавления ключевой фразы",
            result_key="AddResults",
        )

    def _validate_items(
        self, items: Sequence[Dict[str, Any]], *, require_id: bool
    ) -> None:
        """Проверить тела ключевых фраз до отправки (если валидация включена).

        :param items: тела criteria/add или criteria/update.
        :param require_id: True ли требуется поле `Id` (для setbids).
        """
        validator = self._validator()
        for item in items:
            if require_id:
                validator.ids([item.get("Id")], field="AdGroupItem.Id")
            else:
                validator.ids(
                    [item.get("AdGroupId")], field="AdGroupItem.AdGroupId"
                )

    @overload
    def set_bids(
        self,
        bids: Sequence[AdGroupItemBidsInput],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def set_bids(
        self,
        bids: Sequence[AdGroupItemBidsInput],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def set_bids(
        self,
        bids: Sequence[AdGroupItemBidsInput],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Изменить ставки ключевых фраз (batch, до 200 за запрос).

        :param bids: типизированные модели или тела {Id, Bids}.
        :param confirm: явное подтверждение массового изменения.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов SetBidsResults (или `BatchResult`).
        """
        self._ensure_writable("set_bids")
        ensure_confirmed("criteria.set_bids", confirm)
        bid_list = [_bids_body(b) for b in bids]
        self._validate_items(bid_list, require_id=True)
        return run_batches(
            self._transport,
            "criteria",
            method="setbids",
            params_key="AdGroupItems",
            items=bid_list,
            on_item_error=on_item_error,
            action="изменения ставки ключевой фразы",
            result_key="SetBidsResults",
        )

    def set_bid(
        self,
        item_id: int,
        bid: float,
        *,
        auto_bid_fixed: Optional[float] = None,
        bid_type: str = BID_TYPE_SEARCH,
    ) -> Dict[str, Any]:
        """Изменить ставку одной ключевой фразы (одиночная операция).

        :param item_id: ID ключевой фразы.
        :param bid: новая ставка (в валюте аккаунта).
        :param auto_bid_fixed: фиксированная ставка автобиддинга.
        :param bid_type: `search` (поле `Bid`) или `network` (поле `ContextBid`).
        :return: элемент SetBidsResults.
        """
        self._ensure_writable("set_bid")
        single = AdGroupItemBids(
            id=int(item_id),
            bid=bid,
            auto_bid_fixed=auto_bid_fixed,
            bid_type=bid_type,
        )
        return self.set_bids([single], confirm=True)[0]

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
        """Удалить ключевые фразы по ID (авто-чанкинг по 200).

        :param ids: список ID ключевых фраз.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete")
        ensure_confirmed("criteria.delete", confirm)
        id_list = list(ids)
        if id_list:
            self._validator().ids(id_list, field="SelectionCriteria.Ids")
        else:
            return empty_result(on_item_error)
        return run_batches(
            self._transport,
            "criteria",
            method="delete",
            params_key="SelectionCriteria",
            items=id_list,
            on_item_error=on_item_error,
            action="удаления ключевой фразы",
            result_key="DeleteResults",
            wrap_id=True,
        )


def _item_body(item: AdGroupItemInput) -> Dict[str, Any]:
    if isinstance(item, AdGroupItem):
        return item.to_new_payload()
    return dict(item)


def _bids_body(bids: AdGroupItemBidsInput) -> Dict[str, Any]:
    if isinstance(bids, AdGroupItemBids):
        return bids.to_payload()
    return dict(bids)


__all__ = ["AdGroupItemService", "AdGroupItemInput", "AdGroupItemBidsInput"]
