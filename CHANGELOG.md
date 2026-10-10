# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Migration guide: 0.1.x → 0.4.x

The client was restructured into a namespace API. Summary of breaking changes
with migration examples:

| 0.1.x | 0.4.x |
|---|---|
| `client.get_campaigns()` | `client.campaigns.list()` |
| `client.get_ads(ad_ids=..., campaign_ids=...)` | `client.ads.get(ids=...)` / `client.ads.list(campaign_ids=...)` |
| `client.get_ads_text_batch(ids)` | `client.ads.get(ids, include_text=True)` |
| `client.get_stats(...)` | `client.reports.get_ad_stats(...)` (unchanged) or `client.reports.get(...)` |
| `client.update_ad(id, h, b)` | `client.ads.update_text(id, h, b)` |
| `client.add_campaign(payload)` | `client.campaigns.create(payload)` |
| `client.delete_ad(ids)` | `client.ads.delete(ids, confirm=True)` |
| `YandexDirectClient(chunk_size=...)` | parameter removed (auto chunking/pagination) |
| model `AdTextEntry` | `Ad` with `include_text=True` |
| `parse_stats_tsv` importable from `client.py` | `yandex_direct_api_client` (re-exported) |

New safety semantics:

- `delete` and bulk mutations now require explicit `confirm=True`
  (raises `ValidationError` before any HTTP request is sent).
- `StatRow.merged_with` computes weighted-average `bounce_rate` (was: sum).

## Migration guide: 0.5.x → 1.0.0

1.0.0 — первая стабильная версия. Ниже только то, что действительно ломает
код пользователя; всё остальное — новые возможности.

| 0.5.x | 1.0.0 |
|---|---|
| `AdImage(image_id=...)` | `ImageAdRef(image_hash=...)` (алиас `AdImage` сохранён и работает) |
| `client.campaigns.create(ad_images...)` (гипотетический media-flow) | `client.ad_images.add(...)` → `client.ads.create_responsive_ad(..., ad_image_hashes=[...])` |
| `adimages/update`, `adimages/unbind`, `adimages/remove` | удалены: таких методов в API нет, остались `add`/`get`/`delete` |
| `client.campaigns.create({"Name": ..., "CpmBannerCampaign": ...})` с ручной стратегией | тот же словарь принимается, но стратегию удобнее собирать `CpmBannerCampaign`/`BidStrategy` |
| `CampaignDailyBudget` в теле `campaigns/add` | `DailyBudget` — deprecated escape-hatch, рабочий путь — недельный бюджет `set_weekly_budget` / `ManualCpm.WeeklySpendLimit` |
| `api_version="v501"` в `client.ad_groups.create`, `client.ads.create` | сохранено; для `UnifiedAdGroup`/`UnifiedCampaign` версия подставляется автоматически |
| импорт `GENDER_SEGMENT_NAMES` | удалён: SDK не зашивает локализованные названия половых сегментов |
| `DemographicsSpec(gender=GENDER_FEMALE)` без `gender_names` | теперь обязательно `gender_names={GENDER_FEMALE: "<имя из справочника>"}`; справочник локализован, а SDK не догадывается локаль |

Поведенческие изменения, которые стоит проверить при обновлении:

- `ads.update_text(..., auto_clamp=True)` по-прежнему молча обрезает строку —
  это сохранённый BC (D3). Новые билдеры (`ResponsiveAd`, `AdText` в
  `create_with_payload`) не обрезают: превышение лимита — `ValidationError`.
- `RegionIds=[0]` и пустой список регионов отвергаются локально (раньше уходили
  в API и падали там).
- `on_item_error` добавлен во все batch-мутации; значение по умолчанию `raise`
  сохраняет прежнее поведение.
- `client_login` необязателен: если он не задан, заголовок `Client-Login` не
  отправляется. Для агентского доступа передавайте `client_login` как раньше.
  - Реквизиты бюджета — строки/числа в валюте аккаунта; на провод уходят
  единицы API ×1 000 000 (`to_money_units`), а `from_money_units` возвращает
  `Decimal` с 6 знаками.
- `DemographicsTarget.name` обязательно: без имени `to_retargeting_list()`
  бросает `ValidationError` (SDK не придумывает имя сегмента за бизнес).
- `DemographicsSpec` для таргетинга по полу требует `gender_names` — SDK не
  локализует строки за бизнес (справочник `AudienceDemographicProfiles`
  локализован; варианты — через
  `TargetingService.demographic_segment_names`).
- `RegionSelector.country_region` по‑прежнему `"RUC"` по умолчанию, но теперь
  подпись и inline‑комментарий явно требуют переопределять для не‑российских
  аккаунтов; докстринг больше не содержит частных бизнес‑примеров.
- `set_weekly_budget_in_campaign` и `campaigns.set_weekly_budget` получили
  `strategy=`. CPM‑ветка больше не молча перезаписывает чужую
  `Network.BiddingStrategyType` → `MANUAL_CPM`; при конфликте бросает
  `ValidationError`. Дополнительно: `campaigns.set_weekly_budget` для CPM‑кампании
  с живой сетевой стратегией, **отличной от `MANUAL_CPM`** (например `MAX_CLICKS`),
  требует явного `strategy=` — без него бросает `ValidationError` (weekly budget
  поддерживается только при `MANUAL_CPM`; смена стратегии должна быть намеренной).
- `TextCampaign`/`CpmBannerCampaign`/`UnifiedCampaign`/`PriorityGoal`/`CampaignBase.daily_budget_mode`/`AutotargetingSetting` больше не молчат о выбранных по умолчанию значениях: SDK эмиттирует `logging.warning`, а явный параметр (escape-hatch) подавляет его.
- `readonly=True` блокирует все мутирующие методы, включая новые слои
  (бюджеты, стратегии, изображения, таргетинг).
- Денежные мутации требуют `confirm=True`; ограничение — `daily_budget_cap`
  (`YANDEX_DIRECT_BUDGET_CAP`), по умолчанию проверка отключена.
- Live-скрипты лежат в `scripts/` и не входят в `pytest`; они создают только
  тестовые сущности (`E2E`/`TEST` в имени — иначе требуется `confirm=True`) и
  удаляют созданное в `finally`.

## [Unreleased]

## [1.0.0] - 2026-10-01

### Breaking (Layer 1 migration to v501 dictionaries contract)
- **`client.dictionaries`** (`DictionariesService`): запрос справочников переведён на
  формат `v501` (`DictionaryNames`) вместо старого `v5` (`getGeoRegions`,
  `getInterests` и т. п.). Изменения:
  - `geo_regions(country_region="RUC")` — больше не фильтрует на сервере по
    стране; возвращает весь мировой справочник (≈17 000 регионов). Клиент
    должен фильтровать по `GeoRegionType`/`ParentId` локально (см. `RegionSelector`).
  - Поля ответа: `GeoRegionId`, `GeoRegionName`, `GeoRegionType`, `ParentId`
    вместо `GeoRegionId`, `ParentGeoRegionId`, `CountryRegion`, `IsArea`.
  - Русские названия требуют заголовок `Accept-Language: ru` (по умолчанию
    возвращаются английские).
  - Справочники `RetargetingLists`, `Sites`, `AdTypes`, `BingTypes`,
    `Keywords`, `GeoHierarchy` **отсутствуют в v501** — для них используется
    старый `v5` формат (методы работают как раньше).
- **`GeoRegion` модель**: поля изменены — `region_type` (`GeoRegionType`),
  `parent_id` (`ParentId`); `country_region` и `is_area` убраны.
  Свойство `is_top_level` теперь проверяет `region_type == "country"`
  (в v501 у Country есть `ParentId` → World).
- **`RegionSelector`**: резолв теперь работает с v501 иерархией
  (`GeoRegionType`/`ParentId`). Сайд-эффект: исключаемые регионы (Москва, МО,
  СПб, ЛО) резолвятся динамически из словаря (названия в v501 отличаются
  от v5).

### Added
- **STAGE_05, этап 0 — фундамент:**
  - `api_version` в `YandexDirectClient` и `Settings`: переключение между `v5`
    (классическая РСЯ) и `v501` (ЕПК). Версия извлекается из `api_url`,
    поэтому `https://api.direct.yandex.com/json/v5` + `api_version="v501"`
    даёт корректный URL без дублирования сегмента версии.
  - `client_login` стал необязательным: если он не задан, заголовок
    `Client-Login` не отправляется (прямой доступ рекламодателя).
  - `on_item_error="raise" | "collect"` для всех batch-мутаций
    (`campaigns`, `ads`, `ad_groups`, `ad_group_items`, `ad_extensions`,
    `audience_targets`, `retargeting_*`, `negative_keywords`): режим `collect`
    возвращает `BatchResult(succeeded=..., failed=...)` с `ItemFailure`
    (код, сообщение, ID объекта, `request_id`) вместо потери успешных
    элементов. Значение по умолчанию — `raise` (прежнее поведение).
  - `campaigns.create_many()` — создание нескольких кампаний с авто-чанкингом
    по 10 (реальный лимит `campaigns/add`).
  - Модуль `limits` — централизованные лимиты API (вместо разбросанных
    констант); `services/_base.run_batches()` — общий batch-планировщик.
  - Модуль `validation` — пред-отправочная валидация (ID, `RegionIds`,
    имена, тексты, URL, суммы, enum). Отключается через `validate=False`
    или `YANDEX_DIRECT_VALIDATE=0`.
  - Модуль `logs` — structured logging (мутации на INFO, чтения на DEBUG,
    поля `service`/`method`/`api_version`/`request_id`/`status_code`/
    `duration_ms`) и redactor секретов (`Authorization`, `token`,
    `client_secret`, токены `t1.`/`y0_`/`y1_`, `Bearer ...`).
  - `BatchResult` и `ItemFailure` экспортированы из пакета.
- **STAGE_05, этап 1 — справочники, гео и лимиты клиента:**
  - `client.dictionaries` (`DictionariesService`): `geo_regions`,
    `geo_hierarchy`, `interests`, `keywords`, `retargeting_lists`, `sites`,
    `ad_types`, `time_zones`, `currency`, `bing_types` и эскапирующий
    `dicts(field, params=...)` для новых словарей Яндекса.
  - Модели справочников: `GeoRegion`, `Interest`, `RetargetingList`, `Site`,
    `AdType`, `TimeZone`, `Currency`, `DictEntry` — все с `raw`.
  - Дисковый кэш справочников: TTL 7 суток, каталог
    `YANDEX_DIRECT_CACHE_DIR` (по умолчанию `~/.yandex-direct-api-client/cache`),
    метод `clear_cache()`. Сбой доступа к файлу кэша не ломает клиент.
  - `RegionSelector(include=[...], exclude=[...])` — единственный механизм
    гео-таргетинга в SDK: принимает ID, коды и названия, резолвит их только
    через справочник, отвергает выдуманные ID и неоднозначные названия с
    `ValidationError`. Зашитых бизнес-регионов в коде нет (D5).
    Хелпер `client.regions(selector)` и `RegionSelector.current(ad_group)`.
  - `client.clients.get()` → `ClientInfo` с `Restrictions`, метод
    `can_create_campaign(count)` для предварительной проверки лимитов.
- **STAGE_05, слой 2А — классическая РСЯ (v5):** тела запросов сверены с
  документацией (снимок 30.09.2026), поэтому билдеры строятся по фактическому
  контракту API, а не по «наивной» структуре.
  - `models/ad.py`: `AdImage` переименован в `ImageAdRef` (алиас `AdImage`
    сохранён — BC для импортов); изображение адресуется хэшем
    `AdImageHash`, а не `ImageId`.
  - `money.py`: `to_money_units`, `from_money_units`, `monthly_to_weekly`
    на `Decimal` — никаких `float`-артефактов в денежных полях.
  - `models/campaign_payloads.py`: `CpmBannerCampaign` и `TextCampaign` +
    диспетчер `build_campaign(kind, **kwargs)`. Типоспецифичные поля
    кладутся во **вложенную** структуру (`CpmBannerCampaign`,
    `TextCampaign`); бюджет — недельный и задаётся стратегией
    (`BiddingStrategy.Network.ManualCpm.WeeklySpendLimit`); показы на
    поиске у CPM-кампании выключены (`SERVING_OFF`); `StartDate`
    обязателен при создании; имя — до 255 символов. `SmartCampaign`
    удалён: `SMART_CAMPAIGN` через API не создаётся.
  - `models/ad_group_payloads.py`: `CpmBannerAdGroup`
    (`CpmBannerKeywordsAdGroup: {}` / `CpmBannerUserProfileAdGroup: {}`),
    `TextAdGroup`, `SmartAdGroup` (`SmartAdGroup.FeedId` и т. п.) и
    `build_ad_group(kind, **kwargs)`. Поле `Type` в `adgroups/add` больше
    не отправляется — тип задаётся типовой структурой.
  - `client.ad_images` (`AdImageService`): `add`, `add_from_file`,
    `add_from_stream`, `get`, `list`, `delete` (алиас `remove`) — ровно те
    методы, которые есть в API; `adimages/update` и `adimages/unbind` в
    API отсутствуют. Проверка base64, формата, размера и имени до отправки.
  - `client.creatives` (`CreativesService`): `get`, `list`,
    `image_creative_ids` — чтение `CreativeId` для медийных объявлений.
  - `CpmBannerAdBuilderAd` + `client.ads.create_rsya_banner(ad_group_id,
    creative_id, ...)`: медийное объявление создаётся по креативу
    (`Creative.CreativeId`); полей `Title`/`Text`/`ImageId` в `ads/add`
    больше нет. `BannerAd` оставлен как модель чтения.
  - `AdGroup.to_new_payload()` больше не отправляет `Type` (в `update` —
    не отправлялся и раньше).
  - `campaigns.create`/`create_many` и `ad_groups.create` принимают как
    типизированные билдеры, так и сырые словари.
- **STAGE_05, слой 2Б — ЕПК (UnifiedCampaign, v501):**
  - `UnifiedCampaign` + `UnifiedStrategy` + `PriorityGoal`: вложенный блок
    `UnifiedCampaign`, стратегии поиска и сетей с недельным бюджетом
    (`BiddingStrategy.Search.AverageCpa.WeeklySpendLimit` и т. п.), счётчики
    Метрики (`CounterIds`) и ключевые цели по ID (`PriorityGoals`);
    обязательные поля стратегии (недельный бюджет, `GoalId`, ставка для
    `AVERAGE_CPC`) проверяются до отправки, редкие поля — escape-hatch.
  - `UnifiedAdGroup`: группа ЕПК с обязательной структурой
    `UnifiedAdGroup: {OfferRetargeting}`; гео (`RegionIds`) задаётся здесь же,
    поэтому ЕПК использует тот же `RegionSelector`, что и v5.
  - `ResponsiveAd`: комбинаторное объявление ЕПК (1..7 заголовков по 56
    символов, 1..3 текстов по 81, 1..5 `AdImageHashes`, расширения,
    видеодополнения, `AgeLabel`); строки не обрезаются молча (D3).
  - `campaigns.create_unified`, `update_unified`, `get_unified`,
    `delete_unified` работают на `v501`; `campaigns.create` с билдером
    `UnifiedCampaign` маршрутизируется на `v501` автоматически, v5-методы
    остаются на `v5`.
  - `ad_groups.create` и `ads.create` принимают `api_version`; для
    `UnifiedAdGroup` версия подставляется сама.
  - `client.ads.create_responsive_ad(...)` — узкий хелпер для ЕПК-объявления
    с маршрутизацией на `v501`.
- **STAGE_05, слой 3 — ставки и бюджеты:**
  - `models/bid_strategy.py`: `BidStrategy` (типизированные стратегии с
    `to_payload()`/`from_dict()`, escape-hatch `extra` для новых полей) и
    `strategy_payload()` для передачи готовой секции стратегии словарём.
    Обязательные поля стратегии (недельный бюджет, `GoalId`, ставка
    `AVERAGE_CPC`) проверяются при сборке payload, поэтому стратегию можно
    создать заранее, а бюджет передать отдельным аргументом метода.
  - `services/budgets.py`: `CampaignBudget`, `read_budget`,
    `set_weekly_budget_in_campaign`, `verify_weekly_budget`,
    `ensure_money_confirmed`.
  - `client.campaigns.set_weekly_budget(ids, budget, *, verify=True,
    confirm=False)`, `set_daily_budget(...)`, `get_budgets(ids)`,
    `set_bid_strategy(ids, strategy, *, weekly_budget=None, verify=True,
    confirm=False)`. `verify=True` перечитывает бюджеты и бросает `ApiError`
    с обоими значениями при расхождении; `get_budgets` читает v5, затем v501.
  - `Settings.daily_budget_cap` (env `YANDEX_DIRECT_BUDGET_CAP`) и
    `require_confirm_for_money` (env `YANDEX_DIRECT_REQUIRE_CONFIRM_MONEY`,
    по умолчанию `True`) — предохранители денежных мутаций; превышение cap
    блокируется до сети. Аргументы доступны и в конструкторе клиента.
  - `AdGroupItemBids.bid_type`: `search` (поле `Bid`) или `network`
    (поле `ContextBid`); `set_bid(..., bid_type=...)` — то же. Ставка
    проверяется на положительность, точные лимиты валюты остаются в
    справочнике `Currencies`.
- **STAGE_05, слой 4 — таргетинг (демография, интересы, ретаргетинг):**
  - `constants.py`: матрица допустимости «тип группы × вид нацеливания»
    (`is_allowed`, `explain`, `keyword_conflict`) и префиксы типов интереса
    (`segment_external_id`); несовместимые комбинации отсекаются до сети.
  - `models/targeting.py`: спеки `DemographicsSpec` (возрастные сегменты и
    пол), `InterestSpec` (`resolve(name)` с `ValidationError` при
    неоднозначности), `RetargetingSpec`, модель `RetargetingList` и
    типизированные билдеры `RetargetingTarget`, `InterestTarget`,
    `DemographicsTarget`, `ContextTarget`.
  - `ContextTarget` сообщает `ValidationError`: нацеливания по контексту
    страницы в Direct API v5 нет — `audiencetargets` поддерживает только
    `RetargetingListId` и `InterestId`.
  - `services/retargeting_lists.py` + `client.retargeting_lists`:
    `retargetinglists` add/update/delete/get, фильтр по типам, подбор
    сегментов по `AvailableForTargetsInAdGroupTypes`.
  - `services/targeting.py` + `client.targeting`: `resolve_demographics`,
    `resolve_interest`, `demographic_segment_names`, сборка условий
    нацеливания и `create_audience_target` (сегмент `AUDIENCE` → условие).
  - `dictionaries`: `audience_demographic_profiles()`, `audience_interests()`,
    `audience_criteria_types()`, `audience_profiles_of_type()` +
    модели `AudienceDemographicProfile`, `AudienceInterestSegment`,
    `AudienceCriteriaType`.
  - `AutotargetingSetting` и группы `DynamicSiteAdGroup`,
    `DynamicFeedAdGroup` (`AutotargetingCategories` в `adgroups/add`).
- **STAGE_05, слой 5 — E2E-сборка запуска в `scripts/` (вне пакета):**
  - `scripts/_launch_common.py`: `LaunchResult`/`LaunchStep`/`PartialIds`
    (частичные ID для компенсации), план запуска (`plan_lines`), `preflight()`
    (параметры клиента и лимиты), `resolve_geo()`, `moderate_ads()`,
    `resume_ads()`, `poll_ads()` и `rollback()` — компенсация без исключений:
    `suspend` → `archive` → `campaigns/delete` (только при `confirm=True`) →
    `adimages/delete` загруженных в этом запуске изображений.
  - `ReuseCache` — кэш «SHA-256 содержимого файла → ID созданной сущности»;
    повторный запуск с тем же файлом не грузит изображение второй раз.
    Каталог: `YANDEX_DIRECT_LAUNCH_CACHE_DIR`; ошибки ФС не ломают запуск.
  - `scripts/launch_rsy.py` (сценарий 2А): `launch(client, spec, *,
    dry_run=False, poll_interval=30, poll_timeout=3600, confirm=False)`.
    Требует готовый креатив (`creative_id` или `creative_name`), потому что
    `creatives/add` баннерные креативы не создаёт (D11).
  - `scripts/launch_epk.py` (сценарий 2Б, основной автозапуск): `adimages/add`
    → `UnifiedCampaign` (v501) → `UnifiedAdGroup` → `ResponsiveAd` (v501) →
    `ads/moderate` (v501).
  - `dry_run=True` — только валидация и план, **ноль** сетевых вызовов;
    ошибка любого шага фиксируется в отчёте, а не выбрасывается наружу.
  - Имя запуска без маркеров `E2E`/`TEST`/`ТЕСТ` требует `confirm=True`
    (D9: автоматический запуск кампании реального бизнеса запрещён).
  - Новые точки входа запускаются как модули: `python -m scripts.launch_rsy`,
    `python -m scripts.launch_epk`.
- **STAGE_05, слой 5 — расширение API для ЕПК (не breaking):**
  - `ads.suspend()`, `ads.resume()`, `ads.archive()`, `ads.moderate()` и
    `campaigns.suspend()`, `campaigns.archive()` принимают необязательный
    `api_version` (по умолчанию `None` — `v5`). Нужен для управления
    объявлениями и кампаниями ЕПК через `v501`.
- **STAGE_05, этап 7 — L1/L2 mock-тесты по всем слоям:**
  - `tests/test_task04_stage7.py` (70 тестов): снапшоты payload'ов
    классической РСЯ, поведение `readonly` по полному списку мутирующих
    методов, negative-кейсы пред-отправочной валидации, справочники,
    кэш, ретаргетинг-листы, расширения, отчёты, версии API.
  - `tests/test_task04_stage7_quality.py` (52 теста): OAuth-хелперы
    (`refresh_token`, code-flow, обработчик callback, CLI, поиск свободного
    порта), ветви `ad_extensions`/`audience_targets`/`retargeting_conditions`,
    денежные операции кампаний (`set_weekly_budget`, `set_daily_budget`,
    `set_bid_strategy`, маршрутизация ЕПК в `v501`), модели объявлений
    (`AdText`, `ImageAdRef`, `CpmBannerAdBuilderAd`, `ResponsiveAd`).
  - `tests/test_task04_stage8.py` (19 тестов): сценарии live-скрипта
    (гео, обязательные аргументы, отчёт о провалах, CLI, контур безопасности).
  - Итог: 638 тестов, покрытие пакета 96 %, новые модули ≥ 90 %;
    `ruff check .`, `mypy yandex_direct_api_client` и `pytest` — зелёные.
- **STAGE_05, этап 8 — permanent live-скрипт:**
  - `scripts/smoke_campaign_live.py --scenario S-01…S-05` (или `all`):
    авторизация и лимиты, гео-проверка, жизненный цикл классической РСЯ
    (`v5`), жизненный цикл ЕПК (`v501`), отчёт по кампании. Сценарии создают
    только тестовые сущности в `DRAFT`, не включают показы, выполняют
    самоочистку через `rollback(..., confirm=True)` и возвращают ненулевой код
    при провале; OAuth-токен не выводится никогда.
- **STAGE_05, этап 9 — документация и релиз:**
  - README: поддерживаемые сервисы, таблица `v5` vs `v501`, примеры создания
    кампании РСЯ и ЕПК, `readonly`/`confirm=True`, денежные операции,
    гео-таргетинг, live smoke с описанием ограничений.
  - Миграционные заметки `0.5.x → 1.0.0` (см. раздел выше).
  - Отчёт этапа: `tasks/task04_report.md`.

### Changed
- Ошибки классифицируются по категориям (`auth`, `rate_limit`, `retryable`,
  `validation`, `fatal`) с хелперами `is_auth`/`is_retryable`/
  `is_validation`/`is_fatal`; `ApiError` при non-2xx теперь извлекает
  `error_code` и `details` из JSON-тела ответа.
- `ApiError`, `ValidationError` и тексты логов проходят через redactor:
  OAuth-токен не попадает в `str(exception)`, `repr` и логи.

### Fixed
- `region_ids=[0]` и пустой `RegionIds` отвергаются локально, до запроса.
- Лимит `campaigns/add` приведён к фактическим 10 кампаниям за вызов.
- Перегрузки `campaigns.create()` принимают билдеры кампаний
  (`CampaignInput`), а не только словари — сигнатура реализации всегда это
  допускала, аннотация типов расходилась с поведением.

## [0.5.0] - 2026-09-23

### Added
- **Track A — full lifecycle of existing resources:**
  - `client.ad_groups` gained mutations: `create` (typed `AdGroup` or raw),
    `update`, `delete` (requires `confirm=True`). Endpoint `adgroups/add|update|delete`.
  - `client.campaigns` state management: `suspend`, `resume`, `archive`
    (requires `confirm=True`), `unarchive`. Endpoints `campaigns/suspend|resume|archive|unarchive`.
  - `client.ads` state management and moderation: `suspend`, `resume`,
    `archive` (requires `confirm=True`), `unarchive`, `moderate`.
    Endpoints `ads/suspend|resume|archive|unarchive|moderate`.
  - `AdGroup.to_new_payload()` / `to_update_payload()`.
- **Track B — new API resources:**
  - `client.negative_keywords` service (API `negativekeywordsharedsets`):
    `list`, `get`, `create`, `update`, `delete` (requires `confirm=True`).
    Model `NegativeKeywordSharedSet`.
  - `client.audience_targets` service (API `audiencetargets`): `list`, `get`,
    `create`, `delete` (requires `confirm=True`), `suspend`, `resume`, `set_bids`.
    Model `AudienceTarget`. (audiencetargets has no `update`; bids change via
    `set_bids`.)
  - `client.retargeting_conditions` service: `list`, `get`, `create`,
    `delete` (requires `confirm=True`). Model `RetargetingCondition`. Wraps the
    `audiencetargets` service (the standalone `retargetingconditions` endpoint is
    not in the current v5 reference; retargeting is managed via
    `audiencetargets` + `RetargetingListId`).
  - `client.ad_extensions` service: `list_sitelinks`, `get_sitelinks`,
    `create_sitelinks`, `delete_sitelinks` (API `sitelinks`) and
    `list_callouts`, `get_callouts`, `create_callouts`, `delete_callouts`
    (API `adextensions`, type CALLOUT). Models `Sitelink`, `SitelinksSet`, `Callout`.
- New models: `NegativeKeywordSharedSet`, `AudienceTarget`,
  `RetargetingCondition`, `Sitelink`, `SitelinksSet`, `Callout`.
- 51 new tests (Track A: 23, Track B: 28): request construction, response
  parsing, item-level errors, `confirm`/`readonly` guards, typed/raw payloads.
- 5 regression tests from the live-account run (see below): `ad_groups`
  `list`/`get` field/criteria contracts and guards.
- `scripts/smoke_task03_live.py` — permanent live smoke over a real account
  (campaign + groups + ads lifecycle); creates a DRAFT campaign starting
  tomorrow and deletes everything it creates. Not part of pytest.

### Fixed
- `AdGroup` model: field is `NegativeKeywordSharedSetIds` (singular) and it is
  an `ArrayOfLong` (`{Items: [...]}`) — `from_dict` now unwraps the `Items`
  wrapper and `to_new_payload` emits it. Previously used a wrong field name and
  a bare list.
- `client.ad_groups` service is now constructed with `readonly=ro`, so its
  mutations are correctly blocked in readonly mode (was wired without the flag).
- **Request-contract bugs found only against the live API (mocks could not
  catch them):**
  - `adgroups/get` requested a non-existent `State` field (ad groups have only
    `Status`/`ServingStatus`) → API error 8000 "Not able to process JSON/XML".
    Removed from `_DEFAULT_FIELDS`; `ad_groups.list`/`get` now send valid fields.
  - `ad_groups.list()` without `campaign_ids` produced an empty
    `SelectionCriteria` → API "filtration parameters incorrectly set". Now raises
    a clear client-side `ValidationError` (adgroups/get requires `CampaignIds`/`Ids`).
  - `ad_groups.list(states=…)` sent invalid `SelectionCriteria.States`; replaced
    with valid `statuses`/`serving_statuses` filters.
  - `AdGroup.to_update_payload()` sent `CampaignId`, which `adgroups/update`
    rejects (error 8000 "unknown parameter CampaignId"). No longer sent on update.
  - `ads.create_with_payload()` sent `CampaignId` and `Type`, both rejected by
    `ads/add` (error 8000 "unknown parameter …"). The ad's campaign is derived
    from `AdGroupId` (now required) and its type from the `TextAd`/`ImageAd`
    object. `campaign_id`/`type_` params are kept for compatibility but not sent.
  - Updated two existing tests that had codified the buggy payloads
    (`test_ads_create_with_payload`).

## [0.4.1] - 2026-09-22

### Changed
- Deduplicated service-level helpers: `check_item_errors` and `ensure_writable`
  moved to `services/_base.py` (was copy-pasted in 4 services).
- Deduplicated OAuth token exchange: `auth.refresh_token` and code exchange now
  share a single `_post_token_request` implementation.
- `services/_base.py`: `import copy` moved to module level.

### Fixed
- `auth._parse_args` no longer returns a 1-tuple (odd signature).

## [0.4.0] - 2026-09-22

### Added
- Full Reports API support: universal `client.reports.get()` with report type,
  date period (`date_from`/`date_to` or `date_range_type`), custom fields,
  filters (`ReportFilter`), ordering (`ReportOrder`), Metrika goals
  (conversions), attribution models, VAT/discount flags, page limit and
  per-call `report_timeout`.
- Typed convenience wrappers: `account_stats`, `campaign_stats`,
  `ad_group_stats`, `criteria_stats` (keywords/autotargeting),
  `search_queries` — all delegate to `get()` (single execution path).
- New models: `ReportFilter`, `ReportOrder`, `ReportRow` (typed accessors
  `as_int/as_float/as_money/as_date`), `ReportResult` with `to_dicts()`,
  `to_csv()`, `to_json()` and optional `to_dataframe()` (pandas optional).
- Auto-batching for large requests: ID filters chunked by 1000 values per
  report; long date ranges split into windows via `max_days` parameter.
- `report_timeout` override per call (`Transport.post` parameter).
- 25 new tests: parsing, filters/order/goals payload, 202 polling, timeout,
  429 retry, API errors, ID chunking, date-window splitting, wrappers,
  backward compatibility.

### Fixed
- `get_ad_stats` now sends ID filters via `SelectionCriteria.Filter`
  (per official v5 spec) instead of non-standard `AdIds`/`CampaignIds` fields.

## [0.3.0] - 2026-09-22

### Added
- `client.ad_group_items` service (keywords, API service `criteria`): `list`, `get`,
  `add` (typed `AdGroupItem` or raw dicts), `set_bid`, `set_bids` (bulk, requires
  `confirm=True`), `delete` (requires `confirm=True`).
- `client.retargeting_adjustments` service: `list`, `get`, `add`, `update`
  (bulk, requires `confirm=True`), `delete` (requires `confirm=True`).
- New models: `AdGroupItem`, `AdGroupItemBids`, `RetargetingBidAdjustment`,
  `AdImage`; `AdText.to_payload()` for typed ad creation.
- `client.ads.create_with_payload()` — create a text ad from typed
  `AdText`/`AdImage` models.
- Unit tests for all new services: pagination, batching, typed/raw payloads,
  item-level errors, confirm and readonly guards (22 new tests).

## [0.2.1] - 2026-09-22

### Added
- `confirm=True` guard for destructive operations: `ads.delete`, `campaigns.delete`,
  and bulk `ads.update` now raise `ValidationError` unless explicitly confirmed.
  Single-item operations (`update_text`, `campaigns.update`, `campaigns.create`,
  `ads.create`) do not require confirmation.

### Removed
- Unused `DEFAULT_CHUNK_SIZE` constant from `config.py`.

## [0.2.0] - 2026-09-22

### Breaking changes
- Client API restructured to namespace-based: `client.campaigns.list()` instead of `client.get_campaigns()`.
- `client.ads.update_text()` replaces `client.update_ad()`.
- `client.ads.delete()` replaces `client.delete_ad()`.
- `client.campaigns.create()` replaces `client.add_campaign()`.
- `client.reports.get_ad_stats()` replaces `client.get_stats()`.
- `chunk_size` parameter removed from constructor (pagination handles this internally).
- `AdTextEntry` model removed (use `Ad` with `include_text=True` instead).
- `StatRow.merged_with` now computes weighted-average `bounce_rate` instead of summing.

### Added
- Namespace services: `client.campaigns`, `client.ads`, `client.ad_groups`, `client.reports`.
- Auto-pagination via `Page`/`LimitedBy` in all `list()` methods.
- `AdGroup` model and `client.ad_groups` service (list, get).
- `client.campaigns.update()` and `client.campaigns.delete()`.
- `client.ads.create()` and `client.ads.update()` — batch operations (up to 200 per request).
- `client.ads.list()` — flexible filtering with auto-pagination.
- `Transport` class extracted for HTTP layer separation.
- `models/` package with per-entity modules.
- `services/` package with per-resource service classes.

### Changed
- `Campaign` model now includes `type` field.
- `requests.Session` lock removed (Session is thread-safe for independent requests).
- `DEFAULT_CHUNK_SIZE` constant removed from config.

## [0.1.0] - 2026-09-20

### Added
- `YandexDirectClient` — sync typed client for Yandex.Direct API v5.
- OAuth helpers: `get_new_token`, `refresh_token` in `yandex_direct_api_client.auth`.
- Built-in retry layer for HTTP 429 (with `Retry-After`) and 202 report polling.
- Token-bucket rate limiter (configurable `rate_limit_rps`).
- Typed responses as dataclasses (`Campaign`, `Ad`, `AdText`, `StatRow`).
- Custom exceptions with `request_id`: `AuthError`, `RateLimitError`,
  `ReportNotReadyError`, `ApiError`.
- `readonly=True` guard blocking all mutating methods.
- Auto-chunking for `get_ads`, `get_ads_text_batch`, `update_ad`, `delete_ad`.
- Context-manager support with shared `requests.Session` (keep-alive).
- Environment-variable fallback (`YANDEX_DIRECT_TOKEN`, `YANDEX_DIRECT_CLIENT_LOGIN`, ...).
- `py.typed` marker for mypy / PEP 561.
