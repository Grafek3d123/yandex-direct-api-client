"""Базовые хелперы для сервисов (пагинация, чанкинг, confirm)."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from .._transport import Transport
from ..exceptions import ValidationError

# API-лимиты (https://yandex.ru/dev/direct/doc/ref-v5/limits/)
MAX_GET_IDS = 1000  # SelectionCriteria.Ids для get-методов кампаний
MAX_MUTATE_IDS = 200  # add/update/delete


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


def fetch_all_pages(
    transport: Transport,
    service: str,
    payload_base: Dict[str, Any],
    *,
    page_limit: int = 10000,
) -> List[Dict[str, Any]]:
    """Загрузить все страницы get-запроса с пагинацией через LimitedBy.

    :param transport: транспорт для HTTP-запросов.
    :param service: имя API-сервиса.
    :param payload_base: полный payload (method=get, params=...),
        без поля Page — будет добавлено автоматически.
    :param page_limit: размер страницы (Limit), по умолчанию 10000.
    :return: объединённый список всех объектов из всех страниц.
    """
    import copy

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
    "chunked",
    "fetch_all_pages",
]
