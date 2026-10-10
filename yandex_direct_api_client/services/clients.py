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
        """Разобрать один элемент ответа `clients/get`.

        Фактический контракт API (проверен живым запросом): секция
        ``ClientInfo`` приходит строкой с отображаемым именем клиента, а не
        объектом. Остальные поля (``Id``, ``Login``, ``Currency`` и т.д.)
        API не возвращает — они остаются ``None`` и сохранены для плоских
        ответов и моков.

        :param d: JSON-объект одного клиента.
        :return: типизированная модель клиента.
        """
        info = d.get("ClientInfo")
        name = info if isinstance(info, str) else d.get("Name")
        return cls(
            id=to_int(d.get("Id")),
            login=d.get("Login"),
            name=name,
            currency=d.get("Currency"),
            time_zone=d.get("TimeZone"),
            is_agency=to_bool(d.get("Agency")),
            manager=d.get("ManagerLogin") or d.get("Manager"),
            raw=d,
        )

    @property
    def restrictions(self) -> Dict[str, int]:
        """Лимиты клиента (`Restrictions`) в виде словаря имя → значение.

        API отдаёт ``Restrictions`` списком объектов ``{Element, Value}``;
        словарная форма поддержана как escape-hatch для моков и старых
        ответов.
        """
        raw = self.raw.get("Restrictions")
        pairs: List[Any]
        if isinstance(raw, list):
            pairs = [
                (item.get("Element"), item.get("Value"))
                for item in raw
                if isinstance(item, dict)
            ]
        elif isinstance(raw, dict):
            pairs = list(raw.items())
        else:
            return {}
        result: Dict[str, int] = {}
        for key, value in pairs:
            parsed = to_optional_int(value)
            if key is not None and parsed is not None:
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

        API принимает строго два имени полей — `ClientInfo` и `Restrictions`
        (проверено живым запросом); другие значения отклоняются как
        `InvalidRequest`. Ответ — список `Clients`, берётся первый элемент.

        :param fields: запрашиваемые поля; по умолчанию оба доступных.
        :return: типизированная модель клиента с лимитами.
        """
        field_names = list(fields) if fields else ["ClientInfo", "Restrictions"]
        payload: Dict[str, Any] = {
            "method": "get",
            "params": {"FieldNames": field_names},
        }
        result = self._transport.post_result("clients", payload)
        clients = result.get("Clients")
        if isinstance(clients, list) and clients:
            first = clients[0]
            if isinstance(first, dict):
                return ClientInfo.from_dict(first)
        return ClientInfo.from_dict(result)


__all__ = [
    "LIMIT_CAMPAIGNS_TOTAL",
    "LIMIT_CAMPAIGNS_UNARCHIVED",
    "ClientInfo",
    "ClientsService",
]
