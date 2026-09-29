"""Сервис групп объявлений: list, get, create, update, delete."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .._transport import Transport
from ..exceptions import ValidationError
from ..models.ad_group import AdGroup
from ._base import (
    MAX_MUTATE_IDS,
    check_item_errors,
    chunked,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
)

# Валидные имена полей для adgroups/get (AdGroupFieldEnum). У группы НЕТ поля
# State — только Status и ServingStatus (в отличие от кампаний/объявлений).
_DEFAULT_FIELDS = ["Id", "Name", "CampaignId", "Status", "Type", "RegionIds"]

AdGroupInput = Union[AdGroup, Mapping[str, Any]]


class AdGroupService:
    """Операции над группами объявлений Yandex.Direct."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("adgroups", method_name, self._readonly)

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        statuses: Optional[Sequence[str]] = None,
        serving_statuses: Optional[Sequence[str]] = None,
        page_limit: int = 10000,
    ) -> List[AdGroup]:
        """Список групп объявлений с авто-пагинацией.

        :param campaign_ids: фильтр по ID кампаний.
        :param statuses: фильтр по Status (DRAFT/ACCEPTED/MODERATION/...).
        :param serving_statuses: фильтр по ServingStatus (ELIGIBLE/
            RARELY_SERVED). У группы нет поля State, поэтому фильтра по
            State нет — см. официальный справочник adgroups/get.
        :param page_limit: размер страницы.
        """
        criteria: Dict[str, Any] = {}
        if campaign_ids:
            criteria["CampaignIds"] = list(campaign_ids)
        if statuses:
            criteria["Statuses"] = list(statuses)
        if serving_statuses:
            criteria["ServingStatuses"] = list(serving_statuses)
        # AdGroupsSelectionCriteria требует хотя бы один из CampaignIds/Ids
        # (см. официальный справочник adgroups/get). list() не принимает Ids,
        # поэтому обязателен campaign_ids — иначе API вернёт
        # "filtration parameters incorrectly set".
        if not campaign_ids:
            raise ValidationError(
                "adgroups/get требует фильтр CampaignIds (или Ids через get()); "
                "вызов ad_groups.list() без campaign_ids невозможен"
            )

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

    def create(self, ad_groups: Sequence[AdGroupInput]) -> List[Dict[str, Any]]:
        """Создать группы объявлений (batch, до 200 за запрос).

        :param ad_groups: типизированные модели AdGroup или тела
            AdGroupAddItem (adgroups/add).
        :return: список элементов AddResults.
        """
        self._ensure_writable("create")
        body_list = [_new_body(g) for g in ad_groups]
        if not body_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(body_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "add",
                "params": {"AdGroups": list(chunk)},
            }
            result = self._transport.post_result("adgroups", payload)
            for item in result.get("AddResults") or []:
                check_item_errors(
                    item, f"создания группы объявлений id={item.get('Id')}"
                )
                results.append(item)
        return results

    def update(self, ad_groups: Sequence[AdGroupInput]) -> List[Dict[str, Any]]:
        """Обновить группы объявлений (batch, до 200 за запрос).

        :param ad_groups: типизированные модели с Id или тела
            AdGroupUpdateItem (adgroups/update).
        :return: список элементов UpdateResults.
        """
        self._ensure_writable("update")
        body_list = [_update_body(g) for g in ad_groups]
        if not body_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(body_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "update",
                "params": {"AdGroups": list(chunk)},
            }
            result = self._transport.post_result("adgroups", payload)
            for item in result.get("UpdateResults") or []:
                check_item_errors(
                    item, f"обновления группы объявлений id={item.get('Id')}"
                )
                results.append(item)
        return results

    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
    ) -> List[Dict[str, Any]]:
        """Удалить группы объявлений по ID (авто-чанкинг по 200).

        :param ids: список ID групп.
        :param confirm: явное подтверждение необратимой операции удаления.
        :return: список элементов DeleteResults.
        """
        self._ensure_writable("delete")
        ensure_confirmed("adgroups.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(id_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "delete",
                "params": {"SelectionCriteria": {"Ids": list(chunk)}},
            }
            result = self._transport.post_result("adgroups", payload)
            for item in result.get("DeleteResults") or []:
                check_item_errors(
                    item, f"удаления группы объявлений id={item.get('Id')}"
                )
                results.append(item)
        return results


def _new_body(ad_group: AdGroupInput) -> Dict[str, Any]:
    if isinstance(ad_group, AdGroup):
        return ad_group.to_new_payload()
    return dict(ad_group)


def _update_body(ad_group: AdGroupInput) -> Dict[str, Any]:
    if isinstance(ad_group, AdGroup):
        return ad_group.to_update_payload()
    return dict(ad_group)


__all__ = ["AdGroupService", "AdGroupInput"]
