"""Сервис расширений объявлений: быстрые ссылки и уточнения.

Официальные справочники (подтверждены):
- быстрые ссылки (sitelinks):
  https://yandex.ru/dev/direct/doc/ru/sitelinks/sitelinks.html
  методы add, get, delete (обновление = create + delete по семантике API)
- уточнения (adextensions, тип CALLOUT):
  https://yandex.ru/dev/direct/doc/ru/adextensions/adextensions.html
  методы add, get, delete
"""
from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Literal,
    Mapping,
    Sequence,
    Union,
    overload,
)

from .._transport import Transport
from ..limits import AD_EXTENSIONS_GET_MAX, GET_PAGE_MAX
from ..models.ad_extension import Callout, Sitelink, SitelinksSet
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

_SITELINKS_FIELDS = ["Id", "Sitelinks"]
_CALLOUT_FIELDS = ["Id", "Type", "Status", "StatusClarification", "Associated"]
_CALLOUT_SUBFIELDS = ["CalloutText"]

SitelinksSetInput = Union[SitelinksSet, Mapping[str, Any]]
CalloutInput = Union[Callout, Mapping[str, Any]]


class AdExtensionService:
    """Операции над расширениями объявлений (быстрые ссылки и уточнения)."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("ad_extensions", method_name, self._readonly)

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    # ---------------- быстрые ссылки (sitelinks) ----------------
    def list_sitelinks(self, *, page_limit: int = GET_PAGE_MAX) -> List[SitelinksSet]:
        """Список наборов быстрых ссылок с авто-пагинацией.

        :param page_limit: размер страницы.
        """
        payload: Dict[str, Any] = {
            "method": "get",
            "params": {"FieldNames": _SITELINKS_FIELDS},
        }
        raw_list = fetch_all_pages(
            self._transport, "sitelinks", payload, page_limit=page_limit
        )
        return [SitelinksSet.from_dict(x) for x in raw_list]

    def get_sitelinks(self, ids: Sequence[int]) -> List[SitelinksSet]:
        """Получить наборы быстрых ссылок по ID (авто-чанкинг по 1000).

        :param ids: список ID наборов.
        """
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        results: List[SitelinksSet] = []
        for chunk in chunked(list(ids), AD_EXTENSIONS_GET_MAX):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": _SITELINKS_FIELDS,
                },
            }
            result = self._transport.post_result("sitelinks", payload)
            for raw in result.get("SitelinksSets") or []:
                results.append(SitelinksSet.from_dict(raw))
        return results

    @overload
    def create_sitelinks(
        self,
        sets: Sequence[SitelinksSetInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def create_sitelinks(
        self,
        sets: Sequence[SitelinksSetInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def create_sitelinks(
        self,
        sets: Sequence[SitelinksSetInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Создать наборы быстрых ссылок (batch, до 200 за запрос).

        :param sets: типизированные модели SitelinksSet или тела
            SitelinksSetAddItem {Sitelinks: [...]}.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов AddResults (или `BatchResult`).
        """
        self._ensure_writable("create_sitelinks")
        body_list = [_sitelinks_new_body(x) for x in sets]
        return run_batches(
            self._transport,
            "sitelinks",
            method="add",
            params_key="SitelinksSets",
            items=body_list,
            on_item_error=on_item_error,
            action="создания набора быстрых ссылок",
            result_key="AddResults",
        )

    @overload
    def delete_sitelinks(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def delete_sitelinks(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def delete_sitelinks(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Удалить наборы быстрых ссылок по ID (авто-чанкинг по 200).

        :param ids: список ID наборов.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete_sitelinks")
        ensure_confirmed("ad_extensions.delete_sitelinks", confirm)
        return self._ids_action(
            "sitelinks",
            "delete",
            "DeleteResults",
            "удаления набора быстрых ссылок",
            ids,
            on_item_error,
        )

    # ---------------- уточнения (adextensions, CALLOUT) ----------------
    def list_callouts(self, *, page_limit: int = GET_PAGE_MAX) -> List[Callout]:
        """Список уточнений с авто-пагинацией.

        :param page_limit: размер страницы.
        """
        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "SelectionCriteria": {},
                "FieldNames": _CALLOUT_FIELDS,
                "CalloutFieldNames": _CALLOUT_SUBFIELDS,
            },
        }
        raw_list = fetch_all_pages(
            self._transport, "adextensions", payload, page_limit=page_limit
        )
        return [Callout.from_dict(x) for x in raw_list]

    def get_callouts(self, ids: Sequence[int]) -> List[Callout]:
        """Получить уточнения по ID (авто-чанкинг по 1000).

        :param ids: список ID уточнений.
        """
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        results: List[Callout] = []
        for chunk in chunked(list(ids), AD_EXTENSIONS_GET_MAX):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": _CALLOUT_FIELDS,
                    "CalloutFieldNames": _CALLOUT_SUBFIELDS,
                },
            }
            result = self._transport.post_result("adextensions", payload)
            for raw in result.get("AdExtensions") or []:
                results.append(Callout.from_dict(raw))
        return results

    @overload
    def create_callouts(
        self,
        callouts: Sequence[CalloutInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def create_callouts(
        self,
        callouts: Sequence[CalloutInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def create_callouts(
        self,
        callouts: Sequence[CalloutInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Создать уточнения (batch, до 200 за запрос).

        :param callouts: типизированные модели Callout или тела
            AdExtensionAddItem {Callout: {CalloutText}}.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов AddResults (или `BatchResult`).
        """
        self._ensure_writable("create_callouts")
        body_list = [_callout_new_body(x) for x in callouts]
        return run_batches(
            self._transport,
            "adextensions",
            method="add",
            params_key="AdExtensions",
            items=body_list,
            on_item_error=on_item_error,
            action="создания уточнения",
            result_key="AddResults",
        )

    @overload
    def delete_callouts(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def delete_callouts(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def delete_callouts(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Удалить уточнения по ID (авто-чанкинг по 200).

        :param ids: список ID уточнений.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete_callouts")
        ensure_confirmed("ad_extensions.delete_callouts", confirm)
        return self._ids_action(
            "adextensions",
            "delete",
            "DeleteResults",
            "удаления уточнения",
            ids,
            on_item_error,
        )

    # ---------------- общий хелпер ----------------
    def _ids_action(
        self,
        service: str,
        method_name: str,
        result_key: str,
        action_label: str,
        ids: Sequence[int],
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Общий batch-вызов delete по SelectionCriteria.Ids.

        :param service: имя API-сервиса (sitelinks/adextensions).
        :param method_name: имя метода API.
        :param result_key: ключ списка результатов в ответе.
        :param action_label: описание действия для сообщений об ошибках.
        :param ids: список ID расширений.
        :param on_item_error: `raise` или `collect`.
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        id_list = list(ids)
        if not id_list:
            return empty_result(on_item_error)
        self._validator().ids(id_list, field="SelectionCriteria.Ids")
        return run_batches(
            self._transport,
            service,
            method=method_name,
            params_key="SelectionCriteria",
            items=id_list,
            on_item_error=on_item_error,
            action=action_label,
            result_key=result_key,
            wrap_id=True,
        )


def _sitelinks_new_body(item: SitelinksSetInput) -> Dict[str, Any]:
    if isinstance(item, SitelinksSet):
        return item.to_new_payload()
    return dict(item)


def _callout_new_body(item: CalloutInput) -> Dict[str, Any]:
    if isinstance(item, Callout):
        return item.to_new_payload()
    return dict(item)


__all__ = [
    "AdExtensionService",
    "SitelinksSetInput",
    "CalloutInput",
    "Sitelink",
    "SitelinksSet",
    "Callout",
]
