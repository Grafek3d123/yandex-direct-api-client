"""Сервис кампаний: list, get, create, update, delete."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .._transport import Transport
from ..exceptions import ApiError
from ..models.campaign import Campaign
from ._base import (
    MAX_GET_IDS,
    check_item_errors,
    chunked,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
)

_DEFAULT_FIELDS = [
    "Id",
    "Name",
    "Status",
    "State",
    "Type",
    "StartDate",
    "EndDate",
]


class CampaignService:
    """Операции над кампаниями Yandex.Direct."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("campaigns", method_name, self._readonly)

    def list(
        self,
        *,
        states: Optional[Sequence[str]] = None,
        statuses: Optional[Sequence[str]] = None,
        page_limit: int = 10000,
    ) -> List[Campaign]:
        """Список кампаний клиента с авто-пагинацией.

        :param states: фильтр по State (ON, OFF, SUSPENDED, ENDED, ARCHIVED, CONVERTED).
        :param statuses: фильтр по Status (ACCEPTED, DRAFT, MODERATION, REJECTED).
        :param page_limit: размер страницы (до 10000).
        """
        criteria: Dict[str, Any] = {}
        if states:
            criteria["States"] = list(states)
        if statuses:
            criteria["Statuses"] = list(statuses)

        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": _DEFAULT_FIELDS,
            },
        }
        raw_list = fetch_all_pages(
            self._transport, "campaigns", payload, page_limit=page_limit
        )
        return [Campaign.from_dict(c) for c in raw_list]

    def get(
        self,
        ids: Sequence[int],
        *,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[Campaign]:
        """Получить кампании по ID (авто-чанкинг по 1000).

        :param ids: список ID кампаний.
        :param field_names: кастомный список полей для запроса.
        """
        if not ids:
            return []
        fields = list(field_names) if field_names else _DEFAULT_FIELDS
        results: List[Campaign] = []
        for chunk in chunked(list(ids), MAX_GET_IDS):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": fields,
                },
            }
            result = self._transport.post_result("campaigns", payload)
            for raw in result.get("Campaigns") or []:
                results.append(Campaign.from_dict(raw))
        return results

    def create(self, campaign: Dict[str, Any]) -> Dict[str, Any]:
        """Создать кампанию.

        :param campaign: тело кампании по схеме campaigns/add.
        :return: элемент AddResults.
        """
        self._ensure_writable("create")
        payload: Dict[str, Any] = {
            "method": "add",
            "params": {"Campaigns": [campaign]},
        }
        result = self._transport.post_result("campaigns", payload)
        add_results = result.get("AddResults") or []
        if not add_results:
            raise ApiError(
                "Пустой AddResults в ответе API",
                status_code=200,
                response_body=result,
            )
        first: Dict[str, Any] = add_results[0]
        check_item_errors(first, "создания кампании")
        return first

    def update(self, campaign: Dict[str, Any]) -> Dict[str, Any]:
        """Обновить кампанию.

        :param campaign: тело с Id и обновляемыми полями (campaigns/update).
        :return: элемент UpdateResults.
        """
        self._ensure_writable("update")
        payload: Dict[str, Any] = {
            "method": "update",
            "params": {"Campaigns": [campaign]},
        }
        result = self._transport.post_result("campaigns", payload)
        update_results = result.get("UpdateResults") or []
        if not update_results:
            raise ApiError(
                "Пустой UpdateResults в ответе API",
                status_code=200,
                response_body=result,
            )
        first: Dict[str, Any] = update_results[0]
        check_item_errors(first, "обновления кампании")
        return first

    def delete(self, ids: Sequence[int], *, confirm: bool = False) -> List[Dict[str, Any]]:
        """Удалить кампании по ID (авто-чанкинг по 200).

        :param ids: список ID кампаний.
        :param confirm: явное подтверждение необратимой операции удаления.
        :return: список элементов DeleteResults.
        """
        self._ensure_writable("delete")
        ensure_confirmed("campaigns.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(id_list, 200):
            payload: Dict[str, Any] = {
                "method": "delete",
                "params": {"SelectionCriteria": {"Ids": list(chunk)}},
            }
            result = self._transport.post_result("campaigns", payload)
            for item in result.get("DeleteResults") or []:
                check_item_errors(item, f"удаления кампании id={item.get('Id')}")
                results.append(item)
        return results


__all__ = ["CampaignService"]
