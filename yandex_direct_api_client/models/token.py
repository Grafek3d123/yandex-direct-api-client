"""Модель OAuth-токена."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ._helpers import to_int, to_str


@dataclass
class TokenResponse:
    """Ответ OAuth-эндпоинтов Яндекса (token / refresh)."""

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TokenResponse":
        return cls(
            access_token=to_str(d.get("access_token")),
            refresh_token=(
                to_str(d["refresh_token"]) if d.get("refresh_token") else None
            ),
            token_type=to_str(d.get("token_type"), default="bearer"),
            expires_in=(
                to_int(d["expires_in"]) if d.get("expires_in") is not None else None
            ),
        )


__all__ = ["TokenResponse"]
