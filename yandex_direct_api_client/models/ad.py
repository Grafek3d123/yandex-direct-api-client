"""Модели объявлений Яндекс.Директа.

Содержит:

- `AdText` — текстово-графическое объявление (`TextAd`);
- `CpmBannerAdBuilderAd` — медийное объявление РСЯ
  (`CpmBannerAdBuilderAd`): текст и картинка берутся из **креатива**;
- `ImageAdRef` — ссылка на загруженное изображение по `AdImageHash`
  (алиас `AdImage` сохранён для совместимости, D2);
- `BannerAd` — модель чтения legacy-медийного объявления;
- `Ad` — общая модель ответа по объявлению.

Состав полей сверен с ads/add (снимок 30.09.2026): в текущем API
медийное объявление создаётся только как builder-объявление с
`Creative.CreativeId` — креатив загружается в веб-интерфейсе или
конструкторе креативов и читается через `creatives/get`. Поля `Title`,
`Text`, `ImageId` в `ads/add` больше не принимаются.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..exceptions import ValidationError
from ..validation import AD_HREF_MAX_LENGTH, Validator
from ._helpers import to_int, to_optional_int, to_str

#: Максимум пикселей-трекеров у builder-объявления (docs: TrackingPixels).
TRACKING_PIXELS_MAX = 2

#: Максимальная длина одного пикселя-трекера.
TRACKING_PIXEL_MAX_LENGTH = 1024

#: Количество и лимиты заголовков ЕПК-объявления (docs: ResponsiveAdAdd).
RESPONSIVE_TITLES_MIN = 1
RESPONSIVE_TITLES_MAX = 7
RESPONSIVE_TITLE_MAX_LENGTH = 56

#: Количество и лимиты текстов ЕПК-объявления (docs: ResponsiveAdAdd).
RESPONSIVE_TEXTS_MIN = 1
RESPONSIVE_TEXTS_MAX = 3
RESPONSIVE_TEXT_MAX_LENGTH = 81

#: Максимум изображений у ЕПК-объявления (docs: ResponsiveAdAdd.AdImageHashes).
RESPONSIVE_IMAGES_MAX = 5

#: Максимум расширений и видеодополнений (docs: ResponsiveAdAdd).
RESPONSIVE_AD_EXTENSIONS_MAX = 50
RESPONSIVE_VIDEO_EXTENSIONS_MIN = 1
RESPONSIVE_VIDEO_EXTENSIONS_MAX = 6

#: Максимальная длина пути отображаемой ссылки (docs: DisplayUrlPath).
RESPONSIVE_DISPLAY_URL_PATH_MAX = 20


@dataclass
class AdText:
    """Текстово-графическое объявление (`TextAd`)."""

    title: str = ""
    text: str = ""
    href: str = ""
    ad_image_hash: Optional[str] = None
    display_url_path: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "AdText":
        """Разобрать `TextAd` из ответа API.

        :param d: JSON-объект TextAd либо None.
        :return: модель текстовой части.
        """
        if not d:
            return cls()
        return cls(
            title=to_str(d.get("Title")),
            text=to_str(d.get("Text")),
            href=to_str(d.get("Href")),
            ad_image_hash=to_str(d.get("AdImageHash")) or None,
            display_url_path=to_str(d.get("DisplayUrlPath")) or None,
        )

    def to_payload(self) -> Dict[str, Any]:
        """Тело `TextAd` для `ads/add` и `ads/update`.

        :return: словарь с `Title`, `Text` и опциональными полями.
        """
        payload: Dict[str, Any] = {"Title": self.title, "Text": self.text}
        if self.href:
            payload["Href"] = self.href
        if self.ad_image_hash:
            payload["AdImageHash"] = self.ad_image_hash
        if self.display_url_path:
            payload["DisplayUrlPath"] = self.display_url_path
        return payload


@dataclass
class ImageAdRef:
    """Ссылка на загруженное изображение (`AdImageHash`).

    :param image_hash: хэш изображения, полученный от `adimages/add`.
    """

    image_hash: str = ""

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "ImageAdRef":
        """Разобрать ссылку на изображение из ответа API.

        :param d: JSON-объект с `AdImageHash`/`ImageHash` либо None.
        :return: модель ссылки на креатив.
        """
        if not d:
            return cls()
        return cls(image_hash=to_str(d.get("AdImageHash")) or to_str(d.get("ImageHash")))

    def to_payload(self) -> Dict[str, Any]:
        """Тело ссылки на изображение.

        :return: словарь `{"AdImageHash": ...}`.
        :raises ValidationError: хэш не задан.
        """
        if not self.image_hash:
            raise ValidationError(
                "image_hash обязателен: загрузите изображение через "
                "client.ad_images.add() и передайте полученный AdImageHash"
            )
        return {"AdImageHash": self.image_hash}


#: Историческое имя класса. Сохранено как алиас, чтобы не ломать код,
#: написанный до перехода на `ImageAdRef` (D2).
AdImage = ImageAdRef


@dataclass
class CpmBannerAdBuilderAd:
    """Медийное объявление РСЯ (`CpmBannerAdBuilderAd`).

    Текст, заголовок и изображения берутся из креатива, созданного в
    конструкторе креативов; ID креатива читается через `creatives/get`.
    В самом объявлении задаются только ссылка и пиксели.

    :param creative_id: ID креатива из `creatives/get`.
    :param href: ссылка объявления (обязательна, если не задан
        `turbo_page_id`).
    :param turbo_page_id: ID Турбо-страницы вместо ссылки.
    :param eir_ad_description: описание для ЕИР (реклама на маркетплейсах).
    :param tracking_pixels: пиксели-трекеры (не более двух).
    """

    creative_id: int = 0
    href: Optional[str] = None
    turbo_page_id: Optional[int] = None
    eir_ad_description: Optional[str] = None
    tracking_pixels: Optional[Sequence[str]] = None

    def to_payload(self) -> Dict[str, Any]:
        """Тело `CpmBannerAdBuilderAd` для `ads/add` и `ads/update`.

        :return: словарь с `Creative` и опциональными полями.
        :raises ValidationError: не задан креатив, нет ни ссылки, ни
            Турбо-страницы, либо превышены лимиты пикселей.
        """
        validator = Validator(True)
        validator.ids([self.creative_id], field="CpmBannerAdBuilderAd.Creative.CreativeId")
        if not self.href and self.turbo_page_id is None:
            raise ValidationError(
                "CpmBannerAdBuilderAd требует href или turbo_page_id"
            )
        if self.turbo_page_id is not None:
            validator.ids([self.turbo_page_id], field="TurboPageId")
        payload: Dict[str, Any] = {"Creative": {"CreativeId": int(self.creative_id)}}
        if self.href:
            validator.href(self.href, field="Href")
            if len(self.href) > AD_HREF_MAX_LENGTH:
                raise ValidationError(
                    f"Href длиннее {AD_HREF_MAX_LENGTH} символов"
                )
            payload["Href"] = self.href
        if self.turbo_page_id is not None:
            payload["TurboPageId"] = int(self.turbo_page_id)
        if self.eir_ad_description:
            payload["ErirAdDescription"] = self.eir_ad_description
        if self.tracking_pixels is not None:
            pixels: List[str] = list(self.tracking_pixels)
            if len(pixels) > TRACKING_PIXELS_MAX:
                raise ValidationError(
                    f"TrackingPixels: не более {TRACKING_PIXELS_MAX} элементов"
                )
            for pixel in pixels:
                if not pixel or len(pixel) > TRACKING_PIXEL_MAX_LENGTH:
                    raise ValidationError(
                        "TrackingPixels: элементы должны быть непустыми и не "
                        f"длиннее {TRACKING_PIXEL_MAX_LENGTH} символов"
                    )
            payload["TrackingPixels"] = {"Items": pixels}
        return payload


@dataclass
class ResponsiveAd:
    """Комбинаторное объявление ЕПК (`ResponsiveAd`, слой 2Б).

    Создаётся через `v501`. Заголовки и тексты комбинируются Яндексом при
    показе, поэтому SDK не обрезает их молча: превышение лимитов — это
    `ValidationError` (D3).

    :param titles: заголовки (1..7, до 56 узких символов каждый).
    :param texts: тексты (1..3, до 81 узкого символа каждый).
    :param href: ссылка на страницу (обязательна, если не задан `business_id`).
    :param business_id: ID организации в Яндекс Бизнесе.
    :param ad_image_hashes: хэши изображений (1..5, из `adimages/add`).
    :param sitelink_set_id: набор быстрых ссылок.
    :param ad_extension_ids: ID уточнений/быстрых ссылок (до 50).
    :param video_extension_ids: ID видеодополнений (1..6).
    :param display_url_path: путь отображаемой ссылки (до 20 символов).
    :param age_label: возрастная маркировка (0, 6, 12, 16, 18).
    :param eir_ad_description: описание для ЕИР.
    """

    titles: Sequence[str] = field(default_factory=tuple)
    texts: Sequence[str] = field(default_factory=tuple)
    href: Optional[str] = None
    business_id: Optional[int] = None
    ad_image_hashes: Optional[Sequence[str]] = None
    sitelink_set_id: Optional[int] = None
    ad_extension_ids: Optional[Sequence[int]] = None
    video_extension_ids: Optional[Sequence[int]] = None
    display_url_path: Optional[str] = None
    age_label: Optional[int] = None
    eir_ad_description: Optional[str] = None

    def _validate_str_list(
        self, values: Sequence[str], *, field: str, minimum: int, maximum: int,
        max_length: int,
    ) -> List[str]:
        """Проверить список строк объявления.

        :param values: значения.
        :param field: имя поля для сообщения об ошибке.
        :param minimum: минимальное количество.
        :param maximum: максимальное количество.
        :param max_length: максимальная длина одного значения.
        :return: список значений.
        :raises ValidationError: при нарушении количества или длины.
        """
        items = list(values)
        if not minimum <= len(items) <= maximum:
            raise ValidationError(
                f"{field}: от {minimum} до {maximum} значений, передано {len(items)}"
            )
        validator = Validator(True)
        for item in items:
            validator.text(item, field=field, max_length=max_length)
        return items

    def to_payload(self) -> Dict[str, Any]:
        """Тело `ResponsiveAd` для `ads/add` и `ads/update`.

        :return: словарь с заголовками, текстами и опциональными полями.
        :raises ValidationError: нарушены лимиты заголовков, текстов,
            изображений, расширений или не задана ссылка/организация.
        """
        validator = Validator(True)
        titles = self._validate_str_list(
            self.titles,
            field="ResponsiveAd.Titles",
            minimum=RESPONSIVE_TITLES_MIN,
            maximum=RESPONSIVE_TITLES_MAX,
            max_length=RESPONSIVE_TITLE_MAX_LENGTH,
        )
        texts = self._validate_str_list(
            self.texts,
            field="ResponsiveAd.Texts",
            minimum=RESPONSIVE_TEXTS_MIN,
            maximum=RESPONSIVE_TEXTS_MAX,
            max_length=RESPONSIVE_TEXT_MAX_LENGTH,
        )
        if not self.href and self.business_id is None:
            raise ValidationError(
                "ResponsiveAd требует href или business_id"
            )
        payload: Dict[str, Any] = {"Titles": titles, "Texts": texts}
        if self.href:
            validator.href(self.href, field="ResponsiveAd.Href")
            if len(self.href) > AD_HREF_MAX_LENGTH:
                raise ValidationError(
                    f"ResponsiveAd.Href длиннее {AD_HREF_MAX_LENGTH} символов"
                )
            payload["Href"] = self.href
        if self.business_id is not None:
            validator.ids([self.business_id], field="ResponsiveAd.BusinessId")
            payload["BusinessId"] = int(self.business_id)
        if self.ad_image_hashes is not None:
            hashes = list(self.ad_image_hashes)
            if not 1 <= len(hashes) <= RESPONSIVE_IMAGES_MAX:
                raise ValidationError(
                    "ResponsiveAd.AdImageHashes: от 1 до "
                    f"{RESPONSIVE_IMAGES_MAX} изображений, передано {len(hashes)}"
                )
            for item in hashes:
                if not isinstance(item, str) or not item.strip():
                    raise ValidationError(
                        "ResponsiveAd.AdImageHashes: хэш должен быть непустой строкой"
                    )
            payload["AdImageHashes"] = hashes
        if self.sitelink_set_id is not None:
            validator.ids([self.sitelink_set_id], field="ResponsiveAd.SitelinkSetId")
            payload["SitelinkSetId"] = int(self.sitelink_set_id)
        if self.ad_extension_ids is not None:
            extension_ids = list(self.ad_extension_ids)
            validator.ids(extension_ids, field="ResponsiveAd.AdExtensionIds")
            if len(extension_ids) > RESPONSIVE_AD_EXTENSIONS_MAX:
                raise ValidationError(
                    "ResponsiveAd.AdExtensionIds: не более "
                    f"{RESPONSIVE_AD_EXTENSIONS_MAX} расширений"
                )
            payload["AdExtensionIds"] = [int(x) for x in extension_ids]
        if self.video_extension_ids is not None:
            video_ids = list(self.video_extension_ids)
            validator.ids(video_ids, field="ResponsiveAd.VideoExtensionIds")
            if not RESPONSIVE_VIDEO_EXTENSIONS_MIN <= len(video_ids) <= (
                RESPONSIVE_VIDEO_EXTENSIONS_MAX
            ):
                raise ValidationError(
                    "ResponsiveAd.VideoExtensionIds: от "
                    f"{RESPONSIVE_VIDEO_EXTENSIONS_MIN} до "
                    f"{RESPONSIVE_VIDEO_EXTENSIONS_MAX} видеодополнений"
                )
            payload["VideoExtensionIds"] = [int(x) for x in video_ids]
        if self.display_url_path:
            if len(self.display_url_path) > RESPONSIVE_DISPLAY_URL_PATH_MAX:
                raise ValidationError(
                    "ResponsiveAd.DisplayUrlPath длиннее "
                    f"{RESPONSIVE_DISPLAY_URL_PATH_MAX} символов"
                )
            payload["DisplayUrlPath"] = self.display_url_path
        if self.age_label is not None:
            if self.age_label not in (0, 6, 12, 16, 18):
                raise ValidationError(
                    f"ResponsiveAd.AgeLabel: недопустимое значение {self.age_label!r}"
                )
            payload["AgeLabel"] = int(self.age_label)
        if self.eir_ad_description:
            payload["ErirAdDescription"] = self.eir_ad_description
        return payload


@dataclass
class BannerAd:
    """Модель чтения медийного объявления (`BannerAd`).

    В текущем API `BannerAd` не принимается в `ads/add` (см.
    `CpmBannerAdBuilderAd`); модель сохранена для разбора ответов
    `ads/get` и не умеет собирать тело запроса.

    :param title: заголовок объявления.
    :param text: текст объявления.
    :param href: ссылка.
    :param image_id: ID креатива, если пришёл в ответе.
    """

    title: str = ""
    text: str = ""
    href: str = ""
    image_id: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "BannerAd":
        """Разобрать `BannerAd` из ответа API.

        :param d: JSON-объект BannerAd либо None.
        :return: модель медийного объявления.
        """
        if not d:
            return cls()
        return cls(
            title=to_str(d.get("Title")),
            text=to_str(d.get("Text")),
            href=to_str(d.get("Href")),
            image_id=to_optional_int(d.get("ImageId")),
        )


@dataclass
class Ad:
    """Объявление Директа (базовые поля + текстовая часть, если запрошена)."""

    id: int
    ad_group_id: Optional[int] = None
    campaign_id: Optional[int] = None
    status: Optional[str] = None
    state: Optional[str] = None
    type: Optional[str] = None
    name: Optional[str] = None
    text_ad: Optional[AdText] = None
    banner_ad: Optional[BannerAd] = None
    image_ad: Optional[ImageAdRef] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Ad":
        """Разобрать объявление из ответа API.

        :param d: JSON-запись объявления.
        :return: модель объявления с доступными частями (TextAd/BannerAd).
        """
        text_ad_raw = d.get("TextAd")
        banner_ad_raw = d.get("BannerAd")
        image_ad_raw = d.get("ImageAd") or d.get("Image")
        return cls(
            id=to_int(d.get("Id")),
            ad_group_id=to_optional_int(d.get("AdGroupId")),
            campaign_id=to_optional_int(d.get("CampaignId")),
            status=d.get("Status"),
            state=d.get("State"),
            type=d.get("Type"),
            name=d.get("Name"),
            text_ad=AdText.from_dict(text_ad_raw) if text_ad_raw else None,
            banner_ad=BannerAd.from_dict(banner_ad_raw) if banner_ad_raw else None,
            image_ad=ImageAdRef.from_dict(image_ad_raw) if image_ad_raw else None,
            raw=d,
        )


__all__ = [
    "RESPONSIVE_AD_EXTENSIONS_MAX",
    "RESPONSIVE_DISPLAY_URL_PATH_MAX",
    "RESPONSIVE_IMAGES_MAX",
    "RESPONSIVE_TEXTS_MAX",
    "RESPONSIVE_TEXTS_MIN",
    "RESPONSIVE_TEXT_MAX_LENGTH",
    "RESPONSIVE_TITLES_MAX",
    "RESPONSIVE_TITLES_MIN",
    "RESPONSIVE_TITLE_MAX_LENGTH",
    "RESPONSIVE_VIDEO_EXTENSIONS_MAX",
    "RESPONSIVE_VIDEO_EXTENSIONS_MIN",
    "TRACKING_PIXEL_MAX_LENGTH",
    "TRACKING_PIXELS_MAX",
    "Ad",
    "AdImage",
    "AdText",
    "BannerAd",
    "CpmBannerAdBuilderAd",
    "ImageAdRef",
    "ResponsiveAd",
]
