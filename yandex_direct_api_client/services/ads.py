"""Сервис объявлений: list, get, create, update, delete."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .._transport import Transport
from ..exceptions import ApiError, ValidationError
from ..models.ad import Ad
from ._base import MAX_MUTATE_IDS, chunked, ensure_confirmed, fetch_all_pages

_DEFAULT_FIELDS = ["Id", "CampaignId", "AdGroupId", "Status", "State", "Type"]
_TEXT_LIMITS = {"Title": 56, "Text": 81}


def _clamp_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


class AdService:
    """Операции над объявлениями Yandex.Direct."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        if self._readonly:
            raise ValidationError(
                f"Метод ads.{method_name} запрещён в readonly-режиме"
            )

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        states: Optional[Sequence[str]] = None,
        statuses: Optional[Sequence[str]] = None,
        include_text: bool = False,
        page_limit: int = 10000,
    ) -> List[Ad]:
        """Список объявлений с авто-пагинацией.

        :param campaign_ids: фильтр по ID кампаний.
        :param ad_group_ids: фильтр по ID групп объявлений.
        :param states: фильтр по State.
        :param statuses: фильтр по Status.
        :param include_text: включить TextAd (Title/Text/Href).
        :param page_limit: размер страницы.
        """
        criteria: Dict[str, Any] = {}
        if campaign_ids:
            criteria["CampaignIds"] = list(campaign_ids)
        if ad_group_ids:
            criteria["AdGroupIds"] = list(ad_group_ids)
        if states:
            criteria["States"] = list(states)
        if statuses:
            criteria["Statuses"] = list(statuses)

        fields = list(_DEFAULT_FIELDS)
        params: Dict[str, Any] = {
            "SelectionCriteria": criteria,
            "FieldNames": fields,
        }
        if include_text:
            params["TextAdFieldNames"] = ["Title", "Text", "Href"]

        payload: Dict[str, Any] = {"method": "get", "params": params}
        raw_list = fetch_all_pages(
            self._transport, "ads", payload, page_limit=page_limit
        )
        return [Ad.from_dict(a) for a in raw_list]

    def get(
        self,
        ids: Sequence[int],
        *,
        include_text: bool = False,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[Ad]:
        """Получить объявления по ID (авто-чанкинг по 10000).

        :param ids: список ID объявлений.
        :param include_text: включить TextAd.
        :param field_names: кастомные поля.
        """
        if not ids:
            return []
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[Ad] = []
        for chunk in chunked(list(ids), 10000):
            params: Dict[str, Any] = {
                "SelectionCriteria": {"Ids": list(chunk)},
                "FieldNames": fields,
            }
            if include_text:
                params["TextAdFieldNames"] = ["Title", "Text", "Href"]
            payload: Dict[str, Any] = {"method": "get", "params": params}
            result = self._transport.post_result("ads", payload)
            for raw in result.get("Ads") or []:
                results.append(Ad.from_dict(raw))
        return results

    def create(self, ads: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Создать объявления (batch, до 200 за запрос).

        :param ads: список тел объявлений по схеме ads/add.
        :return: список AddResults.
        """
        self._ensure_writable("create")
        ad_list = list(ads)
        if not ad_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(ad_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "add",
                "params": {"Ads": list(chunk)},
            }
            result = self._transport.post_result("ads", payload)
            for item in result.get("AddResults") or []:
                _check_item_errors(item, f"создания объявления id={item.get('Id')}")
                results.append(item)
        return results

    def update(self, ads: Sequence[Dict[str, Any]], *, confirm: bool = False) -> List[Dict[str, Any]]:
        """Обновить объявления (batch, до 200 за запрос).

        :param ads: список тел с Id и обновляемыми полями (ads/update).
        :param confirm: явное подтверждение массового изменения.
        :return: список UpdateResults.
        """
        self._ensure_writable("update")
        ensure_confirmed("ads.update", confirm)
        ad_list = list(ads)
        if not ad_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(ad_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "update",
                "params": {"Ads": list(chunk)},
            }
            result = self._transport.post_result("ads", payload)
            for item in result.get("UpdateResults") or []:
                _check_item_errors(item, f"обновления объявления id={item.get('Id')}")
                results.append(item)
        return results

    def update_text(
        self,
        ad_id: int,
        headline: str,
        body: str,
        *,
        href: Optional[str] = None,
        auto_clamp: bool = True,
    ) -> Dict[str, Any]:
        """Обновить Title/Text текстового объявления (одиночное).

        :param auto_clamp: обрезать строки до лимитов Директа (56/81).
        :return: элемент UpdateResults.
        """
        self._ensure_writable("update_text")
        if auto_clamp:
            headline = _clamp_text(headline, _TEXT_LIMITS["Title"])
            body = _clamp_text(body, _TEXT_LIMITS["Text"])
        else:
            if len(headline) > _TEXT_LIMITS["Title"]:
                raise ValidationError(
                    f"headline длиннее {_TEXT_LIMITS['Title']} символов"
                )
            if len(body) > _TEXT_LIMITS["Text"]:
                raise ValidationError(
                    f"body длиннее {_TEXT_LIMITS['Text']} символов"
                )

        text_ad: Dict[str, Any] = {"Title": headline, "Text": body}
        if href is not None:
            text_ad["Href"] = href

        return self.update([{"Id": int(ad_id), "TextAd": text_ad}], confirm=True)[0]

    def delete(self, ids: Sequence[int], *, confirm: bool = False) -> List[Dict[str, Any]]:
        """Удалить объявления по ID (авто-чанкинг по 200).

        :param ids: список ID объявлений.
        :param confirm: явное подтверждение необратимой операции удаления.
        :return: список элементов DeleteResults.
        """
        self._ensure_writable("delete")
        ensure_confirmed("ads.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(id_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "delete",
                "params": {"Ids": list(chunk)},
            }
            result = self._transport.post_result("ads", payload)
            for item in result.get("DeleteResults") or []:
                _check_item_errors(item, f"удаления объявления id={item.get('Id')}")
                results.append(item)
        return results


def _check_item_errors(item: Dict[str, Any], action: str) -> None:
    errors = item.get("Errors") or []
    if errors:
        raise ApiError(
            f"Ошибка {action}: {errors[0].get('Message') or errors[0].get('Code')}",
            details=errors,
            status_code=200,
            response_body=item,
        )


__all__ = ["AdService"]
