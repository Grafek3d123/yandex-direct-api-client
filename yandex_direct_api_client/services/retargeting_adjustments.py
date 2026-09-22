"""Сервис ретаргетинг-сегментов: list, get, add, update, delete."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .._transport import Transport
from ..exceptions import ApiError, ValidationError
from ..models.retargeting_adjustment import RetargetingBidAdjustment
from ._base import (
    MAX_GET_IDS,
    MAX_MUTATE_IDS,
    chunked,
    ensure_confirmed,
    fetch_all_pages,
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
        if self._readonly:
            raise ValidationError(
                "Метод retargetingadjustments."
                f"{method_name} запрещён в readonly-режиме"
            )

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        page_limit: int = 10000,
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
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[RetargetingBidAdjustment] = []
        for chunk in chunked(list(ids), MAX_GET_IDS):
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

    def add(
        self, adjustments: Sequence[AdjustmentInput]
    ) -> List[Dict[str, Any]]:
        """Добавить корректировки (batch, до 200 за запрос).

        :param adjustments: типизированные модели или тела
            RetargetingAdjustmentNew.
        :return: список элементов AddResults.
        """
        self._ensure_writable("add")
        body_list = [_new_body(a) for a in adjustments]
        if not body_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(body_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "add",
                "params": {"RetargetingAdjustments": list(chunk)},
            }
            result = self._transport.post_result("retargetingadjustments", payload)
            for item in result.get("AddResults") or []:
                _check_item_errors(
                    item,
                    f"добавления ретаргетинг-сегмента id={item.get('Id')}",
                )
                results.append(item)
        return results

    def update(
        self,
        adjustments: Sequence[AdjustmentInput],
        *,
        confirm: bool = False,
    ) -> List[Dict[str, Any]]:
        """Обновить корректировки (batch, до 200 за запрос).

        :param adjustments: типизированные модели с Id или тела {Id, ...}.
        :param confirm: явное подтверждение массового изменения.
        :return: список элементов UpdateResults.
        """
        self._ensure_writable("update")
        ensure_confirmed("retargetingadjustments.update", confirm)
        body_list = [_update_body(a) for a in adjustments]
        if not body_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(body_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "update",
                "params": {"RetargetingAdjustments": list(chunk)},
            }
            result = self._transport.post_result("retargetingadjustments", payload)
            for item in result.get("UpdateResults") or []:
                _check_item_errors(
                    item,
                    f"обновления ретаргетинг-сегмента id={item.get('Id')}",
                )
                results.append(item)
        return results

    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
    ) -> List[Dict[str, Any]]:
        """Удалить корректировки по ID (авто-чанкинг по 200).

        :param ids: список ID корректировок.
        :param confirm: явное подтверждение необратимой операции удаления.
        :return: список элементов DeleteResults.
        """
        self._ensure_writable("delete")
        ensure_confirmed("retargetingadjustments.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(id_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "delete",
                "params": {"Ids": list(chunk)},
            }
            result = self._transport.post_result("retargetingadjustments", payload)
            for item in result.get("DeleteResults") or []:
                _check_item_errors(
                    item,
                    f"удаления ретаргетинг-сегмента id={item.get('Id')}",
                )
                results.append(item)
        return results


def _new_body(adjustment: AdjustmentInput) -> Dict[str, Any]:
    if isinstance(adjustment, RetargetingBidAdjustment):
        return adjustment.to_new_payload()
    return dict(adjustment)


def _update_body(adjustment: AdjustmentInput) -> Dict[str, Any]:
    if isinstance(adjustment, RetargetingBidAdjustment):
        return adjustment.to_update_payload()
    return dict(adjustment)


def _check_item_errors(item: Dict[str, Any], action: str) -> None:
    errors = item.get("Errors") or []
    if errors:
        raise ApiError(
            f"Ошибка {action}: {errors[0].get('Message') or errors[0].get('Code')}",
            details=errors,
            status_code=200,
            response_body=item,
        )


__all__ = ["RetargetingAdjustmentService", "AdjustmentInput"]
