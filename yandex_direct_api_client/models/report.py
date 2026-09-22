"""Типизированные модели для Reports API (параметры и результаты)."""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ._helpers import to_date, to_float, to_int

# Операторы фильтра Reports API (см. docs: Reports API / spec / FilterItem)
FILTER_OPERATORS = frozenset(
    {
        "EQUALS",
        "NOT_EQUALS",
        "IN",
        "NOT_IN",
        "LESS_THAN",
        "GREATER_THAN",
        "STARTS_WITH",
        "STARTS_WITH_IGNORE_CASE",
    }
)


@dataclass
class ReportFilter:
    """Фильтр отчёта (FilterItem): поле, оператор, значения."""

    field_name: str
    operator: str
    values: Sequence[str]

    def __post_init__(self) -> None:
        if self.operator not in FILTER_OPERATORS:
            raise ValueError(
                f"Недопустимый оператор фильтра: {self.operator!r}; "
                f"допустимые: {sorted(FILTER_OPERATORS)}"
            )

    def to_payload(self) -> Dict[str, Any]:
        """Тело FilterItem для запроса build."""
        return {
            "Field": self.field_name,
            "Operator": self.operator,
            "Values": [str(v) for v in self.values],
        }


@dataclass
class ReportOrder:
    """Сортировка строк отчёта (OrderBy)."""

    field_name: str
    ascending: bool = True

    def to_payload(self) -> Dict[str, Any]:
        """Тело OrderBy для запроса build."""
        payload: Dict[str, Any] = {"Field": self.field_name}
        payload["SortOrder"] = "ASCENDING" if self.ascending else "DESCENDING"
        return payload


@dataclass
class ReportRow:
    """Строка отчёта: значения полей по имени колонки.

    Значения хранятся как строки (так отдаёт TSV), доступ с конвертацией —
    через `as_int` / `as_float` / `as_money` / `as_date`.
    """

    fields: Dict[str, str] = field(default_factory=dict)

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Сырое строковое значение поля (или default)."""
        return self.fields.get(name, default)

    def as_int(self, name: str, default: int = 0) -> int:
        """Целочисленное значение поля."""
        raw = self.fields.get(name)
        return to_int(raw, default) if raw is not None else default

    def as_float(self, name: str, default: float = 0.0) -> float:
        """Числовое значение поля (float)."""
        raw = self.fields.get(name)
        return to_float(raw, default) if raw is not None else default

    def as_money(self, name: str) -> float:
        """Денежное значение: Reports API отдаёт микросуммы (x 1 000 000)."""
        return self.as_float(name) / 1_000_000.0

    def as_date(self, name: str = "Date") -> Optional[_dt.date]:
        """Значение поля как дата (YYYY-MM-DD)."""
        return to_date(self.fields.get(name))

    def to_dict(self) -> Dict[str, str]:
        """Копия полей строки как dict (для JSON/передачи дальше)."""
        return dict(self.fields)


@dataclass
class ReportResult:
    """Готовый отчёт: колонки + строки + исходный TSV."""

    columns: List[str] = field(default_factory=list)
    rows: List[ReportRow] = field(default_factory=list)
    raw_text: str = ""

    def to_dicts(self) -> List[Dict[str, str]]:
        """Все строки как list[dict] (удобно для итерации и сериализации)."""
        return [row.to_dict() for row in self.rows]

    def to_csv(self) -> str:
        """CSV-представление (заголовок + строки, запятая-экранирование)."""
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(self.columns)
        for row in self.rows:
            writer.writerow([row.fields.get(c, "") for c in self.columns])
        return buf.getvalue()

    def to_json(self, **kwargs: Any) -> str:
        """JSON-представление (list of objects)."""
        return json.dumps(self.to_dicts(), ensure_ascii=False, **kwargs)

    def to_dataframe(self) -> Any:
        """pandas.DataFrame из отчёта (pandas — опциональная зависимость).

        :raises ImportError: если pandas не установлен.
        """
        try:
            import pandas as pd  # type: ignore[import-untyped]
        except ImportError as e:
            raise ImportError(
                "pandas не установлен: pip install pandas "
                "(опциональная зависимость, не входит в базовые)"
            ) from e
        return pd.DataFrame(self.to_dicts(), columns=self.columns)


__all__ = [
    "FILTER_OPERATORS",
    "ReportFilter",
    "ReportOrder",
    "ReportResult",
    "ReportRow",
]
