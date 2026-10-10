"""Тесты этапа 7 STAGE_05: покрытие новых модулей и регрессия (tasks/task04.md, §9).

Смысл этапа — не новые функции, а проверка того, что уже написанные слои
0–5 действительно покрыты mock-тестами, а поведение не поехало:

- **совместимость Python 3.9** — проект объявлен как `requires-python >= 3.9`,
  поэтому синтаксис 3.10+ (`match`, `X | Y` в рантайм-позициях) в пакете
  недопустим; проверяется разбором AST всех модулей;
- **покрытие новых модулей ≥ 90%** — здесь закрываются непокрытые ветки
  `validation`, `models/_helpers`, `models/batch`, `models/stats`,
  `creatives`, `dictionaries`, `retargeting_lists`, `bid_strategy`,
  `campaign_payloads`, `ad_extensions`, `retargeting_conditions`,
  `audience_targets`;
- **регрессия** существующих тестов (весь прогон остаётся зелёным).

Сетевых вызовов здесь нет: всё замокано через `responses`.
"""
from __future__ import annotations

import ast
import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.cache import JsonCache
from yandex_direct_api_client.exceptions import ApiError, ValidationError
from yandex_direct_api_client.models import _helpers
from yandex_direct_api_client.models.batch import BatchResult, ItemFailure
from yandex_direct_api_client.models.bid_strategy import (
    BidStrategy,
    strategy_payload,
    weekly_budget_of,
)
from yandex_direct_api_client.models.campaign_payloads import (
    CpmBannerCampaign,
    TextCampaign,
    build_campaign,
    campaign_payloads,
    campaign_type_of,
)
from yandex_direct_api_client.models.stats import StatRow
from yandex_direct_api_client.services.retargeting_lists import (
    RetargetingListService,
)
from yandex_direct_api_client.validation import (
    Validator,
    cross_entity_checks_enabled,
)

V5 = "https://api.direct.yandex.com/json/v5"
V501 = "https://api.direct.yandex.com/json/v501"
DICTIONARIES_URL_V5 = f"{V5}/dictionaries/"
DICTIONARIES_URL_V501 = f"{V501}/dictionaries/"
CREATIVES_URL = f"{V5}/creatives/"
RETARGETING_URL = f"{V5}/retargetinglists/"
PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "yandex_direct_api_client"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Изолировать дисковый кэш от домашнего каталога пользователя."""
    monkeypatch.setenv("YANDEX_DIRECT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("YANDEX_DIRECT_VALIDATE", raising=False)
    monkeypatch.delenv("YANDEX_DIRECT_CROSS_CHECKS", raising=False)


def _mark() -> int:
    """Отметка начала вызовов вызыванного теста (
esponses.calls общий на сессию)."""
    return len(responses.calls)


def _client(cache: Optional[JsonCache] = None) -> YandexDirectClient:
    """Клиент с тестовыми настройками."""
    kwargs: Dict[str, Any] = {"token": "t", "rate_limit_rps": 1000.0, "max_retries": 1}
    if cache is not None:
        kwargs["cache"] = cache
    return YandexDirectClient(**kwargs)


# ---------------- Python 3.9: синтаксис и рантайм-типы ----------------


def _package_modules() -> List[Path]:
    """Все модули пакета."""
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def test_package_has_modules() -> None:
    """Сбой защиты: список модулей не должен оказаться пустым."""
    assert len(_package_modules()) > 40


def test_no_match_statements() -> None:
    """`match` — синтаксис 3.10+, в пакете недопустим."""
    offenders: List[str] = []
    for path in _package_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Match):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_future_annotations_everywhere() -> None:
    """Все модули импортируют `from __future__ import annotations`.

    Это делает аннотации ленивыми: подписки `Optional[int]`/`Dict[str, Any]`
    не вычисляются в рантайме, а значит не требуют нового синтаксиса.
    """
    missing: List[str] = []
    for path in _package_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        has_future = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in tree.body
        )
        if not has_future:
            missing.append(path.name)
    # `_version.py` — одна строка без аннотаций, исключение допустимо.
    assert missing in ([], ["_version.py"])


def test_no_pep604_in_runtime_positions() -> None:
    """`X | Y` допустим только внутри аннотаций, не в рантайм-выражениях.

    Проверяются `AnnAssign`-аннотации и `TypeAlias`-подобные присваивания:
    при `from __future__ import annotations` они не вычисляются, но
    `TypeAlias`-объявление или вызов вроде `cast(int | None, x)` вычисляется
    и на 3.9 упал бы с `TypeError`.
    """
    offenders: List[str] = []
    for path in _package_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            # Присваивания вида `X = A | B` вычисляются в рантайме.
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.BinOp):
                if isinstance(node.value.op, ast.BitOr):
                    names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                    if "TypeAlias" in names:
                        offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_no_py310_typing_imports() -> None:
    """Нет импортов из 3.10+ (`TypeAlias`, `Self`, `ParamSpec` из 3.10+)."""
    banned = {"TypeAlias", "Self", "TypeGuard", "Concatenate"}
    offenders: List[str] = []
    for path in _package_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "typing"
            ):
                for alias in node.names:
                    if alias.name in banned:
                        offenders.append(f"{path.name}:{alias.name}")
    assert offenders == []


def test_no_py310_builtin_apis() -> None:
    """Нет API из 3.10+, отсутствующих в 3.9."""
    banned_attrs = {"pairwise", "KW_ONLY"}
    offenders: List[str] = []
    for path in _package_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in banned_attrs:
                offenders.append(f"{path.name}:{node.lineno}:{node.attr}")
            # `zip(..., strict=True)` — 3.10+.
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "zip":
                    for kw in node.keywords:
                        if kw.arg == "strict":
                            offenders.append(f"{path.name}:{node.lineno}:zip strict")
    assert offenders == []


def test_cross_entity_checks_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Флаг кросс-сущностных проверок читается из окружения."""
    assert cross_entity_checks_enabled() is False
    for raw in ("1", "true", "YES", "on"):
        monkeypatch.setenv("YANDEX_DIRECT_CROSS_CHECKS", raw)
        assert cross_entity_checks_enabled() is True
    monkeypatch.setenv("YANDEX_DIRECT_CROSS_CHECKS", "0")
    assert cross_entity_checks_enabled() is False


# ---------------- validation: непокрытые ветки ----------------


def test_validator_name_rejects_surrounding_spaces() -> None:
    """Имя с пробелами по краям отвергается."""
    with pytest.raises(ValidationError, match="пробел"):
        Validator(True).name(" Имя", field="Name")


def test_validator_name_disabled() -> None:
    """Выключенный валидатор не проверяет ничего."""
    Validator(False).name("  ", field="Name")
    Validator(False).text(None, field="Text", max_length=10, required=True)
    Validator(False).ids(None, field="Ids")
    Validator(False).region_ids(None)
    Validator(False).positive_amount(-5, field="Amount")
    Validator(False).href("ftp://example.com")
    Validator(False).one_of("что-то", ("a", "b"), field="Enum")
    Validator(False).date_range(_dt.date(2030, 1, 1), _dt.date(2020, 1, 1))


def test_validator_text_required_and_optional() -> None:
    """`text`: обязательность и лимит длины."""
    v = Validator(True)
    with pytest.raises(ValidationError, match="обязателен"):
        v.text("  ", field="Title", max_length=10)
    v.text(None, field="Title", max_length=10, required=False)
    with pytest.raises(ValidationError, match="длиннее"):
        v.text("x" * 11, field="Title", max_length=10)


def test_validator_ids_none_and_allow_empty() -> None:
    """`ids`: None обязателен, если не разрешён пустой список."""
    v = Validator(True)
    with pytest.raises(ValidationError, match="обязателен"):
        v.ids(None, field="Ids")
    v.ids(None, field="Ids", allow_empty=True)
    with pytest.raises(ValidationError, match="не может быть пустым"):
        v.ids([], field="Ids")
    v.ids([], field="Ids", allow_empty=True)


def test_validator_region_ids_none_and_types() -> None:
    """`region_ids`: None и нецелые значения отвергаются."""
    v = Validator(True)
    with pytest.raises(ValidationError, match="обязателен"):
        v.region_ids(None)
    with pytest.raises(ValidationError, match="целые ID"):
        v.region_ids(["Москва"])
    with pytest.raises(ValidationError, match="целые ID"):
        v.region_ids([True])
    v.region_ids([-219])  # отрицательные ID допустимы


def test_validator_positive_amount_types() -> None:
    """`positive_amount`: строки и нули отвергаются."""
    v = Validator(True)
    with pytest.raises(ValidationError, match="ожидается число"):
        v.positive_amount("100", field="Amount")
    with pytest.raises(ValidationError, match="больше нуля"):
        v.positive_amount(0, field="Amount")
    v.positive_amount(0, field="Amount", allow_zero=True)
    with pytest.raises(ValidationError, match="больше нуля"):
        v.positive_amount(-1, field="Amount")
    v.positive_amount(None, field="Amount")


def test_validator_date_range_types() -> None:
    """`date_range`: типы дат проверяются явно."""
    v = Validator(True)
    v.date_range(None, None)
    with pytest.raises(ValidationError, match="StartDate"):
        v.date_range("2026-01-01", None)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="EndDate"):
        v.date_range(_dt.date(2026, 1, 1), "2026-02-01")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="позже"):
        v.date_range(_dt.date(2026, 2, 1), _dt.date(2026, 1, 1))


def test_validator_href_and_one_of() -> None:
    """`href` пропускает None, но отвергает мусор; `one_of` сверяет enum."""
    v = Validator(True)
    v.href(None)
    with pytest.raises(ValidationError, match="пустым"):
        v.href("   ")
    with pytest.raises(ValidationError, match="http"):
        v.href("example.com")
    v.href("http://example.com", field="Href")
    with pytest.raises(ValidationError, match="недопустимо"):
        v.one_of("WRONG", ("A", "B"), field="Enum")
    v.one_of(None, ("A", "B"), field="Enum")


# ---------------- models/_helpers: конвертация значений API ----------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 0),
        ("42", 42),
        (7, 7),
        ("не число", 0),
        (None, 5),
    ],
)
def test_helpers_to_int(raw: Any, expected: int) -> None:
    """`to_int` не падает на мусоре — отдаёт значение по умолчанию."""
    assert _helpers.to_int(raw, default=0 if expected != 5 else 5) == expected


def test_helpers_to_float() -> None:
    """`to_float` понимает запятую как десятичный разделитель."""
    assert _helpers.to_float("1,5") == 1.5
    assert _helpers.to_float(2) == 2.0
    assert _helpers.to_float(None) == 0.0
    assert _helpers.to_float(None, default=-1.0) == -1.0
    assert _helpers.to_float("--") == 0.0
    assert _helpers.to_float("") == 0.0
    assert _helpers.to_float("не число", default=3.0) == 3.0


def test_helpers_to_str_and_dates() -> None:
    """`to_str`, `to_date`, `to_optional_int`."""
    assert _helpers.to_str(None) == ""
    assert _helpers.to_str(5) == "5"
    assert _helpers.to_str(None, default="н/д") == "н/д"
    assert _helpers.to_date("2026-10-01") == _dt.date(2026, 10, 1)
    assert _helpers.to_date("") is None
    assert _helpers.to_date("не дата") is None
    assert _helpers.to_optional_int(None) is None
    assert _helpers.to_optional_int("8") == 8
    assert _helpers.to_optional_int("мусор") is None


def test_helpers_to_bool() -> None:
    """`to_bool` понимает и числа, и строки API."""
    assert _helpers.to_bool(None) is False
    assert _helpers.to_bool(None, default=True) is True
    assert _helpers.to_bool(True) is True
    assert _helpers.to_bool(1) is True
    assert _helpers.to_bool(0) is False
    assert _helpers.to_bool(2.5) is True
    for text in ("true", "YES", "1"):
        assert _helpers.to_bool(text) is True
    for text in ("false", "no", "0", ""):
        assert _helpers.to_bool(text) is False
    assert _helpers.to_bool("неизвестно", default=True) is True


# ---------------- models/batch: BatchResult и ItemFailure ----------------


def test_batch_result_dunders_and_helpers() -> None:
    """`BatchResult` ведёт себя как коллекция успешных элементов."""
    result = BatchResult(
        succeeded=[{"Id": 1}, {"Id": 2}],
        failed=[ItemFailure(message="ошибка", code="X", object_id=1, request_id="r")],
    )
    assert len(result) == 2
    assert [item["Id"] for item in result] == [1, 2]
    assert bool(result) is True
    assert result.has_failures is True
    assert result.ids() == [1, 2]
    assert BatchResult().has_failures is False
    assert bool(BatchResult()) is False
    assert list(BatchResult()) == []


def test_item_failure_str_without_optional_fields() -> None:
    """`str(ItemFailure)` работает и без необязательных полей."""
    assert str(ItemFailure(message="только текст")) == "только текст"
    assert "code=42" in str(ItemFailure(message="m", code="42"))
    assert "id=7" in str(ItemFailure(message="m", code="42", object_id=7))


# ---------------- models/stats: слияние строк ----------------


def test_stat_row_from_tsv_row() -> None:
    """Разбор строки TSV: микрорубли переводятся в рубли."""
    row = StatRow.from_tsv_row(
        ["10", "100", "5", "5,00", "25000000", "20", "1"]
    )
    assert row is not None
    assert row.ad_id == 10
    assert row.impressions == 100
    assert row.clicks == 5
    assert row.ctr == 5.0
    assert row.cost == 25.0
    assert row.bounce_rate == 20.0
    assert row.bounces == 1


def test_stat_row_from_tsv_row_short_and_invalid() -> None:
    """Короткая строка и нечисловой AdId дают None, а не исключение."""
    assert StatRow.from_tsv_row(["1", "2"]) is None
    assert StatRow.from_tsv_row(["мусор", "1", "2", "3", "4"]) is None
    minimal = StatRow.from_tsv_row(["7", "1", "0", "0", "0"])
    assert minimal is not None
    assert minimal.bounce_rate == 0.0
    assert minimal.bounces == 0


def test_stat_row_from_tsv_row_by_header() -> None:
    """Порядок колонок задаётся заголовком, недостающие — дефолтные."""
    header = ["Clicks", "AdId", "Cost"]
    row = StatRow.from_tsv_row_by_header(["10", "42", "1000000"], header)
    assert row is not None
    assert row.ad_id == 42
    assert row.clicks == 10
    assert row.cost == 1.0
    assert row.impressions == 0
    assert row.bounce_rate == 0.0
    single = StatRow.from_tsv_row_by_header(["10"], ["AdId"])
    assert single is not None and single.ad_id == 10
    assert StatRow.from_tsv_row_by_header(["мусор"], ["AdId"]) is None
    assert StatRow.from_tsv_row_by_header(["42"], ["Clicks"]) is None


def test_stat_row_merged_with() -> None:
    """Слияние строк: CTR и bounce_rate считаются заново, а не суммируются."""
    first = StatRow(
        ad_id=10, impressions=100, clicks=5, ctr=1.0, cost=10.0,
        bounce_rate=20.0, bounces=1,
    )
    second = StatRow(
        ad_id=10, impressions=100, clicks=15, ctr=3.0, cost=30.0,
        bounce_rate=40.0, bounces=3,
    )
    merged = first.merged_with(second)
    assert merged.ad_id == 10
    assert merged.impressions == 200
    assert merged.clicks == 20
    assert merged.ctr == 10.0
    assert merged.cost == 40.0
    assert merged.bounces == 4
    assert merged.bounce_rate == 20.0


def test_stat_row_merged_with_zero_denominators() -> None:
    """Слияние не делит на ноль."""
    empty = StatRow(ad_id=1)
    merged = empty.merged_with(StatRow(ad_id=1, impressions=0, clicks=0))
    assert merged.ctr == 0.0
    assert merged.bounce_rate == 0.0


# ---------------- creatives: ветки валидации и фильтров ----------------


def _creatives_client(cache: JsonCache) -> YandexDirectClient:
    """Клиент для сервиса креативов."""
    return _client(cache)


@responses.activate
def test_creatives_get_validates_types_before_request(tmp_path: Path) -> None:
    """Неизвестный тип креатива отвергается без сетевого вызова."""
    cache = JsonCache(cache_dir=tmp_path / "cache")

    mark = _mark()

    with _creatives_client(cache) as client:
        with pytest.raises(ValidationError):
            client.creatives.get(types=["НЕТ_ТАКОГО"])
    assert _mark() == mark


@responses.activate
def test_creatives_image_creative_ids_filtered_by_name(tmp_path: Path) -> None:
    """`image_creative_ids` фильтрует по имени и пропускает чужие."""
    responses.add(
        responses.POST,
        CREATIVES_URL,
        json={
            "result": {
                "Creatives": [
                    {"Id": 1, "Type": "IMAGE_CREATIVE", "Name": "нужный"},
                    {"Id": 2, "Type": "IMAGE_CREATIVE", "Name": "чужой"},
                    {"Id": 3, "Type": "IMAGE_CREATIVE"},
                ]
            }
        },
    )
    cache = JsonCache(cache_dir=tmp_path / "cache")

    with _creatives_client(cache) as client:
        assert client.creatives.image_creative_ids(names=["нужный"]) == [1]
        assert client.creatives.image_creative_ids() == [1, 2, 3]


@responses.activate
def test_creatives_image_creative_ids_rejects_bad_id(tmp_path: Path) -> None:
    """Строковый `Id` у креатива — ошибка ответа, а не молчаливое пропускание."""
    responses.add(
        responses.POST,
        CREATIVES_URL,
        json={"result": {"Creatives": [{"Id": "abc", "Name": "битый"}]}},
    )
    cache = JsonCache(cache_dir=tmp_path / "cache")

    with _creatives_client(cache) as client:
        with pytest.raises(ValidationError, match="Id"):
            client.creatives.image_creative_ids(names=["битый"])


@responses.activate
def test_creatives_get_chunks_large_id_list(tmp_path: Path) -> None:
    """Большой список ID разбивается на чанки."""
    for _ in range(3):
        responses.add(
            responses.POST, CREATIVES_URL, json={"result": {"Creatives": []}}
        )
    cache = JsonCache(cache_dir=tmp_path / "cache")

    with _creatives_client(cache) as client:
        client.creatives.get(ids=list(range(1, 25001)))
    assert len(responses.calls) == 3
    for call in responses.calls:
        criteria = json.loads(call.request.body)["params"]["SelectionCriteria"]
        assert len(criteria["Ids"]) <= 10000


# ---------------- dictionaries: справочники без кэша и ошибки формата ----------------


@responses.activate
def test_dictionaries_geo_hierarchy_empty_ids(tmp_path: Path) -> None:
    """Пустой список ID не вызывает API."""
    cache = JsonCache(cache_dir=tmp_path / "cache")

    mark = _mark()

    with _client(cache) as client:
        assert client.dictionaries.geo_hierarchy([]) == []
    assert _mark() == mark


@responses.activate
def test_dictionaries_keywords_rejects_blank(tmp_path: Path) -> None:
    """Пустая фраза для `getKeywords` отвергается до сети."""
    cache = JsonCache(cache_dir=tmp_path / "cache")

    mark = _mark()

    with _client(cache) as client:
        with pytest.raises(ApiError):
            client.dictionaries.keywords("   ")
    assert _mark() == mark


@responses.activate
def test_dictionaries_keywords_passes_geo_and_ad_types(tmp_path: Path) -> None:
    """`geo_ids` и `ad_types` попадают в тело запроса."""
    responses.add(
        responses.POST, DICTIONARIES_URL_V5, json={"result": {"Keywords": ["купить"]}}
    )
    cache = JsonCache(cache_dir=tmp_path / "cache")

    with _client(cache) as client:
        result = client.dictionaries.keywords(
            "купить", geo_ids=[225], ad_types=["TEXT_AD"]
        )
    assert result["Keywords"] == ["купить"]
    params = json.loads(responses.calls[0].request.body)["params"]["getKeywords"]
    assert params == {
        "Keyword": "купить",
        "GeoIds": [225],
        "AdTypes": ["TEXT_AD"],
    }


@responses.activate
def test_dictionaries_simple_lists(tmp_path: Path) -> None:
    """Типовые справочники: сайты, типы объявлений, часовые пояса, Bing (v5)."""
    cache = JsonCache(cache_dir=tmp_path / "cache")

    with _client(cache) as client:
        responses.add(
            responses.POST,
            DICTIONARIES_URL_V5,
            json={"result": {"Sites": [{"Id": 1, "Name": "site", "Url": "https://s"}]}},
        )
        assert [s.name for s in client.dictionaries.sites()] == ["site"]

        responses.add(
            responses.POST,
            DICTIONARIES_URL_V5,
            json={
                "result": {
                    "AdTypes": [{"AdType": "TEXT_AD", "Name": "Текстовое",
                                 "AdGroupType": "TEXT_AD_GROUP"}]
                }
            },
        )
        assert client.dictionaries.ad_types()[0].ad_type == "TEXT_AD"

        responses.add(
            responses.POST,
            DICTIONARIES_URL_V501,
            json={
                "result": {
                    "TimeZones": [
                        {"TimeZone": "Europe/Moscow", "Offset": 3, "TimeZoneId": 1}
                    ]
                }
            },
        )
        assert client.dictionaries.time_zones()[0].name == "Europe/Moscow"

        responses.add(
            responses.POST,
            DICTIONARIES_URL_V5,
            json={"result": {"BingTypes": [{"BingType": "X", "Name": "Икс"}]}},
        )
        assert client.dictionaries.bing_types()[0]["Name"] == "Икс"


@responses.activate
def test_dictionaries_currency_rejects_bad_payload(tmp_path: Path) -> None:
    """Некорректный ответ `getCurrency` даёт `ApiError`, а не пустую модель."""
    cache = JsonCache(cache_dir=tmp_path / "cache")

    with _client(cache) as client:
        responses.add(responses.POST, DICTIONARIES_URL_V501, json={"result": {}})
        with pytest.raises(ApiError, match="Currencies"):
            client.dictionaries.currency()

        responses.add(
            responses.POST,
            DICTIONARIES_URL_V501,
            json={"result": {"Currencies": ["не словарь"]}},
        )
        with pytest.raises(ApiError, match="пустой список"):
            client.dictionaries.currency()


@responses.activate
def test_dictionaries_audience_missing_list_raises(tmp_path: Path) -> None:
    """Справочник аудитории без ожидаемого списка — `ApiError`."""
    responses.add(responses.POST, DICTIONARIES_URL_V501, json={"result": {}})
    cache = JsonCache(cache_dir=tmp_path / "cache")

    with _client(cache) as client:
        with pytest.raises(ApiError, match="AudienceInterests"):
            client.dictionaries.audience_interests(use_cache=False)


@responses.activate
def test_dictionaries_dicts_escape_hatch(tmp_path: Path) -> None:
    """`dicts` — выход к любому справочнику, включая свой парсер (v5 по умолчанию)."""
    cache = JsonCache(cache_dir=tmp_path / "cache")

    with _client(cache) as client:
        responses.add(
            responses.POST,
            DICTIONARIES_URL_V5,
            json={"result": {"SomeList": [{"Id": 1}]}},
        )
        raw = client.dictionaries.dicts("getSomethingNew")
        assert raw[0].key == "SomeList"
        assert raw[0].values == [{"Id": 1}]

        responses.add(
            responses.POST,
            DICTIONARIES_URL_V5,
            json={"result": {"SomeList": [{"Id": 2}]}},
        )
        parsed = client.dictionaries.dicts(
            "getSomethingNew", parser=lambda result: result["SomeList"]
        )
        assert parsed == [{"Id": 2}]


# ---------------- retargeting_lists: кэш, фильтры, ошибки ----------------


def _rl_client(tmp_path: Path) -> YandexDirectClient:
    """Клиент для сервиса сегментов."""
    return _client(JsonCache(cache_dir=tmp_path / "cache"))


@responses.activate
def test_retargeting_lists_filters_by_type(tmp_path: Path) -> None:
    """Фильтр Types уходит в SelectionCriteria."""
    responses.add(
        responses.POST,
        RETARGETING_URL,
        json={
            "result": {
                "RetargetingLists": [
                    {
                        "Id": 1,
                        "Name": "сегмент",
                        "Type": "AUDIENCE",
                        "Rules": [{"Operator": "ANY", "Arguments": [{"ExternalId": 1}]}],
                    }
                ]
            }
        },
    )

    mark = _mark()

    with _rl_client(tmp_path) as client:
        lists = client.retargeting_lists.get(types=["AUDIENCE"])
    assert [item.id for item in lists] == [1]
    criteria = json.loads(responses.calls[mark].request.body)["params"][
        "SelectionCriteria"
    ]
    assert criteria == {"Types": ["AUDIENCE"]}


@responses.activate
def test_retargeting_lists_rejects_unknown_type(tmp_path: Path) -> None:
    """Неизвестный тип сегмента отвергается без сети."""

    mark = _mark()

    with _rl_client(tmp_path) as client:
        with pytest.raises(ValidationError, match="Types"):
            client.retargeting_lists.get(types=["НЕТРАКОГО"])
    assert _mark() == mark


@responses.activate
def test_retargeting_lists_list_for_group_type_filters_client_side(
    tmp_path: Path,
) -> None:
    """
    Сегменты отбираются по AvailableForTargetsInAdGroupTypes
    на стороне клиента: достаточный
    Type обязан быть пустым в SelectionCriteria.
    """
    responses.add(
        responses.POST,
        RETARGETING_URL,
        json={
            "result": {
                "RetargetingLists": [
                    {
                        "Id": 1,
                        "Name": "для МОСКВА",
                        "Type": "AUDIENCE",
                        "AvailableForTargetsInAdGroupTypes": ["CPM_BANNER_AD_GROUP"],
                        "Rules": [{"Operator": "ANY", "Arguments": [{"ExternalId": 1}]}],
                    },
                    {
                        "Id": 2,
                        "Name": "для только поиска",
                        "Type": "AUDIENCE",
                        "AvailableForTargetsInAdGroupTypes": ["TEXT_AD_GROUP"],
                        "Rules": [{"Operator": "ANY", "Arguments": [{"ExternalId": 1}]}],
                    },
                    {
                        "Id": 3,
                        "Name": "без ограничений",
                        "Type": "AUDIENCE",
                        "Rules": [{"Operator": "ANY", "Arguments": [{"ExternalId": 1}]}],
                    },
                ]
            }
        },
    )

    mark = _mark()

    with _rl_client(tmp_path) as client:
        lists = client.retargeting_lists.list_for_group_type("CPM_BANNER_AD_GROUP")
    assert [item.id for item in lists] == [1, 3]
    criteria = json.loads(responses.calls[mark].request.body)["params"][
        "SelectionCriteria"
    ]
    assert "AvailableForTargetsInAdGroupTypes" not in criteria


@responses.activate
def test_retargeting_lists_update_requires_confirm(tmp_path: Path) -> None:
    """Массовое обновление требует confirm=True."""

    mark = _mark()

    with _rl_client(tmp_path) as client:
        with pytest.raises(ValidationError, match="confirm"):
            client.retargeting_lists.update(
                [{"Id": 1, "Name": "s", "Type": "AUDIENCE"}]
            )
    assert _mark() == mark


@responses.activate
def test_retargeting_lists_delete_requires_confirm(tmp_path: Path) -> None:
    """Удаление сегментов требует confirm=True."""

    mark = _mark()

    with _rl_client(tmp_path) as client:
        with pytest.raises(ValidationError, match="confirm"):
            client.retargeting_lists.delete([1])
    assert _mark() == mark


def test_retargeting_lists_update_requires_id(tmp_path: Path) -> None:
    """Без Id убудьть нельзя обновить."""
    with _rl_client(tmp_path) as client:
        with pytest.raises(ValidationError, match="Id"):
            client.retargeting_lists.update(
                [{"Name": "s", "Type": "AUDIENCE"}], confirm=True
            )


@responses.activate
def test_retargeting_lists_create_audience_segment_payload(tmp_path: Path) -> None:
    """create_audience_segment только собирает тело и ничего не отправляет."""

    mark = _mark()

    with _rl_client(tmp_path) as client:
        payload = client.retargeting_lists.create_audience_segment(
            "Мужчины 25-34", [202, 101]
        )
        with pytest.raises(ValidationError, match="ExternalId"):
            client.retargeting_lists.create_audience_segment("пустой", [])
        with pytest.raises(ValidationError, match="ANY"):
            client.retargeting_lists.create_audience_segment(
                "x", [1], operator="ВЫДУМАННЫЙ"
            )
    assert payload["Type"] == "AUDIENCE"
    assert payload["Rules"][0]["Operator"] == "ANY"
    assert payload["Rules"][0]["Arguments"] == [
        {"ExternalId": 202},
        {"ExternalId": 101},
    ]
    assert _mark() == mark


@responses.activate
def test_retargeting_lists_collect_mode_reports_failures(tmp_path: Path) -> None:
    """on_item_error="collect" возвращает частичный результат."""
    responses.add(
        responses.POST,
        RETARGETING_URL,
        json={
            "result": {
                "AddResults": [
                    {"Id": 1},
                    {
                        "Id": 0,
                        "Errors": [
                            {
                                "Code": "RULES_TOO_MANY",
                                "Message": "слишком ного правил",
                                "Details": "d",
                            }
                        ],
                    },
                ]
            }
        },
    )

    with _rl_client(tmp_path) as client:
        result = client.retargeting_lists.create(
            [
                {
                    "Name": "ok",
                    "Type": "AUDIENCE",
                    "Rules": [{"Operator": "ANY", "Arguments": [{"ExternalId": 1}]}],
                },
                {
                    "Name": "bad",
                    "Type": "AUDIENCE",
                    "Rules": [{"Operator": "ANY", "Arguments": [{"ExternalId": 2}]}],
                },
            ],
            on_item_error="collect",
        )
    assert isinstance(result, BatchResult)
    assert result.ids() == [1]
    assert result.failed[0].code == "RULES_TOO_MANY"


@responses.activate
def test_retargeting_lists_raise_mode_raises(tmp_path: Path) -> None:
    """По умолчанию обычный результат бросается."""
    responses.add(
        responses.POST,
        RETARGETING_URL,
        json={
            "result": {
                "AddResults": [
                    {
                        "Id": 0,
                        "Errors": [{"Code": "X", "Message": "нельзя"}],
                    }
                ]
            }
        },
    )
    with _rl_client(tmp_path) as client:
        with pytest.raises(ApiError):
            client.retargeting_lists.create(
                [{"Name": "x", "Type": "AUDIENCE", "Rules": []}]
            )


def test_retargeting_lists_service_is_exported() -> None:
    """Сервис сегментов доступен и как класс — для подмены в тестах."""
    assert RetargetingListService.__name__ == "RetargetingListService"


# ---------------- bid_strategy: стратегии и недельные бюджеты ----------------


def test_bid_strategy_weekly_spend_limit_in_units() -> None:
    """Недельный бюджет доступен в единицах API (×1 000 000)."""
    assert BidStrategy(strategy="MANUAL_CPM", weekly_budget=500).weekly_spend_limit == (
        500_000_000
    )
    assert BidStrategy(strategy="HIGHEST_POSITION").weekly_spend_limit is None


def test_bid_strategy_to_payload_requires_weekly_budget() -> None:
    """Стратегия с обязательным бюджетом требует его при сборке payload."""
    strategy = BidStrategy(strategy="WB_MAXIMUM_CLICKS")
    with pytest.raises(ValidationError, match="недельный бюджет"):
        strategy.to_payload()
    # `require_fields=False` — бюджет задаётся отдельно (методы обновления).
    assert strategy.to_payload(require_fields=False) == {}


def test_bid_strategy_requires_goal_and_cpc() -> None:
    """Цели и ставка `AVERAGE_CPC` обязательны там, где это требует API."""
    with pytest.raises(ValidationError, match="goal_id"):
        BidStrategy(strategy="AVERAGE_CPA", weekly_budget=1).to_payload()
    with pytest.raises(ValidationError, match="average_cpc"):
        BidStrategy(strategy="AVERAGE_CPC", weekly_budget=1).to_payload()
    payload = BidStrategy(
        strategy="AVERAGE_CPC", weekly_budget=1, average_cpc=2, bid_ceiling=3
    ).to_payload()
    assert payload == {
        "WeeklySpendLimit": 1_000_000,
        "AverageCpc": 2_000_000,
        "BidCeiling": 3_000_000,
    }


def test_bid_strategy_rejects_unknown_type_and_bad_ids() -> None:
    """Неизвестный тип стратегии и некорректные ID отвергаются сразу."""
    with pytest.raises(ValidationError, match="BidStrategy.strategy"):
        BidStrategy(strategy="ВЫДУМАННАЯ")
    with pytest.raises(ValidationError, match="goal_id"):
        BidStrategy(strategy="AVERAGE_CPA", weekly_budget=1, goal_id=0)
    with pytest.raises(ValidationError, match="weekly_budget"):
        BidStrategy(strategy="MANUAL_CPM", weekly_budget=0)


def test_bid_strategy_extra_is_escape_hatch() -> None:
    """Неизвестные поля стратегии уходят в payload через `extra`."""
    payload = strategy_payload(
        BidStrategy(strategy="HIGHEST_POSITION", extra={"NewField": 1})
    )
    assert payload == {"BiddingStrategyType": "HIGHEST_POSITION", "NewField": 1}


def test_strategy_payload_accepts_plain_dict() -> None:
    """Словарь — допустимый escape-hatch вместо модели."""
    assert strategy_payload({"BiddingStrategyType": "SERVING_OFF"}) == {
        "BiddingStrategyType": "SERVING_OFF"
    }
    with pytest.raises(ValidationError, match="BidStrategy или dict"):
        strategy_payload("AVERAGE_CPC")  # type: ignore[arg-type]


def test_bid_strategy_from_dict_and_parse() -> None:
    """Разбор стратегии из ответа API и деньги обратно в Decimal."""
    strategy = BidStrategy.from_dict(
        {
            "BiddingStrategyType": "AVERAGE_CPC",
            "WeeklySpendLimit": 1_000_000,
            "AverageCpc": 2_000_000,
            "UnknownField": 7,
        }
    )
    assert strategy.strategy == "AVERAGE_CPC"
    assert strategy.weekly_spend_limit == 1_000_000
    assert strategy.extra == {"UnknownField": 7}
    assert BidStrategy.parse(None) is None
    assert BidStrategy.parse({"BiddingStrategyType": "HIGHEST_POSITION"}) is not None
    with pytest.raises(ValidationError, match="пуста"):
        BidStrategy.from_dict(None)
    with pytest.raises(ValidationError, match="BiddingStrategyType"):
        BidStrategy.from_dict({"WeeklySpendLimit": 1})


def test_weekly_budget_of_variants() -> None:
    """`weekly_budget_of` ищет бюджет на любом уровне секции стратегии."""
    from decimal import Decimal

    assert weekly_budget_of(None) is None
    assert weekly_budget_of({}) is None
    assert weekly_budget_of({"WeeklySpendLimit": 1_500_000}) == Decimal("1.500000")
    assert weekly_budget_of(
        {"AverageCpc": {"WeeklySpendLimit": 2_000_000}}
    ) == Decimal("2.000000")
    assert weekly_budget_of({"AverageCpc": {"AverageCpc": 1}}) is None


# ---------------- campaign_payloads: хелперы и необходные ветки ----------------


def test_campaign_type_of_and_build_campaign() -> None:
    """Определение типа кампании по классу-билдеру."""
    cpm = CpmBannerCampaign(start_date=_dt.date(2026, 10, 2), name="Кампания 1", weekly_budget=1)
    text = TextCampaign(start_date=_dt.date(2026, 10, 2), name="Кампания 2", weekly_budget=1)
    assert campaign_type_of(cpm) == "CPM_BANNER_CAMPAIGN"
    assert campaign_type_of(text) == "TEXT_CAMPAIGN"
    built = build_campaign("TEXT_CAMPAIGN", start_date=_dt.date(2026, 10, 2), name="Кампания 3", weekly_budget=1)
    assert built.to_payload()["TextCampaign"]


def test_build_campaign_rejects_unknown_kind() -> None:
    """Неизвестный тип кампании отвергается со списком доступных."""
    with pytest.raises(ValidationError, match="Неизвестный тип кампании"):
        build_campaign("SMART_CAMPAIGN", start_date=_dt.date(2026, 10, 2), name="x", weekly_budget=1)


def test_campaign_payloads_validates_each_builder() -> None:
    """Пакетная сборка валидирует каждый билдер."""
    payloads = campaign_payloads(
        [CpmBannerCampaign(start_date=_dt.date(2026, 10, 2), name="A", weekly_budget=1), TextCampaign(start_date=_dt.date(2026, 10, 2), name="B", weekly_budget=2)]
    )
    assert len(payloads) == 2
    with pytest.raises(ValidationError):
        campaign_payloads([CpmBannerCampaign(start_date=_dt.date(2026, 10, 2), name="A")])


def test_text_campaign_network_enabled_switches_strategy() -> None:
    """У текстовой кампании сеть включается явно."""
    payload = TextCampaign(
        start_date=_dt.date(2026, 10, 2),
        name="B",
        weekly_budget=1,
        network_enabled=True,
    ).to_payload()
    assert payload["TextCampaign"]["BiddingStrategy"]["Network"][
        "BiddingStrategyType"
    ] == "MAX_CPM"


def test_text_campaign_network_default_warns(caplog) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        payload = TextCampaign(
            name="B", start_date=_dt.date(2026, 10, 2), weekly_budget=700
        ).to_payload()
    assert payload["TextCampaign"]["BiddingStrategy"]["Network"]["BiddingStrategyType"] == "SERVING_OFF"
    assert any("network_enabled не задан" in r.message for r in caplog.records)


def test_text_campaign_network_explicit_no_warn(caplog) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        TextCampaign(
            name="B", start_date=_dt.date(2026, 10, 2),
            weekly_budget=700, network_enabled=False,
        ).to_payload()
    assert not [r for r in caplog.records if "network_enabled не задан" in r.message]


def test_daily_budget_default_mode_warns(caplog) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        payload = CpmBannerCampaign(
            name="R", start_date=_dt.date(2026, 10, 2),
            weekly_budget=1, daily_budget=10,
        ).to_payload()
    assert payload["DailyBudget"]["Mode"] == "STANDARD"
    assert any("daily_budget_mode — SDK выбирает режим STANDARD" in r.message for r in caplog.records)


def test_daily_budget_explicit_mode_no_warn(caplog) -> None:
    with caplog.at_level("WARNING", logger="yandex_direct_api_client.models.campaign_payloads"):
        CpmBannerCampaign(
            name="R", start_date=_dt.date(2026, 10, 2),
            weekly_budget=1, daily_budget=10, daily_budget_mode="DISTRIBUTED",
        ).to_payload()
    assert not [r for r in caplog.records if "daily_budget_mode" in r.message]
    """Готовая секция стратегии — escape-hatch вместо недельного бюджета."""
    campaign = CpmBannerCampaign(
        start_date=_dt.date(2026, 10, 2),
        name="A",
        bidding_strategy={"BiddingStrategyType": "CP_MAXIMUM_IMPRESSIONS"},
    )
    payload = campaign.to_payload()
    network = payload["CpmBannerCampaign"]["BiddingStrategy"]["Network"]
    assert network["BiddingStrategyType"] == "CP_MAXIMUM_IMPRESSIONS"
    with pytest.raises(ValidationError, match="не оба"):
        CpmBannerCampaign(
            start_date=_dt.date(2026, 10, 2),
            name="A",
            weekly_budget=1,
            bidding_strategy={"BiddingStrategyType": "MANUAL_CPM"},
        ).to_payload()
    with pytest.raises(ValidationError, match="недельный бюджет"):
        CpmBannerCampaign(start_date=_dt.date(2026, 10, 2), name="A").to_payload()


def test_campaign_extra_fields_are_merged() -> None:
    """`extra` подмешивается, но не перетирает явные поля."""
    payload = CpmBannerCampaign(
        start_date=_dt.date(2026, 10, 2),
        name="A",
        weekly_budget=1,
        extra={"Name": "перетирать", "Custom": 1},
    ).to_payload()
    assert payload["Name"] == "A"
    assert payload["Custom"] == 1


def test_campaign_requires_start_date_on_create() -> None:
    """При создании `StartDate` обязателен, при обновлении — нет."""
    without_start = CpmBannerCampaign(name="A", weekly_budget=1)
    with pytest.raises(ValidationError, match="StartDate"):
        without_start.to_payload()
    update = without_start.to_update_payload(7)
    assert update["Id"] == 7
    assert "StartDate" not in update
    payload = CpmBannerCampaign(
        start_date=_dt.date(2026, 10, 2), name="A", weekly_budget=1
    ).to_payload()
    assert payload["StartDate"] == "2026-10-02"


def test_campaign_invalid_settings_and_counters() -> None:
    """Настройки и счётчики проверяются по документации."""
    start = _dt.date(2026, 10, 2)
    with pytest.raises(ValidationError, match="Settings.Option"):
        CpmBannerCampaign(
            start_date=start,
            name="A",
            weekly_budget=1,
            settings=[{"Option": "НЕТ_ТАКОГО", "Value": "YES"}],
        ).to_payload()
    with pytest.raises(ValidationError, match="Settings.Value"):
        CpmBannerCampaign(
            start_date=start,
            name="A",
            weekly_budget=1,
            settings=[{"Option": "ADD_METRICA_TAG", "Value": "?"}],
        ).to_payload()
    with pytest.raises(ValidationError, match="CounterIds"):
        CpmBannerCampaign(
            start_date=start, name="A", weekly_budget=1, counter_ids=[0]
        ).to_payload()
    with pytest.raises(ValidationError, match="VideoTarget"):
        CpmBannerCampaign(
            start_date=start, name="A", weekly_budget=1, video_target="НЕТ"
        ).to_payload()
    with pytest.raises(ValidationError, match="ExcludedSitesForVideoAds"):
        CpmBannerCampaign(
            start_date=start,
            name="A",
            weekly_budget=1,
            excluded_sites_for_video_ads=["x" * 300],
        ).to_payload()


def test_text_campaign_counter_ids_validation() -> None:
    """Счётчики текстовой кампании тоже валидируются."""
    with pytest.raises(ValidationError, match="CounterIds"):
        TextCampaign(
            start_date=_dt.date(2026, 10, 2),
            name="B",
            weekly_budget=1,
            counter_ids=[-1],
        ).to_payload()


def test_daily_budget_modes_validated() -> None:
    """`DailyBudgetMode` ограничен двумя значениями."""
    with pytest.raises(ValidationError, match="DailyBudget.Mode"):
        CpmBannerCampaign(
            name="A", daily_budget=1, daily_budget_mode="БЫСТРО"
        ).validate()


# ---------------- регрессия: слои 0–5 ----------------


def test_regression_v501_and_v5_split() -> None:
    """Регрессия: `v501` используется только там, где нужно, `v5` — нет."""
    from yandex_direct_api_client.config import API_VERSION_V501

    assert API_VERSION_V501 == "v501"

    with _client() as client:
        assert client.ads is not None
        assert client.campaigns is not None
