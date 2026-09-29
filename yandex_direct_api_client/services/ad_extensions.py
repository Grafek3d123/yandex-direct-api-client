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

from typing import Any, Dict, List, Mapping, Sequence, Union

from .._transport import Transport
from ..models.ad_extension import Callout, Sitelink, SitelinksSet
from ._base import (
    MAX_GET_IDS,
    MAX_MUTATE_IDS,
    check_item_errors,
    chunked,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
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

    # ---------------- быстрые ссылки (sitelinks) ----------------
    def list_sitelinks(self, *, page_limit: int = 10000) -> List[SitelinksSet]:
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
        results: List[SitelinksSet] = []
        for chunk in chunked(list(ids), MAX_GET_IDS):
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

    def create_sitelinks(
        self, sets: Sequence[SitelinksSetInput]
    ) -> List[Dict[str, Any]]:
        """Создать наборы быстрых ссылок (batch, до 200 за запрос).

        :param sets: типизированные модели SitelinksSet или тела
            SitelinksSetAddItem {Sitelinks: [...]}.
        :return: список элементов AddResults.
        """
        self._ensure_writable("create_sitelinks")
        body_list = [_sitelinks_new_body(x) for x in sets]
        if not body_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(body_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "add",
                "params": {"SitelinksSets": list(chunk)},
            }
            result = self._transport.post_result("sitelinks", payload)
            for item in result.get("AddResults") or []:
                check_item_errors(
                    item, f"создания набора быстрых ссылок id={item.get('Id')}"
                )
                results.append(item)
        return results

    def delete_sitelinks(
        self, ids: Sequence[int], *, confirm: bool = False
    ) -> List[Dict[str, Any]]:
        """Удалить наборы быстрых ссылок по ID (авто-чанкинг по 200).

        :param ids: список ID наборов.
        :param confirm: явное подтверждение необратимой операции удаления.
        :return: список элементов DeleteResults.
        """
        self._ensure_writable("delete_sitelinks")
        ensure_confirmed("ad_extensions.delete_sitelinks", confirm)
        return self._ids_action(
            "sitelinks",
            "delete",
            "DeleteResults",
            "удаления набора быстрых ссылок",
            ids,
        )

    # ---------------- уточнения (adextensions, CALLOUT) ----------------
    def list_callouts(self, *, page_limit: int = 10000) -> List[Callout]:
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
        results: List[Callout] = []
        for chunk in chunked(list(ids), MAX_GET_IDS):
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

    def create_callouts(
        self, callouts: Sequence[CalloutInput]
    ) -> List[Dict[str, Any]]:
        """Создать уточнения (batch, до 200 за запрос).

        :param callouts: типизированные модели Callout или тела
            AdExtensionAddItem {Callout: {CalloutText}}.
        :return: список элементов AddResults.
        """
        self._ensure_writable("create_callouts")
        body_list = [_callout_new_body(x) for x in callouts]
        if not body_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(body_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": "add",
                "params": {"AdExtensions": list(chunk)},
            }
            result = self._transport.post_result("adextensions", payload)
            for item in result.get("AddResults") or []:
                check_item_errors(
                    item, f"создания уточнения id={item.get('Id')}"
                )
                results.append(item)
        return results

    def delete_callouts(
        self, ids: Sequence[int], *, confirm: bool = False
    ) -> List[Dict[str, Any]]:
        """Удалить уточнения по ID (авто-чанкинг по 200).

        :param ids: список ID уточнений.
        :param confirm: явное подтверждение необратимой операции удаления.
        :return: список элементов DeleteResults.
        """
        self._ensure_writable("delete_callouts")
        ensure_confirmed("ad_extensions.delete_callouts", confirm)
        return self._ids_action(
            "adextensions",
            "delete",
            "DeleteResults",
            "удаления уточнения",
            ids,
        )

    # ---------------- общий хелпер ----------------
    def _ids_action(
        self,
        service: str,
        method_name: str,
        result_key: str,
        action_label: str,
        ids: Sequence[int],
    ) -> List[Dict[str, Any]]:
        """Общий batch-вызов delete по SelectionCriteria.Ids."""
        id_list = list(ids)
        if not id_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(id_list, MAX_MUTATE_IDS):
            payload: Dict[str, Any] = {
                "method": method_name,
                "params": {"SelectionCriteria": {"Ids": list(chunk)}},
            }
            result = self._transport.post_result(service, payload)
            for item in result.get(result_key) or []:
                check_item_errors(item, f"{action_label} id={item.get('Id')}")
                results.append(item)
        return results


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
