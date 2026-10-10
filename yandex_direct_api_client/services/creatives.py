"""Сервис креативов `creatives` (F-2A.3).

Официальный справочник:
https://yandex.ru/dev/direct/doc/ru/creatives/creatives.md

Зачем он нужен именно здесь. Медийное объявление РСЯ создаётся как
`CpmBannerAdBuilderAd` со ссылкой на **готовый креатив**
(`Creative.CreativeId`). Заголовок, текст и картинки такого объявления
задаются в конструкторе креативов (веб-интерфейс), а через API доступно
только чтение: `creatives/add` умеет создавать лишь креативы видеодополнений.

Сервис только читающий, поэтому `readonly=True` на него не влияет.

- `get` — чтение креативов по `Ids` и/или `Types` с авто-пагинацией;
- `list` — все креативы аккаунта;
- `image_creative_ids` — хэш быстрого поиска `CreativeId` для РСЯ.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .._transport import Transport
from ..exceptions import ValidationError
from ..limits import CREATIVES_GET_MAX, GET_PAGE_MAX
from ..validation import Validator
from ._base import chunked, fetch_all_pages

#: Типы креативов (docs: CreativeTypeEnum).
CREATIVE_TYPES = (
    "IMAGE_CREATIVE",
    "HTML5_CREATIVE",
    "VIDEO_EXTENSION_CREATIVE",
    "CPC_VIDEO_CREATIVE",
    "CPM_VIDEO_CREATIVE",
    "SMART_CREATIVE",
)

#: Поля ответа `creatives/get` по умолчанию.
DEFAULT_FIELD_NAMES = (
    "Id",
    "Type",
    "Name",
    "PreviewUrl",
    "Width",
    "Height",
    "ThumbnailUrl",
    "Associated",
    "IsAdaptive",
)


class CreativesService:
    """Чтение креативов объявлений (`creatives/get`)."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def get(
        self,
        *,
        ids: Optional[Sequence[int]] = None,
        types: Optional[Sequence[str]] = None,
        field_names: Optional[Sequence[str]] = None,
        page_limit: int = GET_PAGE_MAX,
    ) -> List[Dict[str, Any]]:
        """Получить креативы аккаунта (`creatives/get`).

        :param ids: ID креативов (до 10 000 за вызов, чанкится автоматически).
        :param types: фильтр по типам креативов (см. `CREATIVE_TYPES`).
        :param field_names: поля ответа вместо значений по умолчанию.
        :param page_limit: размер страницы.
        :return: список сырых записей креативов.
        :raises ValidationError: некорректные ID или типы.
        """
        validator = Validator(self._transport.validate_enabled)
        if types is not None:
            for item in types:
                validator.one_of(item, CREATIVE_TYPES, field="Types")
        fields = list(field_names or DEFAULT_FIELD_NAMES)
        id_list = [int(x) for x in ids] if ids else []
        if id_list:
            validator.ids(id_list, field="SelectionCriteria.Ids")
            results: List[Dict[str, Any]] = []
            for chunk in chunked(id_list, CREATIVES_GET_MAX):
                results.extend(
                    self._get_page(chunk, types, fields, page_limit=page_limit)
                )
            return results
        return self._get_page([], types, fields, page_limit=page_limit)

    def list(self, *, page_limit: int = GET_PAGE_MAX) -> List[Dict[str, Any]]:
        """Все креативы аккаунта с авто-пагинацией.

        :param page_limit: размер страницы.
        :return: список сырых записей креативов.
        """
        return self.get(page_limit=page_limit)

    def image_creative_ids(
        self, *, names: Optional[Sequence[str]] = None
    ) -> List[int]:
        """ID картинных креативов (`IMAGE_CREATIVE`) для объявлений РСЯ.

        :param names: если задано — вернуть ID только креативов с такими
            именами (точное совпадение).
        :return: список `CreativeId`.
        """
        wanted = set(names) if names else None
        ids: List[int] = []
        for item in self.get(types=["IMAGE_CREATIVE"]):
            if wanted is not None and item.get("Name") not in wanted:
                continue
            creative_id = item.get("Id")
            if isinstance(creative_id, int) and not isinstance(creative_id, bool):
                ids.append(creative_id)
            elif wanted is not None and creative_id is not None:
                raise ValidationError(
                    f"Creatives.get: неожиданный тип Id: {creative_id!r}"
                )
        return ids

    # ---------------- внутреннее ----------------
    def _get_page(
        self,
        ids: Sequence[int],
        types: Optional[Sequence[str]],
        field_names: Sequence[str],
        *,
        page_limit: int,
    ) -> List[Dict[str, Any]]:
        """Выполнить `creatives/get` с пагинацией.

        :param ids: отбор по ID (пустой список — все креативы).
        :param types: отбор по типам.
        :param field_names: поля ответа.
        :param page_limit: размер страницы.
        :return: список записей креативов.
        """
        criteria: Dict[str, Any] = {}
        if ids:
            criteria["Ids"] = list(ids)
        if types:
            criteria["Types"] = list(types)
        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": list(field_names),
            },
        }
        return fetch_all_pages(
            self._transport, "creatives", payload, page_limit=page_limit
        )


__all__ = ["CREATIVE_TYPES", "DEFAULT_FIELD_NAMES", "CreativesService"]
