"""Результаты batch-операций: успешные элементы и частичные ошибки.

По умолчанию клиент бросает `ApiError` на первой ошибке элемента (режим
`on_item_error="raise"`). В режиме `on_item_error="collect"` ошибка элемента не
теряет успешные элементы того же ответа: вызывающий код получает `BatchResult`
с двумя списками и решает сам, что делать с частичным результатом.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence


@dataclass(frozen=True)
class ItemFailure:
    """Ошибка одного элемента batch-операции.

    :param message: текст ошибки из `Errors[0].Message`.
    :param code: код ошибки Яндекса (`Errors[0].Code`), если есть.
    :param object_id: ID объекта, если API его вернул в элементе.
    :param request_id: `X-Request-Id` соответствующего запроса.
    :param details: полный список `Errors` элемента.
    """

    message: str
    code: Optional[str] = None
    object_id: Optional[Any] = None
    request_id: Optional[str] = None
    details: Sequence[Any] = field(default_factory=tuple)

    def __str__(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"code={self.code}")
        if self.object_id is not None:
            parts.append(f"id={self.object_id}")
        return " | ".join(parts)


@dataclass(frozen=True)
class BatchResult:
    """Частичный результат batch-операции.

    :param succeeded: элементы, обработанные успешно.
    :param failed: элементы с ошибками (по одной на элемент).
    """

    succeeded: List[Dict[str, Any]] = field(default_factory=list)
    failed: List[ItemFailure] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.succeeded)

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        return iter(self.succeeded)

    def __bool__(self) -> bool:
        return bool(self.succeeded)

    @property
    def has_failures(self) -> bool:
        """Есть ли элементы с ошибками."""
        return bool(self.failed)

    def ids(self) -> List[Any]:
        """ID успешно обработанных объектов."""
        return [item.get("Id") for item in self.succeeded]


__all__ = ["BatchResult", "ItemFailure"]
