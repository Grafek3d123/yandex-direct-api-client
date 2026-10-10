"""Сервис ретаргетинг-сегментов: list, get, add, update, delete."""
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
from ..limits import GET_PAGE_MAX, RETARGETING_ADJUSTMENTS_GET_MAX
from ..models.batch import BatchResult
from ..models.retargeting_adjustment import RetargetingBidAdjustment
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
    "CampaignId",
    "SegmentId",
    "Type",
    "LevelId",
    "LevelType",
    "BidDelta",
    "Priority",
    "Enabled",
]

AdjustmentInput = Union[RetargetingBidAdjustment, Mapping[str, Any]]


class RetargetingAdjustmentService:
    """Операции над корректировками ставок по ретаргетинг-сегментам."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("retargetingadjustments", method_name, self._readonly)

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        page_limit: int = GET_PAGE_MAX,
    ) -> List[RetargetingBidAdjustment]:
        """Список корректировок с авто-пагинацией.

        :param campaign_ids: фильтр по ID кампаний.
        :param page_limit: размер страницы.
        """
        criteria: Dict[str, Any] = {}
        if campaign_ids:
            criteria["CampaignIds"] = list(campaign_ids)

        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": _DEFAULT_FIELDS,
            },
        }
        raw_list = fetch_all_pages(
            self._transport,
            "retargetingadjustments",
            payload,
            page_limit=page_limit,
        )
        return [RetargetingBidAdjustment.from_dict(a) for a in raw_list]

    def get(
        self,
        ids: Sequence[int],
        *,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[RetargetingBidAdjustment]:
        """Получить корректировки по ID (авто-чанкинг по 1000).

        :param ids: список ID корректировок.
        :param field_names: кастомные поля.
        """
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[RetargetingBidAdjustment] = []
        for chunk in chunked(list(ids), RETARGETING_ADJUSTMENTS_GET_MAX):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": fields,
                },
            }
            result = self._transport.post_result("retargetingadjustments", payload)
            for raw in result.get("RetargetingBidAdjustments") or []:
                results.append(RetargetingBidAdjustment.from_dict(raw))
        return results

    @overload
    def add(
        self,
        adjustments: Sequence[AdjustmentInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def add(
        self,
        adjustments: Sequence[AdjustmentInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def add(
        self,
        adjustments: Sequence[AdjustmentInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Добавить корректировки (batch, до 200 за запрос).

        :param adjustments: типизированные модели или тела
            RetargetingAdjustmentNew.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов AddResults (или `BatchResult`).
        """
        self._ensure_writable("add")
        body_list = [_new_body(a) for a in adjustments]
        self._validate_bodies(body_list, require_id=False)
        return run_batches(
            self._transport,
            "retargetingadjustments",
            method="add",
            params_key="RetargetingAdjustments",
            items=body_list,
            on_item_error=on_item_error,
            action="добавления ретаргетинг-сегмента",
            result_key="AddResults",
        )

    def _validate_bodies(
        self, bodies: Sequence[Dict[str, Any]], *, require_id: bool
    ) -> None:
        """Проверить тела корректировок до отправки (если валидация включена).

        :param bodies: тела retargetingadjustments/add или /update.
        :param require_id: True ли требуется поле `Id` (для update).
        """
        validator = self._validator()
        for body in bodies:
            if require_id:
                validator.ids([body.get("Id")], field="Adjustment.Id")
            else:
                validator.ids(
                    [body.get("CampaignId")], field="Adjustment.CampaignId"
                )

    @overload
    def update(
        self,
        adjustments: Sequence[AdjustmentInput],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def update(
        self,
        adjustments: Sequence[AdjustmentInput],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def update(
        self,
        adjustments: Sequence[AdjustmentInput],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Обновить корректировки (batch, до 200 за запрос).

        :param adjustments: типизированные модели с Id или тела {Id, ...}.
        :param confirm: явное подтверждение массового изменения.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов UpdateResults (или `BatchResult`).
        """
        self._ensure_writable("update")
        ensure_confirmed("retargetingadjustments.update", confirm)
        body_list = [_update_body(a) for a in adjustments]
        self._validate_bodies(body_list, require_id=True)
        return run_batches(
            self._transport,
            "retargetingadjustments",
            method="update",
            params_key="RetargetingAdjustments",
            items=body_list,
            on_item_error=on_item_error,
            action="обновления ретаргетинг-сегмента",
            result_key="UpdateResults",
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
        """Удалить корректировки по ID (авто-чанкинг по 200).

        :param ids: список ID корректировок.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete")
        ensure_confirmed("retargetingadjustments.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return empty_result(on_item_error)
        self._validator().ids(id_list, field="SelectionCriteria.Ids")
        return run_batches(
            self._transport,
            "retargetingadjustments",
            method="delete",
            params_key="SelectionCriteria",
            items=id_list,
            on_item_error=on_item_error,
            action="удаления ретаргетинг-сегмента",
            result_key="DeleteResults",
            wrap_id=True,
        )


def _new_body(adjustment: AdjustmentInput) -> Dict[str, Any]:
    if isinstance(adjustment, RetargetingBidAdjustment):
        return adjustment.to_new_payload()
    return dict(adjustment)


def _update_body(adjustment: AdjustmentInput) -> Dict[str, Any]:
    if isinstance(adjustment, RetargetingBidAdjustment):
        return adjustment.to_update_payload()
    return dict(adjustment)


__all__ = ["RetargetingAdjustmentService", "AdjustmentInput"]
