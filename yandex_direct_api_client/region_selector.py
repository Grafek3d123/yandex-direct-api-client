"""Универсальный механизм гео-таргетинга `RegionSelector` (F-1.2, D5).

Ключевой факт API: **механизма «исключить регионы» в Yandex.Direct нет**.
Гео-таргетинг задаётся только списком `RegionIds` — то есть «вся РФ, кроме
Москвы, МО, СПб и Ленобласти» выражается перечислением всех остальных
регионов.

`RegionSelector` скрывает это перечисление, но **не содержит бизнес-значений**:
в SDK нет ни «всей России», ни «исключить МСК/СПб/ЛО/МО» как зашитых констант.
Пользователь передаёт произвольный список, а SDK:

- принимает элементы как `RegionId` (int), код региона или название;
- резолвит коды и названия **только** через справочник
  `client.dictionaries.geo_regions()` (никаких выдуманных ID);
- при неизвестном значении или неоднозначном названии бросает
  `ValidationError` с подсказками, а не угадывает;
- при пустом результате резолва бросает `ValidationError` — отправлять
  `RegionIds: []` бессмысленно.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Union, cast

from .exceptions import ValidationError
from .models.dictionaries import GeoRegion, dedupe_ids

#: Элемент списка гео: ID региона, его код или название.
RegionRef = Union[int, str]

#: Сколько похожих совпадений показывать в сообщении об ошибке.
_SUGGESTIONS_LIMIT = 5

#: Порог совпадения по подстроке, при котором название считается совпавшим.
_SIMILARITY_THRESHOLD = 0.34


def _normalize(text: str) -> str:
    """Нормализовать название региона для сравнения.

    :param text: исходное название.
    :return: строчная строка без «области/края/республики» и без пробелов.
    """
    lowered = text.strip().lower().replace("ё", "е")
    for suffix in (
        " область",
        " республика",
        " край",
        " республ",
        " респ.",
        " автономный округ",
        " ао",
        " г.",
        " г ",
        " обл.",
    ):
        if lowered.endswith(suffix):
            lowered = lowered[: -len(suffix)]
            break
    return lowered.strip()


def _similarity(a: str, b: str) -> float:
    """Оценить близость двух названий через общий префикс/символы.

    Простая эвристика без внешних зависимостей: доля общих символов
    относительно длины объединения.

    :param a: первое название.
    :param b: второе название.
    :return: значение от 0.0 до 1.0.
    """
    if not a or not b:
        return 0.0
    common = sum(1 for x, y in zip(a, b) if x == y)
    prefix = 0
    for x, y in zip(a, b):
        if x != y:
            break
        prefix += 1
    union = len(set(a) | set(b))
    chars = common / union if union else 0.0
    return max(chars, prefix / max(len(a), len(b)))


def _suggest(needle: str, regions: Sequence[GeoRegion]) -> List[str]:
    """Подобрать похожие названия регионов для сообщения об ошибке.

    :param needle: неизвестное пользовательское значение.
    :param regions: доступные регионы.
    :return: до пяти похожих названий «id — название».
    """
    target = _normalize(needle)
    scored = [
        (_similarity(target, _normalize(r.name)), r)
        for r in regions
    ]
    scored = [item for item in scored if item[0] >= _SIMILARITY_THRESHOLD]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [f"{r.id} — {r.name}" for _score, r in scored[:_SUGGESTIONS_LIMIT]]


@dataclass
class RegionSelector:
    """Описание гео-таргетинга: список включаемых и исключаемых регионов.

    :param include: регионы, которые нужно включить; если список пуст, а
        `exclude` задан — берётся вся доступная страна минус исключения.
    :param exclude: регионы, которые нужно исключить из результата.
    :param country_region: код страны для резолва. По умолчанию `"RUC"` —
        удобно для русскоязычных аккаунтов; для иностранных укажите код
        явно (например, `"US"`), иначе резолв пойдёт по справочнику России.
    :param include_all: явно брать все регионы страны.

    Пример::

        selector = RegionSelector(
            exclude=["Москва", "Московская область", "Санкт-Петербург",
                     "Ленинградская область"],
        )
        region_ids = selector.resolve(client.dictionaries)
    """

    include: Sequence[RegionRef] = field(default_factory=tuple)
    exclude: Sequence[RegionRef] = field(default_factory=tuple)
    country_region: str = "RUC"  # default — русскоязычный аккаунт; override для иностранных
    include_all: bool = False

    def include_all_russia(self) -> "RegionSelector":
        """Вернуть копию селектора, включающую все регионы страны.

        Страна берётся из `country_region` селектора (по умолчанию `RUC`).

        :return: новый селектор с явным признаком «включить всё».
        """
        return RegionSelector(
            include=list(self.include),
            exclude=list(self.exclude),
            country_region=self.country_region,
            include_all=True,
        )

    # ---------------- резолв ----------------
    def resolve(self, dictionaries: Any) -> List[int]:
        """Превратить описания регионов в список ID для `RegionIds`.

        :param dictionaries: `client.dictionaries` (нужен `geo_regions()`).
        :return: упорядоченный список уникальных ID регионов.
        :raises ValidationError: неизвестное или неоднозначное значение,
            либо пустой результат резолва.
        """
        regions = self._available_regions(dictionaries)
        by_id = {r.id: r for r in regions}
        by_code = self._index_by_code(regions)
        by_name = self._index_by_name(regions)

        excluded_ids = (
            dedupe_ids(
                [self._resolve_one(r, by_id, by_code, by_name) for r in self.exclude]
            )
            if self.exclude
            else []
        )
        excluded_set = set(excluded_ids)

        if self.include_all:
            base_ids = [r.id for r in regions]
        elif self.include:
            base_ids = dedupe_ids(
                [self._resolve_one(r, by_id, by_code, by_name) for r in self.include]
            )
        else:
            if not self.exclude:
                raise ValidationError(
                    "RegionSelector: задайте include или exclude — "
                    "«вся страна» без списков передавать нечего"
                )
            # Пустой include при непустом exclude = «вся страна минус исключения».
            base_ids = [r.id for r in regions]

        result = [rid for rid in base_ids if rid not in excluded_set]

        if not result:
            raise ValidationError(
                "RegionSelector: после резолва не осталось ни одного региона — "
                "проверьте списки include/exclude"
            )
        return result

    @staticmethod
    def current(ad_group: Any) -> List[int]:
        """Прочитать текущие регионы группы объявлений.

        :param ad_group: модель `AdGroup` или словарь с полем `RegionIds`.
        :return: текущий список ID регионов (пустой список, если не задан).
        """
        value = (
            ad_group.get("RegionIds")
            if isinstance(ad_group, dict)
            else getattr(ad_group, "region_ids", None)
        )
        if not value:
            return []
        if isinstance(value, dict):
            items: Iterable[Any] = value.get("Items") or []
        else:
            items = cast(Iterable[Any], value)
        return [int(i) for i in items]

    # ---------------- внутреннее ----------------
    def _available_regions(self, dictionaries: Any) -> List[GeoRegion]:
        """Загрузить справочник регионов страны (без кэша вызывающего кода).

        :param dictionaries: `client.dictionaries`.
        :return: регионы страны селектора.
        :raises ValidationError: если справочник пуст.
        """
        regions = list(dictionaries.geo_regions(self.country_region))
        if not regions:
            raise ValidationError(
                f"Справочник регионов для {self.country_region} пуст — "
                "проверьте доступ к dictionaries"
            )
        return regions

    @staticmethod
    def _index_by_code(regions: Sequence[GeoRegion]) -> Dict[str, int]:
        """Построить индекс по коду региона (символьному и числовому).

        :param regions: регионы справочника.
        :return: словарь код → ID региона.
        """
        index: Dict[str, int] = {}
        for region in regions:
            raw = region.raw
            for key in ("GeoRegionCode", "RegionCode", "Code"):
                value = raw.get(key)
                if value is not None:
                    index.setdefault(str(value).upper(), region.id)
            index.setdefault(str(region.id), region.id)
        return index

    @staticmethod
    def _index_by_name(regions: Sequence[GeoRegion]) -> Dict[str, List[int]]:
        """Построить индекс нормализованных названий → ID регионов.

        :param regions: регионы справочника.
        :return: словарь, где ключ — нормализованное название.
        """
        index: Dict[str, List[int]] = {}
        for region in regions:
            index.setdefault(_normalize(region.name), []).append(region.id)
        return index

    def _resolve_one(
        self,
        ref: RegionRef,
        by_id: Dict[int, GeoRegion],
        by_code: Dict[str, int],
        by_name: Dict[str, List[int]],
    ) -> int:
        """Резолвнуть один элемент списка в ID региона.

        :param ref: ID, код или название региона.
        :param by_id: индекс регионов по ID.
        :param by_code: индекс регионов по коду.
        :param by_name: индекс регионов по названию.
        :return: ID региона.
        :raises ValidationError: значение не найдено или неоднозначно.
        """
        # 1. Числовой ID — единственная форма, которую можно принять «как есть».
        if isinstance(ref, bool):
            raise ValidationError(f"Некорректный регион: {ref!r}")
        if isinstance(ref, int):
            if ref in by_id:
                return ref
            raise ValidationError(
                f"Регион {ref} не найден в справочнике {self.country_region}; "
                f"выдуманные ID использовать нельзя"
            )

        text = str(ref).strip()
        if not text:
            raise ValidationError("Пустое значение в списке регионов")

        # 2. Числовой код (в т.ч. в виде строки) — как ID.
        if text.lstrip("-").isdigit():
            numeric = int(text)
            if numeric in by_id:
                return numeric

        # 3. Символьный код региона.
        code_id = by_code.get(text.upper())
        if code_id is not None:
            return code_id

        # 4. Название региона — строгое совпадение.
        normalized = _normalize(text)
        exact = by_name.get(normalized)
        if exact and len(exact) == 1:
            return exact[0]
        if exact and len(exact) > 1:
            names = [by_id[rid].name for rid in exact if rid in by_id]
            raise ValidationError(
                f"Название {text!r} неоднозначно: подходит {len(exact)} регионов "
                f"({', '.join(sorted(names))}). Уточните запрос, указав ID региона."
            )

        suggestions = _suggest(text, list(by_id.values()))
        hint = f" Возможные совпадения: {'; '.join(suggestions)}." if suggestions else ""
        raise ValidationError(
            f"Регион {text!r} не найден в справочнике {self.country_region}.{hint}"
        )


__all__ = ["RegionRef", "RegionSelector"]
