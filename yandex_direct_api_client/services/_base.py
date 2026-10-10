"""Базовые хелперы для сервисов (пагинация, чанкинг, confirm, guard'ы)."""
from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Union

from .._transport import Transport
from ..exceptions import KIND_VALIDATION, ApiError, ValidationError
from ..limits import GET_IDS_MAX, GET_PAGE_MAX, MUTATE_MAX
from ..models.batch import BatchResult, ItemFailure

# Лимиты API вынесены в `yandex_direct_api_client.limits`; имена ниже
# сохранены для обратной совместимости внутренних импортов.
MAX_GET_IDS = GET_IDS_MAX
MAX_MUTATE_IDS = MUTATE_MAX
MAX_PAGE = GET_PAGE_MAX

#: Режим обработки ошибок элементов batch-операции:
#: ``raise`` — бросить `ApiError` на первой ошибке (поведение по умолчанию),
#: ``collect`` — вернуть `BatchResult` с успешными и неуспешными элементами.
OnItemError = Literal["raise", "collect"]


def chunked(seq: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    """Разбить последовательность на чанки заданного размера."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def ensure_confirmed(method_name: str, confirm: bool) -> None:
    """Проверить, что опасная операция явно подтверждена.

    :param method_name: имя метода для сообщения об ошибке.
    :param confirm: значение флага подтверждения от вызывающего кода.
    :raises ValidationError: если confirm=False.
    """
    if not confirm:
        raise ValidationError(
            f"Метод {method_name} требует явного подтверждения: "
            f"передайте confirm=True"
        )


def ensure_writable(prefix: str, method_name: str, readonly: bool) -> None:
    """Проверить, что mutating-метод разрешён (не readonly-режим).

    :param prefix: имя неймспейса (например, "ads").
    :param method_name: имя метода для сообщения об ошибке.
    :param readonly: флаг readonly-режима клиента.
    :raises ValidationError: если readonly=True.
    """
    if readonly:
        raise ValidationError(
            f"Метод {prefix}.{method_name} запрещён в readonly-режиме"
        )


def _failure(item: Dict[str, Any], request_id: Optional[str]) -> Optional[ItemFailure]:
    """Собрать `ItemFailure` из элемента результата (None, если ошибок нет)."""
    errors = item.get("Errors") or []
    if not errors:
        return None
    first = errors[0] or {}
    return ItemFailure(
        message=first.get("Message") or first.get("Code") or "Ошибка элемента",
        code=first.get("Code"),
        object_id=item.get("Id"),
        request_id=request_id,
        details=tuple(errors),
    )


def item_failure(
    item: Dict[str, Any], request_id: Optional[str] = None
) -> Optional[ItemFailure]:
    """Собрать `ItemFailure` из элемента результата batch-операции.

    Обёртка над приватным `_failure` для сервисов, которым нужно разобрать
    одиночный результат (например, `adimages/add` — одна сущность за вызов).

    :param item: элемент `*Results` из ответа API.
    :param request_id: `X-Request-Id` ответа для поля `ItemFailure.request_id`.
    :return: `ItemFailure` либо None, если ошибок в элементе нет.
    """
    return _failure(item, request_id)


def check_item_errors(item: Dict[str, Any], action: str) -> None:
    """Проверить элемент AddResults/UpdateResults/DeleteResults на Errors.

    Используется в режиме `on_item_error="raise"`. Для сбора частичных
    результатов используйте `ResultCollector`.

    :param item: элемент результата операции.
    :param action: описание действия для сообщения об ошибке.
    :raises ApiError: если в элементе есть Errors.
    """
    failure = _failure(item, None)
    if failure is not None:
        raise ApiError(
            f"Ошибка {action}: {failure.message}",
            details=failure.details,
            object_id=failure.object_id,
            kind=KIND_VALIDATION,
            status_code=200,
            response_body=item,
        )


class ResultCollector:
    """Накопитель элементов batch-операции с учётом режима `on_item_error`.

    В режиме ``raise`` первая ошибка элемента немедленно превращается в
    `ApiError` (поведение предыдущих версий). В режиме ``collect`` ошибки
    складываются в `BatchResult.failed`, а успешные элементы не теряются.
    """

    def __init__(
        self,
        on_item_error: OnItemError = "raise",
        *,
        request_id: Optional[str] = None,
    ) -> None:
        self._on_item_error: OnItemError = on_item_error
        self._request_id = request_id
        self._succeeded: List[Dict[str, Any]] = []
        self._failed: List[ItemFailure] = []

    def set_request_id(self, request_id: Optional[str]) -> None:
        """Запомнить `X-Request-Id` последнего ответа для `ItemFailure`."""
        self._request_id = request_id

    def add(self, items: Sequence[Dict[str, Any]], action: str) -> None:
        """Разобрать элементы одного ответа API.

        :param items: элементы `*Results` из тела ответа.
        :param action: описание действия для сообщения об ошибке.
        :raises ApiError: в режиме ``raise``, если элемент содержит Errors.
        """
        for item in items:
            failure = _failure(item, self._request_id)
            if failure is None:
                self._succeeded.append(item)
                continue
            if self._on_item_error == "raise":
                raise ApiError(
                    f"Ошибка {action}: {failure.message}",
                    details=failure.details,
                    object_id=failure.object_id,
                    kind=KIND_VALIDATION,
                    status_code=200,
                    response_body=item,
                )
            self._failed.append(failure)

    def finish(self) -> Union[List[Dict[str, Any]], BatchResult]:
        """Результат накопленных элементов в соответствии с режимом."""
        if self._on_item_error == "collect":
            return BatchResult(
                succeeded=list(self._succeeded), failed=list(self._failed)
            )
        return list(self._succeeded)


def empty_result(on_item_error: OnItemError) -> Union[List[Dict[str, Any]], BatchResult]:
    """Пустой результат batch-операции, согласованный с режимом ошибок."""
    return BatchResult() if on_item_error == "collect" else []


def run_batches(
    transport: Transport,
    service: str,
    *,
    method: str,
    params_key: str,
    items: Sequence[Any],
    on_item_error: OnItemError = "raise",
    action: str,
    result_key: str,
    chunk_size: int = MUTATE_MAX,
    wrap_id: bool = False,
) -> Union[List[Dict[str, Any]], BatchResult]:
    """Выполнить batch-операцию с авто-чанкингом и учётом ошибок элементов.

    :param transport: транспорт для HTTP-запросов.
    :param service: имя API-сервиса (ads, adgroups, criteria, ...).
    :param method: имя метода API (add, update, delete, suspend, ...).
    :param params_key: ключ в params, под который кладутся элементы
        (``AdGroups``) либо ``SelectionCriteria`` для операций по ID.
    :param items: элементы тела (тела объектов или ID).
    :param on_item_error: `raise` или `collect`.
    :param action: описание действия для сообщений об ошибках.
    :param result_key: ключ списка результатов в ответе API.
    :param chunk_size: размер чанка (лимит метода).
    :param wrap_id: True — элементы это ID, оборачивать в
        ``SelectionCriteria.Ids``; False — элементы кладутся как есть.
    :return: список элементов результата (или `BatchResult`).
    """
    if not items:
        return empty_result(on_item_error)
    collector = ResultCollector(on_item_error)
    for chunk in chunked(list(items), chunk_size):
        if wrap_id:
            params: Dict[str, Any] = {"SelectionCriteria": {"Ids": list(chunk)}}
        else:
            params = {params_key: list(chunk)}
        result = transport.post_result(
            service, {"method": method, "params": params}
        )
        collector.set_request_id(transport.last_request_id)
        collector.add(result.get(result_key) or [], action)
    return collector.finish()


def fetch_all_pages(
    transport: Transport,
    service: str,
    payload_base: Dict[str, Any],
    *,
    page_limit: int = GET_PAGE_MAX,
) -> List[Dict[str, Any]]:
    """Загрузить все страницы get-запроса с пагинацией через LimitedBy.

    :param transport: транспорт для HTTP-запросов.
    :param service: имя API-сервиса.
    :param payload_base: полный payload (method=get, params=...),
        без поля Page — будет добавлено автоматически.
    :param page_limit: размер страницы (Limit), по умолчанию 10000.
    :return: объединённый список всех объектов из всех страниц.
    """
    results: List[Dict[str, Any]] = []
    offset: Optional[int] = None
    while True:
        payload = copy.deepcopy(payload_base)
        params = payload.setdefault("params", {})
        page: Dict[str, Any] = {"Limit": page_limit}
        if offset is not None:
            page["Offset"] = offset
        params["Page"] = page

        result = transport.post_result(service, payload)
        # Найти список объектов в результате (первый ключ-список)
        items: List[Dict[str, Any]] = []
        for _key, val in result.items():
            if isinstance(val, list):
                items = val
                break

        results.extend(items)

        limited_by = result.get("LimitedBy")
        if limited_by is None:
            break
        offset = int(limited_by)

    return results


__all__ = [
    "MAX_GET_IDS",
    "MAX_MUTATE_IDS",
    "MAX_PAGE",
    "OnItemError",
    "ResultCollector",
    "check_item_errors",
    "chunked",
    "empty_result",
    "ensure_confirmed",
    "ensure_writable",
    "fetch_all_pages",
    "item_failure",
    "run_batches",
]
