# STAGE_03 — Отчёт

## 1. Что реализовано

Полноценная работа с Reports API Yandex Direct поверх архитектуры этапов 1–2:

- **Универсальный метод `client.reports.get()`** — любой тип отчёта, любые
  поля, периоды, фильтры, сортировка, цели, модели атрибуции, НДС/скидка,
  лимит строк, per-call таймаут.
- **Типизированные обёртки** для стандартных отчётов: `account_stats`,
  `campaign_stats`, `ad_group_stats`, `criteria_stats`, `search_queries`.
- **Типизированные модели отчёта**: `ReportFilter`, `ReportOrder`,
  `ReportRow`, `ReportResult` (экспорт в dict/CSV/JSON/pandas).
- **Авто-разбиение больших запросов**: чанкинг ID-фильтров по 1000,
  разбиение длинных периодов на окна дат (`max_days`).
- **Async-отчёты**: polling 202/PROGRESS по `Retry-In` до готовности,
  таймаут, retry 429, преобразование ошибок — всё в едином retry-слое.
- **Обратная совместимость**: `get_ad_stats()` сохранён, но теперь это
  обёртка над `get()` (один путь выполнения), и исправлена передача
  ID-фильтров (через `SelectionCriteria.Filter` по спецификации v5).

Клиент только возвращает данные — никакой маркетинговой логики
(`disable_bad_keywords` и т.п.) в нём нет.

## 2. Какие виды статистики поддерживаются

| Обёртка | ReportType | Группировка |
|---|---|---|
| `account_stats()` | ACCOUNT_PERFORMANCE_REPORT | — |
| `campaign_stats()` | CAMPAIGN_PERFORMANCE_REPORT | CampaignId |
| `ad_group_stats()` | ADGROUP_PERFORMANCE_REPORT | AdGroupId |
| `criteria_stats()` | CRITERIA_PERFORMANCE_REPORT | AdGroupId, CriteriaId, CriteriaType |
| `search_queries()` | SEARCH_QUERY_PERFORMANCE_REPORT | AdGroupId, Query |
| `get_ad_stats()` | AD_PERFORMANCE_REPORT | AdId (→ StatRow) |
| `get()` | любой из 8 типов (включая CUSTOM_REPORT, REACH_AND_FREQUENCY) | по FieldNames |

## 3. Какие измерения поддерживаются

Через `field_names` доступны все сегменты/атрибуты из официального
справочника полей: `Date`, `Week`, `Month`, `Quarter`, `Year`, `HourOfDay`,
`DayOfWeek`, `CampaignId/Name/Type/UrlPath`, `AdGroupId/Name`, `AdId`,
`Criteria`, `CriteriaId`, `CriteriaType`, `Query`, `Device`, `Slot`,
`AdNetworkType`, `Age`, `Gender`, `IncomeGrade`, `LocationOfPresence`,
`ExternalNetworkName`, `CarrierType`, `ClickType` и др. Тип отчёта
определяет, какие поля допустимы (сверено с таблицей «Допустимые поля»);
клиент не дублирует эту валидацию — её делает API, ошибки типизированы.

## 4. Какие метрики поддерживаются

Все метрики из справочника: `Impressions`, `Clicks`, `Ctr`, `Cost`,
`AvgCpc`, `AvgClickPosition`, `AvgImpressionPosition`, `BounceRate`,
`Bounces`, `AvgPageviews`, `Conversions`, `ConversionRate`,
`CostPerConversion`, `GoalsRoi`, `Revenue`, `AvgEffectiveBid`,
`AvgTrafficVolume` и др. Для конверсий по конкретным целям — параметр
`goals` (до 10 ID целей, лимит API), API отдаёт колонки вида
`Conversions_<goal_id>_<attribution>`; `ReportRow` читает их по имени.

## 5. Как задаются даты

Два взаимоисключающих способа (как в API):

- `date_from` + `date_to` (`datetime.date`, включительно) →
  `DateRangeType=CUSTOM_DATE`;
- `date_range_type` — готовый период API: `LAST_7_DAYS`, `LAST_14_DAYS`,
  `LAST_30_DAYS`, `LAST_365_DAYS`, `THIS_MONTH`, `LAST_MONTH`, `THIS_WEEK`,
  `LAST_WEEK`, `YESTERDAY`, `TODAY`, `ALL_TIME` и т.д.

Валидация на клиенте: пустые `field_names`, отсутствие дат, `date_to <
date_from`, >10 целей → `ValidationError` до HTTP-запроса.

## 6. Как работают async reports

Reports API асинхронный: отчёт может быть в очереди (HTTP 202 + заголовок
`Retry-In`). Реализовано в едином retry-слое (`retry.request_with_retry`),
который уже существовал и переиспользован без дублирования:

1. отправка отчёта (`method=build`);
2. HTTP 202 → sleep `Retry-In` (или до 10с по умолчанию) → повторный запрос;
3. HTTP 200 с TSV → готово;
4. превышен `report_timeout` → `ReportNotReadyError` (с `report_id`,
   `request_id`);
5. `report_timeout` настраивается на клиенте и переопределяется per-call.

## 7. Как реализованы retry и rate limiting

Без изменений с этапа 1, переиспользуются всеми отчётами:

- **429** → backoff с учётом `Retry-After`, до `max_retries`, затем
  `RateLimitError`;
- **401/403** → `AuthError` без ретраев;
- **400/500+** → `ApiError` с телом ошибки и `request_id` (Reports API
  отдаёт JSON-блок `error` — парсится в Transport);
- **Token bucket** (`rate_limit_rps`) — проактивный throttle каждого
  HTTP-запроса, включая poll-итерации.

Новая правка: `Transport.post(report_timeout=...)` — override таймаута
ожидания отчёта на уровне одного вызова.

## 8. Как работает batching

Два независимых механизма в `ReportService.get()`:

- **ID-чанкинг**: `campaign_ids`/`ad_group_ids`/`ad_ids` превращаются в
  `Filter(Field=..., Operator=EQUALS, Values=[...])`; если значений > 1000
  (`MAX_FILTER_IDS`), фильтр разбивается на чанки, выполняется несколько
  отчётов, строки объединяются. При нескольких ID-полях — декартово
  произведение чанков.
- **Окна дат**: `max_days=N` разбивает CUSTOM_DATE-период на окна не длиннее
  N дней (`_date_windows`), отчёты по окнам объединяются. Имена отчётов
  получают суффиксы (уникальность ReportName — требование API).

Плюс `Page.Limit` (лимит строк, по умолчанию 1 000 000 у API).

## 9. Как поддерживаются поисковые запросы

`client.reports.search_queries(...)` — SEARCH_QUERY_PERFORMANCE_REPORT
(группировка AdGroupId + Query, поле `Query` — сам поисковый запрос).
Дефолтные поля: AdGroupId, Query, Impressions, Clicks, Cost,
AvgClickPosition, Ctr. Поддерживает фильтры (например,
`ReportFilter("Query", "STARTS_WITH_IGNORE_CASE", [...])`), ID-фильтры,
сортировку, все параметры `get()`.

## 10. Как поддерживаются конверсии

- Параметр `goals` — до 10 ID целей Яндекс Метрики (лимит API проверяется
  на клиенте). При указании API выводит конверсии по каждой цели отдельно
  (колонки `Conversions_<id>_<attribution>`), читаются через
  `row.as_int("Conversions_123_LC")`.
- Параметр `attribution_models` — LC/LSCCD/FCCD/AUTO.
- Агрегированные метрики: `Conversions`, `ConversionRate`,
  `CostPerConversion` — в дефолтных полях обёрток `campaign_stats`,
  `ad_group_stats`, `criteria_stats`.
- `GoalsRoi` и связанные поля — доступны через `field_names`.

## 11. Список изменённых и созданных файлов

**Созданы:**
- `yandex_direct_api_client/models/report.py` — ReportFilter, ReportOrder,
  ReportRow, ReportResult
- `tests/test_reports.py` — 25 тестов Reports API
- `tasks/task01/STAGE_03_report.md` (этот файл)

**Изменены:**
- `yandex_direct_api_client/services/reports.py` — переписан: `get()` +
  5 обёрток + чанкинг/окна дат; `parse_stats_tsv` и `get_ad_stats`
  переиспользуют общий парсер
- `yandex_direct_api_client/_transport.py` — `report_timeout` per-call
- `yandex_direct_api_client/models/__init__.py`, `__init__.py` — экспорты
- `yandex_direct_api_client/_version.py`, `pyproject.toml` — 0.4.0
- `README.md`, `CHANGELOG.md`

## 12. Основные архитектурные решения

- **Один путь выполнения**: обёртки (`campaign_stats` и др.) только
  формируют параметры и делегируют в `get()`; `get_ad_stats` тоже обёртка.
  Никаких параллельных реализаций (требование задания).
- **Универсальный `get()` вместо десятков методов**: все параметры
  именованные и опциональные, дефолты задают обёртки. Не «один огромный
  метод» — сложность инкапсулирована в типизированных параметрах
  (ReportFilter/ReportOrder), а не в свободных dict.
- **Строковое ядро + типизированный доступ**: `ReportRow` хранит сырые
  строки TSV (как отдаёт API), конвертация — по требованию
  (`as_int/as_float/as_money/as_date`). Это покрывает любые комбинации
  полей без статического описания всех вариантов (баланс типизации и
  гибкости по заданию).
- **Retry/polling не дублировался**: существующий
  `request_with_retry(report=True)` переиспользован; добавлен только проброс
  `report_timeout`.
- **Money-семантика**: `as_money()` делит на 1 000 000 (микросуммы API) —
  явная точка конвертации вместо разбросанных делений.

## 13. Ограничения

- `ReportRow` не знает типов колонок заранее — конвертация по требованию
  (осознанный компромисс; API сам определяет схему по FieldNames).
- Декартово произведение чанков при одновременных больших `campaign_ids` +
  `ad_group_ids` + `ad_ids` может дать много запросов — на практике
  фильтруют одним полем.
- `parse_report_tsv` распознаёт заголовок по множеству известных имён
  колонок — экзотические полностью кастомные наборы полей (без единого
  известного имени) не распарсятся (вернётся пустой ReportResult с raw_text).
- REACH_AND_FREQUENCY_PERFORMANCE_REPORT и CUSTOM_REPORT доступны через
  `get()`, но без специализированных обёрток.
- Разбиение по датам (`max_days`) — опционально и выключено по умолчанию:
  API сам хорошо обрабатывает длинные периоды, разбиение нужно только при
  близости к лимиту 1 000 000 строк.

## 14. Результаты тестов и проверок

| Проверка | Результат |
|---|---|
| `pytest` | **105 passed** (было 80; +25 тестов Reports API) |
| `ruff check .` | All checks passed |
| `mypy yandex_direct_api_client` | Success: no issues in 27 source files (strict) |

Тесты покрывают: обычный отчёт, парсинг TSV (колонки/строки/Total),
202-polling, timeout (ReportNotReadyError), 429 (retry + исчерпание),
API error 400, даты (CUSTOM_DATE + date_range_type, валидация), фильтры/
сортировка/цели в payload, несколько ID, чанкинг 2500 ID → 3 запроса,
разбиение дат 10 дней → 3 окна, все обёртки, конверсии (Goals + колонки),
поисковые запросы, обратную совместимость `get_ad_stats`. Реальных
HTTP-запросов нет — только `responses`.

## 15. Что намеренно не сделано

- **Маркетинговые решения** (disable_bad_keywords, raise_bid_for_good_ads) —
  вне скоупа клиента; появится в отдельном проекте-оптимизаторе.
- **pandas как обязательная зависимость** — только опциональный
  `to_dataframe()` с понятным ImportError; в `[project.optional-dependencies]`
  pandas не добавлялся (не требуется базовой библиотеке).
- **Кэширование готовых отчётов / офлайн-режим** — API сам кэширует отчёты
  по ReportName; клиентское кэширование не добавлялось.
- **Валидация совместимости полей с типом отчёта на клиенте** — таблица
  совместимости огромна и меняется; её держит API, ошибки типизированы.
- **XML-формат** — API поддерживает только TSV для build.
- **Специализированные обёртки для REACH_AND_FREQUENCY/CUSTOM_REPORT** —
  доступны через `get()`.

## 16. Что предполагается на следующем этапе

(Не начинал — жду задания STAGE_04.)
