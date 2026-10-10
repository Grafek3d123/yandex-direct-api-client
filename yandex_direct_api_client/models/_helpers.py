"""Хелперы конвертации из JSON-значений в Python-типы."""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional


def to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.replace(",", ".").strip()
        if value in {"", "--"}:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def to_date(value: Any) -> Optional[_dt.date]:
    """Parse 'YYYY-MM-DD' date string. Empty/invalid -> None."""
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def to_optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_bool(value: Any, default: bool = False) -> bool:
    """Привести значение API к bool (в JSON встречаются `0`/`1` и `true`)."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0", ""}:
        return False
    return default
