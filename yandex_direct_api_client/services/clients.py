"""Сервис данных клиента Директа (`clients`) и проверка лимитов (F-1.3).

Официальный справочник:
https://yandex.ru/dev/direct/doc/ru/clients/clients.html

Метод `clients/get` возвращает параметры клиента, включая `Restrictions` —
фактические лимиты количества сущностей. Проверять их полезно перед
E2E-запуском: дешевле узнать о нехватке лимита заранее, чем получить
частично созданную кампанию.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .._transport import Transport
from ..models._helpers import to_bool, to_int, to_optional_int

#: Имя лимита на общее число кампаний клиента.
LIMIT_CAMPAIGNS_TOTAL = "CAMPAIGNS_TOTAL_PER_CLIENT"

#: Имя лимита на число неархивированных кампаний клиента.
LIMIT_CAMPAIGNS_UNARCHIVED = "CAMPAIGNS_UNARCHIVED_PER_CLIENT"


@dataclass
class ClientInfo:
    """Параметры клиента из `clients/get`."""

    id: int
    login: Optional[str] = None
    name: Optional[str] = None
    currency: Optional[str] = None
    time_zone: Optional[str] = None
    is_agency: bool = False
    manager: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ClientInfo":
        """Разобрать ответ `clients/get`.

        :param d: JSON-тело клиента.
        :return: типизированная модель клиента.
        """
        return cls(
            id=to_int(d.get("Id")),
            login=d.get("Login"),
            name=d.get("Name"),
            currency=d.get("Currency"),
            time_zone=d.get("TimeZone"),
            is_agency=to_bool(d.get("Agency")),
            manager=d.get("ManagerLogin") or d.get("Manager"),
            raw=d,
        )

    @property
    def restrictions(self) -> Dict[str, int]:
        """Лимиты клиента (`Restrictions`) в виде словаря имя → значение."""
        raw = self.raw.get("Restrictions")
        if not isinstance(raw, dict):
            return {}
        result: Dict[str, int] = {}
        for key, value in raw.items():
            parsed = to_optional_int(value)
            if parsed is not None:
                result[str(key)] = parsed
        return result

    def restriction(self, name: str) -> Optional[int]:
        """Значение одного лимита.

        :param name: имя лимита (например `CAMPAIGNS_TOTAL_PER_CLIENT`).
        :return: значение лимита либо None, если лимит не задан.
        """
        return self.restrictions.get(name)

    def can_create_campaign(self, count: int = 1) -> bool:
        """Проверить, позволяет ли лимит клиента создать `count` кампаний.

        Учитываются оба лимита: на общее число кампаний и на число
        неархивированных. Отсутствие лимита в ответе считается «без
        ограничения».

        :param count: сколько кампаний планируется создать.
        :return: True, если создание укладывается в лимиты.
        """
        if count < 0:
            raise ValueError("count не может быть отрицательным")
        for name in (LIMIT_CAMPAIGNS_TOTAL, LIMIT_CAMPAIGNS_UNARCHIVED):
            limit = self.restriction(name)
            if limit is not None and count > limit:
                return False
        return True


class ClientsService:
    """Чтение параметров клиента и проверка лимитов."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def get(self, fields: Optional[List[str]] = None) -> ClientInfo:
        """Параметры текущего клиента (`clients/get`).

        :param fields: запрашиваемые поля; по умолчанию запрашивается
            `Restrictions` вместе с основными параметрами.
        :return: типизированная модель клиента с лимитами.
        """
        field_names = list(fields) if fields else [
            "Id",
            "Login",
            "Name",
            "Currency",
            "TimeZone",
            "Agency",
            "Restrictions",
        ]
        payload: Dict[str, Any] = {
            "method": "get",
            "params": {"FieldNames": field_names},
        }
        result = self._transport.post_result("clients", payload)
        return ClientInfo.from_dict(result)


__all__ = [
    "LIMIT_CAMPAIGNS_TOTAL",
    "LIMIT_CAMPAIGNS_UNARCHIVED",
    "ClientInfo",
    "ClientsService",
]
