"""Сервис изображений объявлений `adimages` (F-2A.3, D2).

Официальный справочник:
https://yandex.ru/dev/direct/doc/ru/adimages/adimages.html

Контракт сверен с документацией (снимок 30.09.2026):

- `adimages/add` принимает `AdImages[]` с полями `ImageData` (base64),
  `Name` (до 255 символов) и опциональным `Type`
  (`REGULAR`/`WIDE`/`FIXED_IMAGE`/`AUTO`);
- ответ содержит `AddResults[].AdImageHash` — именно этот хэш указывается
  в объявлении (`TextAd.AdImageHash`, `ResponsiveAd.AdImageHashes`);
- в сервисе есть только три метода: `add`, `get`, `delete`; отдельных
  `update`/`unbind`/`remove` не существует;
- `adimages/get` и `adimages/delete` отбирают изображения по
  `SelectionCriteria.AdImageHashes` (не более 10 000 за вызов).

Валидация до сети (F-0.7): имя, обязательное изображение, base64, лимиты
размера и допустимые форматы. Ошибки — `ValidationError` без HTTP-запроса.
"""
from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
from typing import (
    Any,
    BinaryIO,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Union,
    cast,
    overload,
)

from .._transport import Transport
from ..exceptions import ValidationError
from ..limits import ADIMAGES_GET_MAX, GET_PAGE_MAX
from ..models.batch import BatchResult
from ..validation import AD_IMAGE_NAME_MAX_LENGTH, Validator
from ._base import (
    OnItemError,
    ResultCollector,
    chunked,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
)

#: Предельный размер исходного файла изображения (10 МБ, справка adimages).
MAX_IMAGE_BYTES = 10 * 1024 * 1024

#: Допустимые расширения файлов изображения.
ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif")

#: Допустимые типы содержимого, которые принимает API.
ALLOWED_CONTENT_TYPES = ("image/jpeg", "image/png", "image/gif")

#: Типы изображения (docs: AdImageAddTypeEnum).
AD_IMAGE_TYPES = ("REGULAR", "WIDE", "FIXED_IMAGE", "AUTO")

#: Поля ответа `adimages/get` по умолчанию.
DEFAULT_FIELDS = (
    "AdImageHash",
    "Name",
    "Type",
    "Subtype",
    "Associated",
    "OriginalUrl",
    "PreviewUrl",
)


class AdImageService:
    """Операции над изображениями объявлений (`adimages`)."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("ad_images", method_name, self._readonly)

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    # ---------------- чтение ----------------
    def list(
        self,
        *,
        page_limit: int = GET_PAGE_MAX,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Список всех изображений аккаунта с авто-пагинацией.

        Отдельного метода «получить всё» в API нет: `adimages/get` с пустым
        `SelectionCriteria` возвращает все изображения постранично.

        :param page_limit: размер страницы.
        :param field_names: поля ответа вместо значений по умолчанию.
        :return: список сырых записей изображений.
        """
        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "SelectionCriteria": {},
                "FieldNames": list(field_names or DEFAULT_FIELDS),
            },
        }
        return fetch_all_pages(
            self._transport, "adimages", payload, page_limit=page_limit
        )

    def get(
        self,
        hashes: Sequence[str],
        *,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Получить изображения по хэшам (`adimages/get`).

        :param hashes: хэши изображений (из `AdImageHash`).
        :param field_names: поля ответа вместо значений по умолчанию.
        :return: список сырых записей изображений.
        :raises ValidationError: пустой или нестроковый хэш.
        """
        hash_list = self._validated_hashes(hashes)
        if not hash_list:
            return []
        results: List[Dict[str, Any]] = []
        for chunk in chunked(hash_list, ADIMAGES_GET_MAX):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"AdImageHashes": list(chunk)},
                    "FieldNames": list(field_names or DEFAULT_FIELDS),
                },
            }
            result = self._transport.post_result("adimages", payload)
            results.extend(result.get("AdImages") or [])
        return results

    # ---------------- создание ----------------
    @overload
    def add(
        self,
        name: str,
        image_base64: str,
        *,
        type_: Optional[str] = None,
        on_item_error: Literal["raise"] = ...,
    ) -> Dict[str, Any]: ...

    @overload
    def add(
        self,
        name: str,
        image_base64: str,
        *,
        type_: Optional[str] = None,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def add(
        self,
        name: str,
        image_base64: str,
        *,
        type_: Optional[str] = None,
        on_item_error: OnItemError = "raise",
    ) -> Union[Dict[str, Any], BatchResult]:
        """Загрузить изображение из base64-строки (`adimages/add`).

        :param name: имя изображения (1..255 символов).
        :param image_base64: содержимое изображения в base64.
        :param type_: тип изображения (`REGULAR`/`WIDE`/`FIXED_IMAGE`/`AUTO`);
            None — определить автоматически.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: элемент AddResults с `AdImageHash` (или `BatchResult`).
        :raises ValidationError: неверное имя, пустое или невалидное содержимое.
        """
        self._ensure_writable("add")
        self._validator().name(
            name, field="AdImage.Name", max_length=AD_IMAGE_NAME_MAX_LENGTH
        )
        if not image_base64.strip():
            raise ValidationError("image_base64 не может быть пустым")
        self._check_base64(image_base64)
        item: Dict[str, Any] = {"Name": name, "ImageData": image_base64}
        if type_ is not None:
            Validator(True).one_of(type_, AD_IMAGE_TYPES, field="AdImage.Type")
            item["Type"] = type_
        payload: Dict[str, Any] = {
            "method": "add",
            "params": {"AdImages": [item]},
        }
        result = self._transport.post_result("adimages", payload)
        collector = ResultCollector(
            on_item_error, request_id=self._transport.last_request_id
        )
        collector.add(result.get("AddResults") or [], "загрузки изображения")
        if on_item_error == "collect":
            return cast(BatchResult, collector.finish())
        finished = cast(List[Dict[str, Any]], collector.finish())
        return finished[0] if finished else {}

    def add_from_file(
        self,
        path: Union[str, "os.PathLike[str]"],
        *,
        name: Optional[str] = None,
        type_: Optional[str] = None,
        on_item_error: OnItemError = "raise",
    ) -> Union[Dict[str, Any], BatchResult]:
        """Загрузить изображение из файла на диске.

        Расширение файла проверяется по белому списку
        (`.jpg`, `.jpeg`, `.png`, `.gif`) — API вернёт ошибку на другом
        формате, а платить за round-trip не нужно.

        :param path: путь к файлу изображения.
        :param name: имя изображения; None — имя файла без расширения.
        :param type_: тип изображения (см. `add`).
        :param on_item_error: `raise` или `collect` (см. `add`).
        :return: элемент AddResults с `AdImageHash` (или `BatchResult`).
        :raises ValidationError: файл не найден, слишком большой или формат
            не поддерживается.
        """
        file_path = Path(path)
        if not file_path.is_file():
            raise ValidationError(f"Файл изображения не найден: {file_path}")
        suffix = file_path.suffix.lower()
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            allowed = ", ".join(ALLOWED_IMAGE_EXTENSIONS)
            raise ValidationError(
                f"Неподдерживаемый формат изображения {suffix!r}; допустимо: {allowed}"
            )
        size = file_path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise ValidationError(
                f"Файл изображения больше {MAX_IMAGE_BYTES // (1024 * 1024)} МБ "
                f"({size} байт)"
            )
        data = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return self.add(
            name or file_path.stem, data, type_=type_, on_item_error=on_item_error
        )

    def add_from_stream(
        self,
        stream: BinaryIO,
        name: str,
        *,
        type_: Optional[str] = None,
        on_item_error: OnItemError = "raise",
    ) -> Union[Dict[str, Any], BatchResult]:
        """Загрузить изображение из открытого бинарного потока.

        :param stream: поток с содержимым изображения.
        :param name: имя изображения.
        :param type_: тип изображения (см. `add`).
        :param on_item_error: `raise` или `collect` (см. `add`).
        :return: элемент AddResults с `AdImageHash` (или `BatchResult`).
        :raises ValidationError: поток пуст или слишком большой.
        """
        raw = stream.read()
        if not raw:
            raise ValidationError("Поток изображения пуст")
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValidationError(
                f"Изображение больше {MAX_IMAGE_BYTES // (1024 * 1024)} МБ "
                f"({len(raw)} байт)"
            )
        return self.add(
            name,
            base64.b64encode(raw).decode("ascii"),
            type_=type_,
            on_item_error=on_item_error,
        )

    # ---------------- удаление ----------------
    @overload
    def delete(
        self,
        hashes: Sequence[str],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def delete(
        self,
        hashes: Sequence[str],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def delete(
        self,
        hashes: Sequence[str],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Удалить изображения (`adimages/delete`).

        Операция необратима, поэтому требует `confirm=True`.

        :param hashes: хэши изображений (`AdImageHashes`).
        :param confirm: явное подтверждение необратимой операции.
        :param on_item_error: `raise` или `collect` (см. `ads.create`).
        :return: список DeleteResults (или `BatchResult`).
        :raises ValidationError: без `confirm` или при неверных хэшах.
        """
        self._ensure_writable("delete")
        ensure_confirmed("ad_images.delete", confirm)
        hash_list = self._validated_hashes(hashes)
        collector = ResultCollector(
            on_item_error, request_id=self._transport.last_request_id
        )
        for chunk in chunked(hash_list, ADIMAGES_GET_MAX):
            payload: Dict[str, Any] = {
                "method": "delete",
                "params": {"SelectionCriteria": {"AdImageHashes": list(chunk)}},
            }
            result = self._transport.post_result("adimages", payload)
            collector.set_request_id(self._transport.last_request_id)
            collector.add(result.get("DeleteResults") or [], "удаления изображения")
        return collector.finish()

    #: Историческое имя метода удаления; в API метода `remove` нет.
    remove = delete

    # ---------------- внутреннее ----------------
    def _validated_hashes(self, hashes: Sequence[str]) -> List[str]:
        """Проверить список хэшей изображений.

        :param hashes: хэши из `adimages/add` или `ads/get`.
        :return: список непустых строк-хэшей.
        :raises ValidationError: хэш не является непустой строкой.
        """
        result: List[str] = []
        for item in hashes:
            if not isinstance(item, str) or not item.strip():
                raise ValidationError(
                    f"AdImageHash должен быть непустой строкой, получено {item!r}"
                )
            result.append(item)
        return result

    def _check_base64(self, image_base64: str) -> None:
        """Проверить, что строка действительно base64 с данными изображения.

        :param image_base64: содержимое изображения в base64.
        :raises ValidationError: строка не декодируется или пуста.
        """
        try:
            decoded = base64.b64decode(image_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationError(
                "Изображение должно быть валидной base64-строкой"
            ) from exc
        if not decoded:
            raise ValidationError("Изображение пустое после декодирования base64")


#: Тип тела одного элемента `adimages/add` (escape-hatch для сложных случаев).
AdImageItem = Mapping[str, Any]

__all__ = [
    "AD_IMAGE_TYPES",
    "ALLOWED_CONTENT_TYPES",
    "ALLOWED_IMAGE_EXTENSIONS",
    "DEFAULT_FIELDS",
    "MAX_IMAGE_BYTES",
    "AdImageItem",
    "AdImageService",
]
