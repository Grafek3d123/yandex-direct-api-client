"""Сервис групп объявлений: list, get."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .._transport import Transport
from ..models.ad_group import AdGroup
from ._base import chunked, fetch_all_pages

_DEFAULT_FIELDS = ["Id", "CampaignId", "Name", "Status", "State"]


class AdGroupService:
    """Операции над группами объявлений Yandex.Direct."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        states: Optional[Sequence[str]] = None,
        statuses: Optional[Sequence[str]] = None,
        page_limit: int = 10000,
    ) -> List[AdGroup]:
        """Список групп объявлений с авто-пагинацией.

        :param campaign_ids: фильтр по ID кампаний.
        :param states: фильтр по State.
        :param statuses: фильтр по Status.
        :param page_limit: размер страницы.
        """
        criteria: Dict[str, Any] = {}
        if campaign_ids:
            criteria["CampaignIds"] = list(campaign_ids)
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
            self._transport, "adgroups", payload, page_limit=page_limit
        )
        return [AdGroup.from_dict(g) for g in raw_list]

    def get(
        self,
        ids: Sequence[int],
        *,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[AdGroup]:
        """Получить группы объявлений по ID (авто-чанкинг по 10000).

        :param ids: список ID групп.
        :param field_names: кастомные поля.
        """
        if not ids:
            return []
        fields = list(field_names) if field_names else _DEFAULT_FIELDS
        results: List[AdGroup] = []
        for chunk in chunked(list(ids), 10000):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": fields,
                },
            }
            result = self._transport.post_result("adgroups", payload)
            for raw in result.get("AdGroups") or []:
                results.append(AdGroup.from_dict(raw))
        return results


__all__ = ["AdGroupService"]
