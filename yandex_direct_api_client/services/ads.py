"""Сервис объявлений: list, get, create, update, delete."""
from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Union,
    overload,
)

from .._transport import Transport
from ..config import API_VERSION_V501
from ..exceptions import ValidationError
from ..limits import ADS_GET_MAX, GET_PAGE_MAX, MUTATE_MAX
from ..models.ad import Ad, AdImage, AdText, CpmBannerAdBuilderAd, ResponsiveAd
from ..models.batch import BatchResult
from ..validation import AD_TEXT_MAX_LENGTH, AD_TITLE_MAX_LENGTH, Validator
from ._base import (
    OnItemError,
    ResultCollector,
    chunked,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
)

_DEFAULT_FIELDS = ["Id", "CampaignId", "AdGroupId", "Status", "State", "Type"]
#: Лимиты символов поискового объявления (TextAd). Для РСЯ-лимиты свои —
#: см. `config.AD_TEXT_LIMITS`, добавляется вместе с моделями РСЯ.
_TEXT_LIMITS = {"Title": AD_TITLE_MAX_LENGTH, "Text": AD_TEXT_MAX_LENGTH}


def _clamp_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


class AdService:
    """Операции над объявлениями Yandex.Direct."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("ads", method_name, self._readonly)

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    def list(
        self,
        *,
        campaign_ids: Optional[Sequence[int]] = None,
        ad_group_ids: Optional[Sequence[int]] = None,
        states: Optional[Sequence[str]] = None,
        statuses: Optional[Sequence[str]] = None,
        include_text: bool = False,
        page_limit: int = GET_PAGE_MAX,
    ) -> List[Ad]:
        """Список объявлений с авто-пагинацией.

        :param campaign_ids: фильтр по ID кампаний.
        :param ad_group_ids: фильтр по ID групп объявлений.
        :param states: фильтр по State.
        :param statuses: фильтр по Status.
        :param include_text: включить TextAd (Title/Text/Href).
        :param page_limit: размер страницы.
        """
        criteria: Dict[str, Any] = {}
        if campaign_ids:
            criteria["CampaignIds"] = list(campaign_ids)
        if ad_group_ids:
            criteria["AdGroupIds"] = list(ad_group_ids)
        if states:
            criteria["States"] = list(states)
        if statuses:
            criteria["Statuses"] = list(statuses)

        fields = list(_DEFAULT_FIELDS)
        params: Dict[str, Any] = {
            "SelectionCriteria": criteria,
            "FieldNames": fields,
        }
        if include_text:
            params["TextAdFieldNames"] = ["Title", "Text", "Href"]

        payload: Dict[str, Any] = {"method": "get", "params": params}
        raw_list = fetch_all_pages(
            self._transport, "ads", payload, page_limit=page_limit
        )
        return [Ad.from_dict(a) for a in raw_list]

    def get(
        self,
        ids: Sequence[int],
        *,
        include_text: bool = False,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[Ad]:
        """Получить объявления по ID (авто-чанкинг по 10000).

        :param ids: список ID объявлений.
        :param include_text: включить TextAd.
        :param field_names: кастомные поля.
        """
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        fields = list(field_names) if field_names else list(_DEFAULT_FIELDS)
        results: List[Ad] = []
        for chunk in chunked(list(ids), ADS_GET_MAX):
            params: Dict[str, Any] = {
                "SelectionCriteria": {"Ids": list(chunk)},
                "FieldNames": fields,
            }
            if include_text:
                params["TextAdFieldNames"] = ["Title", "Text", "Href"]
            payload: Dict[str, Any] = {"method": "get", "params": params}
            result = self._transport.post_result("ads", payload)
            for raw in result.get("Ads") or []:
                results.append(Ad.from_dict(raw))
        return results

    @overload
    def create(
        self,
        ads: Sequence[Dict[str, Any]],
        *,
        api_version: Optional[str] = None,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def create(
        self,
        ads: Sequence[Dict[str, Any]],
        *,
        api_version: Optional[str] = None,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def create(
        self,
        ads: Sequence[Dict[str, Any]],
        *,
        api_version: Optional[str] = None,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Создать объявления (batch, до 200 за запрос).

        :param ads: список тел объявлений по схеме ads/add.
        :param api_version: версия API для этого вызова (`v501` для ЕПК).
        :param on_item_error: `raise` — ошибка элемента бросает `ApiError`;
            `collect` — возвращает `BatchResult` с успешными и неуспешными.
        :return: список AddResults (или `BatchResult`).
        """
        self._ensure_writable("create")
        ad_list = list(ads)
        if not ad_list:
            return [] if on_item_error == "raise" else BatchResult()
        collector = ResultCollector(on_item_error)
        for chunk in chunked(ad_list, MUTATE_MAX):
            payload: Dict[str, Any] = {
                "method": "add",
                "params": {"Ads": list(chunk)},
            }
            result = self._transport.post_result(
                "ads", payload, api_version=api_version
            )
            collector.set_request_id(self._transport.last_request_id)
            collector.add(result.get("AddResults") or [], "создания объявления")
        return collector.finish()

    def create_with_payload(
        self,
        campaign_id: int,
        text: AdText,
        *,
        image: Optional[AdImage] = None,
        ad_group_id: Optional[int] = None,
        type_: str = "TEXT_AD",
    ) -> Dict[str, Any]:
        """Создать объявление из типизированных моделей (текст и картинка).

        :param campaign_id: ID кампании. Принимается для совместимости, но
            НЕ отправляется: ads/add не принимает CampaignId — кампания
            объявления выводится из группы (AdGroupId).
        :param text: текстовая часть объявления (AdText).
        :param image: картинка объявления (`AdImageHash` внутри `TextAd`),
            если нужна.
        :param ad_group_id: ID группы объявлений — обязателен (ads/add
            требует AdGroupId).
        :param type_: принимается для совместимости, но НЕ отправляется:
            ads/add не принимает Type — тип выводится из переданных
            TextAd/ImageAd.
        :return: элемент AddResults.
        """
        self._ensure_writable("create_with_payload")
        if ad_group_id is None:
            raise ValidationError(
                "ads/add требует AdGroupId — кампания выводится из группы; "
                "передайте ad_group_id"
            )
        validator = self._validator()
        validator.ids([ad_group_id], field="AdGroupId")
        validator.href(getattr(text, "href", None))
        body: Dict[str, Any] = {
            "AdGroupId": int(ad_group_id),
            "TextAd": text.to_payload(),
        }
        if image is not None:
            body["TextAd"].update(image.to_payload())
        return self.create([body])[0]

    @overload
    def update(
        self,
        ads: Sequence[Dict[str, Any]],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def update(
        self,
        ads: Sequence[Dict[str, Any]],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def update(
        self,
        ads: Sequence[Dict[str, Any]],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Обновить объявления (batch, до 200 за запрос).

        :param ads: список тел с Id и обновляемыми полями (ads/update).
        :param confirm: явное подтверждение массового изменения.
        :param on_item_error: `raise` или `collect` (см. `create`).
        :return: список UpdateResults (или `BatchResult`).
        """
        self._ensure_writable("update")
        ensure_confirmed("ads.update", confirm)
        ad_list = list(ads)
        if not ad_list:
            return [] if on_item_error == "raise" else BatchResult()
        collector = ResultCollector(on_item_error)
        for chunk in chunked(ad_list, MUTATE_MAX):
            payload: Dict[str, Any] = {
                "method": "update",
                "params": {"Ads": list(chunk)},
            }
            result = self._transport.post_result("ads", payload)
            collector.set_request_id(self._transport.last_request_id)
            collector.add(result.get("UpdateResults") or [], "обновления объявления")
        return collector.finish()

    def update_text(
        self,
        ad_id: int,
        headline: str,
        body: str,
        *,
        href: Optional[str] = None,
        auto_clamp: bool = True,
    ) -> Dict[str, Any]:
        """Обновить Title/Text текстового объявления (одиночное).

        :param auto_clamp: обрезать строки до лимитов Директа (56/81). По
            умолчанию True — обратная совместимость (решение D3). Новые
            типизированные билдеры объявлений так не обрезают, а бросают
            ValidationError.
        :return: элемент UpdateResults.
        """
        self._ensure_writable("update_text")
        self._validator().ids([ad_id], field="ad_id")
        if auto_clamp:
            headline = _clamp_text(headline, _TEXT_LIMITS["Title"])
            body = _clamp_text(body, _TEXT_LIMITS["Text"])
        else:
            if len(headline) > _TEXT_LIMITS["Title"]:
                raise ValidationError(
                    f"headline длиннее {_TEXT_LIMITS['Title']} символов"
                )
            if len(body) > _TEXT_LIMITS["Text"]:
                raise ValidationError(
                    f"body длиннее {_TEXT_LIMITS['Text']} символов"
                )

        text_ad: Dict[str, Any] = {"Title": headline, "Text": body}
        if href is not None:
            text_ad["Href"] = href

        return self.update([{"Id": int(ad_id), "TextAd": text_ad}], confirm=True)[0]

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
        """Удалить объявления по ID (авто-чанкинг по 200).

        :param ids: список ID объявлений.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `create`).
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete")
        ensure_confirmed("ads.delete", confirm)
        return self._state_action("delete", "DeleteResults", "удаления", ids, on_item_error)

    def _state_action(
        self,
        method_name: str,
        result_key: str,
        action_label: str,
        ids: Sequence[int],
        on_item_error: OnItemError = "raise",
        api_version: Optional[str] = None,
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Общий batch-вызов метода управления состоянием/модерацией.

        :param method_name: имя метода API (suspend/resume/archive/...).
        :param result_key: ключ списка результатов в ответе.
        :param action_label: описание действия для сообщений об ошибках.
        :param ids: список ID объявлений.
        :param on_item_error: `raise` или `collect`.
        :param api_version: версия API для этого вызова; нужна для объявлений
            ЕПК (`v501`), для классических — `None` (то есть `v5`).
        :return: список элементов ActionResult (или `BatchResult`).
        """
        self._ensure_writable(method_name)
        id_list = list(ids)
        if not id_list:
            return [] if on_item_error == "raise" else BatchResult()
        self._validator().ids(id_list, field="SelectionCriteria.Ids")
        collector = ResultCollector(on_item_error)
        for chunk in chunked(id_list, MUTATE_MAX):
            payload: Dict[str, Any] = {
                "method": method_name,
                "params": {"SelectionCriteria": {"Ids": list(chunk)}},
            }
            result = self._transport.post_result(
                "ads", payload, api_version=api_version
            )
            collector.set_request_id(self._transport.last_request_id)
            collector.add(
                result.get(result_key) or [],
                f"{action_label} объявления",
            )
        return collector.finish()

    @overload
    def suspend(
        self,
        ids: Sequence[int],
        *,
        on_item_error: Literal["raise"] = ...,
        api_version: Optional[str] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def suspend(
        self,
        ids: Sequence[int],
        *,
        on_item_error: Literal["collect"],
        api_version: Optional[str] = ...,
    ) -> BatchResult: ...

    def suspend(
        self,
        ids: Sequence[int],
        *,
        on_item_error: OnItemError = "raise",
        api_version: Optional[str] = None,
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Остановить показы объявлений (ads/suspend).

        :param ids: список ID объявлений.
        :param on_item_error: `raise` или `collect`.
        :param api_version: версия API (`v501` для объявлений ЕПК).
        :return: список элементов SuspendResults (или `BatchResult`).
        """
        return self._state_action(
            "suspend",
            "SuspendResults",
            "остановки",
            ids,
            on_item_error,
            api_version=api_version,
        )

    @overload
    def resume(
        self,
        ids: Sequence[int],
        *,
        on_item_error: Literal["raise"] = ...,
        api_version: Optional[str] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def resume(
        self,
        ids: Sequence[int],
        *,
        on_item_error: Literal["collect"],
        api_version: Optional[str] = ...,
    ) -> BatchResult: ...

    def resume(
        self,
        ids: Sequence[int],
        *,
        on_item_error: OnItemError = "raise",
        api_version: Optional[str] = None,
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Возобновить показы объявлений (ads/resume).

        :param ids: список ID объявлений.
        :param on_item_error: `raise` или `collect`.
        :param api_version: версия API (`v501` для объявлений ЕПК).
        :return: список элементов ResumeResults (или `BatchResult`).
        """
        return self._state_action(
            "resume",
            "ResumeResults",
            "возобновления",
            ids,
            on_item_error,
            api_version=api_version,
        )

    def create_rsya_banner(
        self,
        ad_group_id: int,
        creative_id: int,
        *,
        href: Optional[str] = None,
        turbo_page_id: Optional[int] = None,
        tracking_pixels: Optional[Sequence[str]] = None,
        eir_ad_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Создать медийное объявление РСЯ (`CpmBannerAdBuilderAd`).

        В текущем API медийное объявление создаётся только как builder-объявление:
        текст, заголовок и картинка берутся из **креатива**, созданного в
        конструкторе креативов, а в запросе передаётся его ID
        (`Creative.CreativeId`). Заголовок и текст лимитами РСЯ не
        проверяются на стороне SDK — они заданы в креативе.

        :param ad_group_id: ID группы `CPM_BANNER_AD_GROUP`.
        :param creative_id: ID креатива из `client.creatives.get()`.
        :param href: ссылка объявления (обязательна без `turbo_page_id`).
        :param turbo_page_id: ID Турбо-страницы вместо ссылки.
        :param tracking_pixels: пиксели-трекеры (не более двух).
        :param eir_ad_description: описание для ЕИР.
        :return: элемент AddResults.
        :raises ValidationError: невалидные ID, не задан `creative_id`,
            нет ни ссылки, ни Турбо-страницы, либо превышены лимиты.
        """
        self._ensure_writable("create_rsya_banner")
        self._validator().ids([ad_group_id], field="AdGroupId")
        ad = CpmBannerAdBuilderAd(
            creative_id=creative_id,
            href=href,
            turbo_page_id=turbo_page_id,
            tracking_pixels=tracking_pixels,
            eir_ad_description=eir_ad_description,
        )
        body: Dict[str, Any] = {
            "AdGroupId": int(ad_group_id),
            "CpmBannerAdBuilderAd": ad.to_payload(),
        }
        return self.create([body])[0]

    # ---------------- ЕПК (v501) ----------------
    def create_responsive_ad(
        self,
        ad_group_id: int,
        titles: Sequence[str],
        texts: Sequence[str],
        *,
        href: Optional[str] = None,
        ad_image_hashes: Optional[Sequence[str]] = None,
        api_version: Optional[str] = API_VERSION_V501,
    ) -> Dict[str, Any]:
        """Создать комбинаторное объявление ЕПК (`ResponsiveAd`, `v501`).

        Лимиты заголовков (1..7 по 56 символов) и текстов (1..3 по 81)
        проверяются до отправки; строки не обрезаются — превышение лимита
        даёт `ValidationError` (D3).

        :param ad_group_id: ID группы ЕПК (`UNIFIED_AD_GROUP`).
        :param titles: заголовки объявления.
        :param texts: тексты объявления.
        :param href: ссылка на страницу (обязательна без `business_id`).
        :param ad_image_hashes: хэши изображений из `adimages/add` (1..5).
        :param api_version: версия API (по умолчанию `v501`).
        :return: элемент AddResults.
        :raises ValidationError: нарушены лимиты или не задан `href`.
        """
        self._ensure_writable("create_responsive_ad")
        self._validator().ids([ad_group_id], field="AdGroupId")
        ad = ResponsiveAd(
            titles=titles, texts=texts, href=href, ad_image_hashes=ad_image_hashes
        )
        body: Dict[str, Any] = {
            "AdGroupId": int(ad_group_id),
            "ResponsiveAd": ad.to_payload(),
        }
        return self.create([body], api_version=api_version)[0]

    @overload
    def archive(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
        api_version: Optional[str] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def archive(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
        api_version: Optional[str] = ...,
    ) -> BatchResult: ...

    def archive(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
        api_version: Optional[str] = None,
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Разместить объявления в архив (ads/archive).

        :param ids: список ID объявлений.
        :param confirm: явное подтверждение массового изменения.
        :param on_item_error: `raise` или `collect`.
        :param api_version: версия API (`v501` для объявлений ЕПК).
        :return: список элементов ArchiveResults (или `BatchResult`).
        """
        ensure_confirmed("ads.archive", confirm)
        return self._state_action(
            "archive",
            "ArchiveResults",
            "архивации",
            ids,
            on_item_error,
            api_version=api_version,
        )

    @overload
    def unarchive(
        self, ids: Sequence[int], *, on_item_error: Literal["raise"] = ...
    ) -> List[Dict[str, Any]]: ...

    @overload
    def unarchive(
        self, ids: Sequence[int], *, on_item_error: Literal["collect"]
    ) -> BatchResult: ...

    def unarchive(
        self, ids: Sequence[int], *, on_item_error: OnItemError = "raise"
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Разархивировать объявления (ads/unarchive).

        :param ids: список ID объявлений.
        :param on_item_error: `raise` или `collect`.
        :return: список элементов UnarchiveResults (или `BatchResult`).
        """
        return self._state_action(
            "unarchive", "UnarchiveResults", "разархивации", ids, on_item_error
        )

    @overload
    def moderate(
        self,
        ids: Sequence[int],
        *,
        on_item_error: Literal["raise"] = ...,
        api_version: Optional[str] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def moderate(
        self,
        ids: Sequence[int],
        *,
        on_item_error: Literal["collect"],
        api_version: Optional[str] = ...,
    ) -> BatchResult: ...

    def moderate(
        self,
        ids: Sequence[int],
        *,
        on_item_error: OnItemError = "raise",
        api_version: Optional[str] = None,
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Отправить объявления на модерацию (ads/moderate).

        Отправить можно только объявления со статусом DRAFT. Объявления ЕПК
        требуют `api_version="v501"`.

        :param ids: список ID объявлений.
        :param on_item_error: `raise` или `collect`.
        :param api_version: версия API (`v501` для объявлений ЕПК).
        :return: список элементов ModerateResults (или `BatchResult`).
        """
        return self._state_action(
            "moderate",
            "ModerateResults",
            "отправки на модерацию",
            ids,
            on_item_error,
            api_version=api_version,
        )


__all__ = ["AdService"]
