"""Сервис наборов минус-фраз (NegativeKeywordSharedSets).

Официальный справочник:
https://yandex.ru/dev/direct/doc/ru/negativekeywordsharedsets/negativekeywordsharedsets.html
Методы: add, update, delete, get. Привязка набора к группе выполняется
полем AdGroup.NegativeKeywordSharedSetIds через adgroups.update.
"""
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
from ..limits import GET_PAGE_MAX, NEGATIVE_KEYWORDS_MAX
from ..models.batch import BatchResult
from ..models.negative_keyword import NegativeKeywordSharedSet
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

#: negativekeywordsharedsets: не более 30 объектов/Id в одном вызове метода.
_MAX_SETS = NEGATIVE_KEYWORDS_MAX

_DEFAULT_FIELDS = ["Id", "Name", "NegativeKeywords", "Associated"]

NegativeKeywordSetInput = Union[NegativeKeywordSharedSet, Mapping[str, Any]]


class NegativeKeywordService:
    """Операции над наборами минус-фраз Yandex.Direct."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("negative_keywords", method_name, self._readonly)

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    def list(
        self, *, page_limit: int = GET_PAGE_MAX
    ) -> List[NegativeKeywordSharedSet]:
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
        self._validator().ids(ids, field="Ids")
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

    @overload
    def create(
        self,
        sets: Sequence[NegativeKeywordSetInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def create(
        self,
        sets: Sequence[NegativeKeywordSetInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def create(
        self,
        sets: Sequence[NegativeKeywordSetInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Создать наборы минус-фраз (batch, до 30 за запрос).

        :param sets: типизированные модели или тела SharedSetAddItem.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов AddResults (или `BatchResult`).
        """
        self._ensure_writable("create")
        body_list = [_new_body(x) for x in sets]
        return run_batches(
            self._transport,
            "negativekeywordsharedsets",
            method="add",
            params_key="NegativeKeywordSharedSets",
            items=body_list,
            on_item_error=on_item_error,
            action="создания набора минус-фраз",
            result_key="AddResults",
            chunk_size=_MAX_SETS,
        )

    @overload
    def update(
        self,
        sets: Sequence[NegativeKeywordSetInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def update(
        self,
        sets: Sequence[NegativeKeywordSetInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def update(
        self,
        sets: Sequence[NegativeKeywordSetInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Обновить наборы минус-фраз (batch, до 30 за запрос).

        :param sets: типизированные модели с Id или тела {Id, Name, ...}.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов UpdateResults (или `BatchResult`).
        """
        self._ensure_writable("update")
        body_list = [_update_body(x) for x in sets]
        return run_batches(
            self._transport,
            "negativekeywordsharedsets",
            method="update",
            params_key="NegativeKeywordSharedSets",
            items=body_list,
            on_item_error=on_item_error,
            action="обновления набора минус-фраз",
            result_key="UpdateResults",
            chunk_size=_MAX_SETS,
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
        """Удалить наборы минус-фраз по ID (авто-чанкинг по 30).

        :param ids: список ID наборов.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete")
        ensure_confirmed("negative_keywords.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return empty_result(on_item_error)
        self._validator().ids(id_list, field="SelectionCriteria.Ids")
        return run_batches(
            self._transport,
            "negativekeywordsharedsets",
            method="delete",
            params_key="SelectionCriteria",
            items=id_list,
            on_item_error=on_item_error,
            action="удаления набора минус-фраз",
            result_key="DeleteResults",
            chunk_size=_MAX_SETS,
            wrap_id=True,
        )


def _new_body(item: NegativeKeywordSetInput) -> Dict[str, Any]:
    if isinstance(item, NegativeKeywordSharedSet):
        return item.to_new_payload()
    return dict(item)


def _update_body(item: NegativeKeywordSetInput) -> Dict[str, Any]:
    if isinstance(item, NegativeKeywordSharedSet):
        return item.to_update_payload()
    return dict(item)


__all__ = ["NegativeKeywordService", "NegativeKeywordSetInput"]
