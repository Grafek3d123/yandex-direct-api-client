"""Сервис групп объявлений: list, get, create, update, delete."""
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
from ..config import API_VERSION_V501
from ..exceptions import ValidationError
from ..limits import ADGROUPS_GET_MAX, GET_PAGE_MAX, MUTATE_MAX
from ..models.ad_group import AdGroup
from ..models.ad_group_payloads import AdGroupBuilder, UnifiedAdGroup
from ..models.batch import BatchResult
from ..validation import NAME_MAX_LENGTH, Validator
from ._base import (
    OnItemError,
    ResultCollector,
    chunked,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
)

# Валидные имена полей для adgroups/get (AdGroupFieldEnum). У группы НЕТ поля
# State — только Status и ServingStatus (в отличие от кампаний/объявлений).
_DEFAULT_FIELDS = ["Id", "Name", "CampaignId", "Status", "Type", "RegionIds"]

#: Группа для `ad_groups.create`: билдер, модель или сырой dict.
AdGroupInput = Union[AdGroupBuilder, AdGroup, Mapping[str, Any]]


def _auto_version(items: Sequence[AdGroupInput]) -> Optional[str]:
    """Определить версию API по типу групп: ЕПК доступна только в `v501`.

    :param items: группы объявлений.
    :return: `v501` либо None (версия по умолчанию).
    """
    if any(isinstance(item, UnifiedAdGroup) for item in items):
        return API_VERSION_V501
    return None


class AdGroupService:
    """Операции над группами объявлений Yandex.Direct."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("adgroups", method_name, self._readonly)

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        statuses: Optional[Sequence[str]] = None,
        serving_statuses: Optional[Sequence[str]] = None,
        page_limit: int = GET_PAGE_MAX,
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
        self._validator().ids(ids, field="Ids")
        fields = list(field_names) if field_names else _DEFAULT_FIELDS
        results: List[AdGroup] = []
        for chunk in chunked(list(ids), ADGROUPS_GET_MAX):
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

    @overload
    def create(
        self,
        ad_groups: Sequence[AdGroupInput],
        *,
        api_version: Optional[str] = None,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def create(
        self,
        ad_groups: Sequence[AdGroupInput],
        *,
        api_version: Optional[str] = None,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def create(
        self,
        ad_groups: Sequence[AdGroupInput],
        *,
        api_version: Optional[str] = None,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Создать группы объявлений (batch, до 200 за запрос).

        Для группы ЕПК (`UnifiedAdGroup`) версия `v501` подставляется
        автоматически; передать другую версию можно явно через
        `api_version`.

        :param ad_groups: типизированные модели AdGroup или тела
            AdGroupAddItem (adgroups/add).
        :param api_version: версия API для этого вызова (None — по умолчанию).
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов AddResults (или `BatchResult`).
        """
        self._ensure_writable("create")
        bodies = [_new_body(g) for g in ad_groups]
        self._validate_bodies(bodies, require_id=False)
        if not bodies:
            return [] if on_item_error == "raise" else BatchResult()
        version = api_version or _auto_version(ad_groups)
        collector = ResultCollector(on_item_error)
        for chunk in chunked(bodies, MUTATE_MAX):
            payload: Dict[str, Any] = {
                "method": "add",
                "params": {"AdGroups": list(chunk)},
            }
            result = self._transport.post_result(
                "adgroups", payload, api_version=version
            )
            collector.set_request_id(self._transport.last_request_id)
            collector.add(
                result.get("AddResults") or [],
                "создания группы объявлений",
            )
        return collector.finish()

    @overload
    def update(
        self,
        ad_groups: Sequence[AdGroupInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def update(
        self,
        ad_groups: Sequence[AdGroupInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def update(
        self,
        ad_groups: Sequence[AdGroupInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Обновить группы объявлений (batch, до 200 за запрос).

        :param ad_groups: типизированные модели с Id или тела
            AdGroupUpdateItem (adgroups/update).
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов UpdateResults (или `BatchResult`).
        """
        self._ensure_writable("update")
        bodies = [_update_body(g) for g in ad_groups]
        self._validate_bodies(bodies, require_id=True)
        if not bodies:
            return [] if on_item_error == "raise" else BatchResult()
        collector = ResultCollector(on_item_error)
        for chunk in chunked(bodies, MUTATE_MAX):
            payload: Dict[str, Any] = {
                "method": "update",
                "params": {"AdGroups": list(chunk)},
            }
            result = self._transport.post_result("adgroups", payload)
            collector.set_request_id(self._transport.last_request_id)
            collector.add(
                result.get("UpdateResults") or [],
                "обновления группы объявлений",
            )
        return collector.finish()

    def _validate_bodies(
        self, bodies: Sequence[Dict[str, Any]], *, require_id: bool
    ) -> None:
        """Проверить тела групп до отправки (если валидация включена).

        :param bodies: тела adgroups/add или adgroups/update.
        :param require_id: True ли требуется поле `Id` (для update).
        """
        validator = self._validator()
        for body in bodies:
            if require_id:
                validator.ids([body.get("Id")], field="AdGroup.Id")
            else:
                validator.ids(
                    [body.get("CampaignId")], field="AdGroup.CampaignId"
                )
            if "Name" in body:
                validator.name(
                    body.get("Name"),
                    field="AdGroup.Name",
                    max_length=NAME_MAX_LENGTH,
                )
            if "RegionIds" in body:
                validator.region_ids(body.get("RegionIds"))

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
        """Удалить группы объявлений по ID (авто-чанкинг по 200).

        :param ids: список ID групп.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete")
        ensure_confirmed("adgroups.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return [] if on_item_error == "raise" else BatchResult()
        self._validator().ids(id_list, field="SelectionCriteria.Ids")
        collector = ResultCollector(on_item_error)
        for chunk in chunked(id_list, MUTATE_MAX):
            payload: Dict[str, Any] = {
                "method": "delete",
                "params": {"SelectionCriteria": {"Ids": list(chunk)}},
            }
            result = self._transport.post_result("adgroups", payload)
            collector.set_request_id(self._transport.last_request_id)
            collector.add(
                result.get("DeleteResults") or [],
                "удаления группы объявлений",
            )
        return collector.finish()


def _new_body(ad_group: AdGroupInput) -> Dict[str, Any]:
    if isinstance(ad_group, Mapping):
        return dict(ad_group)
    if isinstance(ad_group, AdGroupBuilder):
        return ad_group.to_payload()
    return ad_group.to_new_payload()


def _update_body(ad_group: AdGroupInput) -> Dict[str, Any]:
    if isinstance(ad_group, Mapping):
        return dict(ad_group)
    if isinstance(ad_group, AdGroupBuilder):
        raise ValidationError(
            "Билдер группы нельзя обновить без ID: используйте "
            "builder.to_update_payload(ad_group_id) или передайте тело с Id"
        )
    return ad_group.to_update_payload()


__all__ = ["AdGroupService", "AdGroupInput"]
