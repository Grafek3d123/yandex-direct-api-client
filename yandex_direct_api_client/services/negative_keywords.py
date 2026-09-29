"""Сервис наборов минус-фраз (NegativeKeywordSharedSets).

Официальный справочник:
https://yandex.ru/dev/direct/doc/ru/negativekeywordsharedsets/negativekeywordsharedsets.html
Методы: add, update, delete, get. Привязка набора к группе выполняется
полем AdGroup.NegativeKeywordSharedSetIds через adgroups.update.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .._transport import Transport
from ..models.negative_keyword import NegativeKeywordSharedSet
from ._base import (
    check_item_errors,
    chunked,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
)

# negativekeywordsharedsets: не более 30 объектов/Id в одном вызове метода
_MAX_SETS = 30

_DEFAULT_FIELDS = ["Id", "Name", "NegativeKeywords", "Associated"]

NegativeKeywordSetInput = Union[NegativeKeywordSharedSet, Mapping[str, Any]]


class NegativeKeywordService:
    """Операции над наборами минус-фраз Yandex.Direct."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("negative_keywords", method_name, self._readonly)

    def list(self, *, page_limit: int = 10000) -> List[NegativeKeywordSharedSet]:
        """Список всех наборов минус-фраз клиента с авто-пагинацией.

        :param page_limit: размер страницы.
        """
        payload: Dict[str, Any] = {
            "method": "get",
            "params": {"FieldNames": _DEFAULT_FIELDS},
        }
        raw_list = fetch_all_pages(
            self._transport,
            "negativekeywordsharedsets",
            payload,
            page_limit=page_limit,
        )
        return [NegativeKeywordSharedSet.from_dict(x) for x in raw_list]

    def get(
        self,
        ids: Sequence[int],
        *,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[NegativeKeywordSharedSet]:
        """Получить наборы минус-фраз по ID (авто-чанкинг по 30).

        :param ids: список ID наборов.
        :param field_names: кастомные поля.
        """
        if not ids:
            return []
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[NegativeKeywordSharedSet] = []
        for chunk in chunked(list(ids), _MAX_SETS):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": fields,
                },
            }
            result = self._transport.post_result("negativekeywordsharedsets", payload)
            for raw in result.get("NegativeKeywordSharedSets") or []:
                results.append(NegativeKeywordSharedSet.from_dict(raw))
        return results

    def create(
        self, sets: Sequence[NegativeKeywordSetInput]
    ) -> List[Dict[str, Any]]:
        """Создать наборы минус-фраз (batch, до 30 за запрос).

        :param sets: типизированные модели или тела SharedSetAddItem.
        :return: список элементов AddResults.
        """
        self._ensure_writable("create")
        body_list = [_new_body(x) for x in sets]
        if not body_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(body_list, _MAX_SETS):
            payload: Dict[str, Any] = {
                "method": "add",
                "params": {"NegativeKeywordSharedSets": list(chunk)},
            }
            result = self._transport.post_result("negativekeywordsharedsets", payload)
            for item in result.get("AddResults") or []:
                check_item_errors(
                    item, f"создания набора минус-фраз id={item.get('Id')}"
                )
                results.append(item)
        return results

    def update(
        self, sets: Sequence[NegativeKeywordSetInput]
    ) -> List[Dict[str, Any]]:
        """Обновить наборы минус-фраз (batch, до 30 за запрос).

        :param sets: типизированные модели с Id или тела {Id, Name, ...}.
        :return: список элементов UpdateResults.
        """
        self._ensure_writable("update")
        body_list = [_update_body(x) for x in sets]
        if not body_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(body_list, _MAX_SETS):
            payload: Dict[str, Any] = {
                "method": "update",
                "params": {"NegativeKeywordSharedSets": list(chunk)},
            }
            result = self._transport.post_result("negativekeywordsharedsets", payload)
            for item in result.get("UpdateResults") or []:
                check_item_errors(
                    item, f"обновления набора минус-фраз id={item.get('Id')}"
                )
                results.append(item)
        return results

    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
    ) -> List[Dict[str, Any]]:
        """Удалить наборы минус-фраз по ID (авто-чанкинг по 30).

        :param ids: список ID наборов.
        :param confirm: явное подтверждение необратимой операции удаления.
        :return: список элементов DeleteResults.
        """
        self._ensure_writable("delete")
        ensure_confirmed("negative_keywords.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(id_list, _MAX_SETS):
            payload: Dict[str, Any] = {
                "method": "delete",
                "params": {"SelectionCriteria": {"Ids": list(chunk)}},
            }
            result = self._transport.post_result("negativekeywordsharedsets", payload)
            for item in result.get("DeleteResults") or []:
                check_item_errors(
                    item, f"удаления набора минус-фраз id={item.get('Id')}"
                )
                results.append(item)
        return results


def _new_body(item: NegativeKeywordSetInput) -> Dict[str, Any]:
    if isinstance(item, NegativeKeywordSharedSet):
        return item.to_new_payload()
    return dict(item)


def _update_body(item: NegativeKeywordSetInput) -> Dict[str, Any]:
    if isinstance(item, NegativeKeywordSharedSet):
        return item.to_update_payload()
    return dict(item)


__all__ = ["NegativeKeywordService", "NegativeKeywordSetInput"]
