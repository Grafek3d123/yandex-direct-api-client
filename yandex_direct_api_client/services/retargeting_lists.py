"""Сервис ретаргетинг-листов (RetargetingLists).

Справочник:
https://yandex.com/dev/direct/doc/en/retargetinglists/retargetinglists.md
Методы API: add, update, delete, get.

Зачем сервис в слое таргетинга: демография, поведение и пользовательские
интересы в Direct API **не** являются полями `audiencetargets`. Они задаются
сегментами внутри правил ретаргетинг-листа типа `AUDIENCE`. Тип сегмента
задаётся при создании и не меняется (docs: objects/retargeting-list).

Ограничения документации, которые проверяются локально:

- не более 2000 ретаргетинг-листов на аккаунт;
- не более 1000 объектов в одном вызове add/update/delete;
- список типа `RETARGETING` — 1..50 правил, в правиле 1..250 аргументов;
- для сегментов по демографии/поведению допустим только оператор `ANY`, и
  нельзя выбрать все сегменты характеристики сразу;
- `MembershipLifeSpan` (срок жизни в днях) — от 1 до 540.
"""
from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Union,
    overload,
)

from .._transport import Transport
from ..constants import (
    RETARGETING_LIST_TYPE_AUDIENCE,
    RETARGETING_LIST_TYPE_RETARGETING,
    RETARGETING_RULE_ANY,
    RETARGETING_RULE_NONE,
)
from ..exceptions import ValidationError
from ..limits import MUTATE_MAX
from ..models.batch import BatchResult
from ..models.targeting import RetargetingList
from ..validation import Validator
from ._base import (
    OnItemError,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
    run_batches,
)

#: Поля `retargetinglists/get` по умолчанию.
_DEFAULT_FIELDS = [
    "Id",
    "Name",
    "Description",
    "Type",
    "Rules",
    "IsAvailable",
    "Scope",
    "AvailableForTargetsInAdGroupTypes",
]

#: Лимит сегментов на аккаунт (docs: objects/retargeting-list).
RETARGETING_LISTS_TOTAL_MAX = 2000

RetargetingListInput = Union[RetargetingList, Mapping[str, Any]]


class RetargetingListService:
    """Создание и изменение сегментов ретаргетинга."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("retargeting_lists", method_name, self._readonly)

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    def get(
        self,
        ids: Optional[Sequence[int]] = None,
        *,
        types: Optional[Sequence[str]] = None,
        page_limit: Optional[int] = None,
    ) -> List[RetargetingList]:
        """Получить сегменты ретаргетинга с авто-пагинацией.

        :param ids: фильтр по ID сегментов; None — все сегменты аккаунта.
        :param types: фильтр по типу: `RETARGETING` или `AUDIENCE`.
        :param page_limit: размер страницы (по умолчанию максимум API).
        :return: список сегментов.
        :raises ValidationError: неизвестный тип сегмента или некорректные ID.
        """
        criteria: Dict[str, Any] = {}
        if ids:
            self._validator().ids(ids, field="SelectionCriteria.Ids")
            criteria["Ids"] = [int(x) for x in ids]
        if types:
            self._validator().one_of(
                list(types)[0] if len(list(types)) == 1 else None,
                (RETARGETING_LIST_TYPE_RETARGETING, RETARGETING_LIST_TYPE_AUDIENCE),
                field="SelectionCriteria.Types",
            )
            criteria["Types"] = [str(x) for x in types]
        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": list(_DEFAULT_FIELDS),
            },
        }
        if page_limit is not None:
            raw_list = fetch_all_pages(
                self._transport, "retargetinglists", payload, page_limit=page_limit
            )
        else:
            raw_list = fetch_all_pages(self._transport, "retargetinglists", payload)
        return [RetargetingList.from_dict(item) for item in raw_list]

    def list_for_group_type(
        self, ad_group_type: str, *, types: Optional[Sequence[str]] = None
    ) -> List[RetargetingList]:
        """Сегменты, применимые к типу группы объявлений.

        У каждого сегмента есть поле `AvailableForTargetsInAdGroupTypes` —
        документация отдаёт его именно для этой проверки, поэтому клиент
        не берёт допустимость из своей матрицы, когда сервер её уже знает.

        :param ad_group_type: тип группы из `adgroups/get`.
        :param types: дополнительный фильтр по типу сегмента.
        :return: список применимых сегментов.
        """
        segments = self.get(types=types)
        return [
            segment
            for segment in segments
            if not segment.available_for_ad_group_types
            or ad_group_type in segment.available_for_ad_group_types
        ]

    @overload
    def create(
        self,
        lists: Sequence[RetargetingListInput],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def create(
        self,
        lists: Sequence[RetargetingListInput],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def create(
        self,
        lists: Sequence[RetargetingListInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Создать сегменты ретаргетинга (`retargetinglists/add`).

        :param lists: типизированные модели или тела `RetargetingListAddItem`.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов `AddResults` (или `BatchResult`).
        :raises ValidationError: нарушены лимиты правил отбора.
        """
        self._ensure_writable("create")
        body_list = [_add_body(x) for x in lists]
        return run_batches(
            self._transport,
            "retargetinglists",
            method="add",
            params_key="RetargetingLists",
            items=body_list,
            on_item_error=on_item_error,
            action="создания сегмента ретаргетинга",
            result_key="AddResults",
            chunk_size=MUTATE_MAX,
        )

    @overload
    def update(
        self,
        lists: Sequence[RetargetingListInput],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def update(
        self,
        lists: Sequence[RetargetingListInput],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def update(
        self,
        lists: Sequence[RetargetingListInput],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Изменить сегменты ретаргетинга (`retargetinglists/update`).

        Тип сегмента (`Type`) изменить нельзя — он передаётся только при создании.

        :param lists: модели с заполненным `id` либо тела с `Id`.
        :param confirm: явное подтверждение изменения.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов `UpdateResults` (или `BatchResult`).
        :raises ValidationError: не задан `Id` у элемента.
        """
        self._ensure_writable("update")
        ensure_confirmed("retargeting_lists.update", confirm)
        body_list = [_update_body(x) for x in lists]
        return run_batches(
            self._transport,
            "retargetinglists",
            method="update",
            params_key="RetargetingLists",
            items=body_list,
            on_item_error=on_item_error,
            action="изменения сегмента ретаргетинга",
            result_key="UpdateResults",
            chunk_size=MUTATE_MAX,
        )

    @overload
    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Удалить сегменты ретаргетинга (`retargetinglists/delete`).

        :param ids: список ID сегментов.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список элементов `DeleteResults` (или `BatchResult`).
        """
        self._ensure_writable("delete")
        ensure_confirmed("retargeting_lists.delete", confirm)
        id_list = list(ids)
        if not id_list:
            return [] if on_item_error == "raise" else BatchResult()
        self._validator().ids(id_list, field="SelectionCriteria.Ids")
        return run_batches(
            self._transport,
            "retargetinglists",
            method="delete",
            params_key="SelectionCriteria",
            items=id_list,
            on_item_error=on_item_error,
            action="удаления сегмента ретаргетинга",
            result_key="DeleteResults",
            chunk_size=MUTATE_MAX,
            wrap_id=True,
        )

    def create_audience_segment(
        self,
        name: str,
        external_ids: Sequence[int],
        *,
        operator: str = RETARGETING_RULE_ANY,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Собрать (но не создать) сегмент типа `AUDIENCE` из сегментов.

        Хелпер для типичного случая «демография/интересы → один сегмент»:
        собирает правило с одним правилом отбора и оператором (по умолчанию
        `ANY` — для демографии документация разрешает только его).

        :param name: имя сегмента.
        :param external_ids: ID сегментов из `AudienceDemographicProfiles`
            или `AudienceInterests`.
        :param operator: `ANY` (по умолчанию) или `NONE`.
        :param description: текстовая заметка.
        :return: готовое тело `RetargetingListAddItem`.
        :raises ValidationError: пустой список сегментов или недопустимый
            оператор для типа `AUDIENCE`.
        """
        if not external_ids:
            raise ValidationError(
                "Создание сегмента AUDIENCE: передайте хотя бы один ExternalId"
            )
        if operator not in (RETARGETING_RULE_ANY, RETARGETING_RULE_NONE):
            raise ValidationError(
                "Для сегментов по демографии, поведению и интересам "
                f"допустимы только операторы ANY и NONE, получено {operator!r}"
            )
        segment = RetargetingList(
            name=name,
            type=RETARGETING_LIST_TYPE_AUDIENCE,
            rules=[
                {
                    "Arguments": [{"ExternalId": int(x)} for x in external_ids],
                    "Operator": operator,
                }
            ],
            description=description,
        )
        return segment.to_add_payload()


def _add_body(item: RetargetingListInput) -> Dict[str, Any]:
    """Привести элемент к телу `retargetinglists/add`.

    :param item: модель или готовый словарь.
    :return: словарь для отправки.
    """
    if isinstance(item, RetargetingList):
        return item.to_add_payload()
    return dict(item)


def _update_body(item: RetargetingListInput) -> Dict[str, Any]:
    """Привести элемент к телу `retargetinglists/update`.

    :param item: модель с `id` или словарь с `Id`.
    :return: словарь для отправки.
    :raises ValidationError: у модели не заполнен `id`.
    """
    if isinstance(item, RetargetingList):
        return item.to_update_payload()
    body = dict(item)
    if not body.get("Id"):
        raise ValidationError("retargetinglists/update: у элемента нет Id")
    return body


__all__ = [
    "RETARGETING_LISTS_TOTAL_MAX",
    "RetargetingListInput",
    "RetargetingListService",
]
