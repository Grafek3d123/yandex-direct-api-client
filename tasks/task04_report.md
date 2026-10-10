# STAGE_05 — отчёт по этапу

**Задание:** `tasks/task04.md`
**Отчёт:** `tasks/task04_report.md` (D8 — рядом с заданием, один файл, в самом конце)
**Дата:** 01.10.2026 (живой прогон L3 завершён 09.10.2026, обновлён 10.10.2026)
**Версия:** 1.0.0 (`pyproject.toml`, `yandex_direct_api_client/_version.py`)
**Итог:** этапы 0–9 выполнены; живой прогон (L3) **успешно пройден** на креды владельца:
авторизация/лимиты (S-01), гео (S-02), ЕПК (S-04), отчёты (S-05) — ОК.
Классическая РСЯ (S-03) требует ручной шаг в веб-UI (D11) — пропущен.

---

## 1. Что сделано

Реализованы все слои STAGE_05 по этапам 0–9 задания `tasks/task04.md`:

| Этап | Содержание | Состояние |
|---|---|---|
| 0 | Фундамент: `v5`/`v501`, `client_login`, лимиты, ошибки, batch, логи, валидация | выполнен |
| 1 | Справочники, `RegionSelector`, лимиты клиента | выполнен |
| 2А | Слой 2А — классическая РСЯ (`v5`) | выполнен |
| 2Б | Слой 2Б — ЕПК / `UnifiedCampaign` (`v501`) | выполнен |
| 3 | Слой 3 — деньги, стратегии, бюджеты | выполнен |
| 4 | Слой 4 — демография, интересы, ретаргетинг | выполнен |
| 5 | Слой 5 — E2E-сборка запуска в `scripts/` + компенсации | выполнен |
| 6 | — (совмещён со слоем 5: `scripts/launch_*.py`) | выполнен |
| 7 | L1/L2 mock-тесты по всем слоям, регрессия | выполнен |
| 8 | Live-скрипты + прогон на креды владельца | выполнен: S-01, S-02, S-04, S-05 — ОК; S-03 требует веб-UI |
| 9 | README, `CHANGELOG.md` (1.0.0), отчёт, релиз | выполнен |

---

## 2. Что добавлено

### Слой 0 — фундамент
- `api_version` в клиенте и `Settings`: переключение `v5` ⇄ `v501` без дублирования
  сегмента версии в URL.
- `client_login` необязателен (D4): без него заголовок `Client-Login` не отправляется.
- `on_item_error="raise" | "collect"` во всех batch-мутациях; `collect` возвращает
  `BatchResult(succeeded=..., failed=...)` с `ItemFailure` (код, сообщение, ID, `request_id`).
- `limits` — централизованные лимиты API; `services/_base.run_batches()` — общий
  batch-планировщик с авто-чанкингом.
- `validation` — пред-отправочная валидация (ID, `RegionIds`, имена, тексты, URL, суммы, enum).
- `logs` — структурированное логирование + redactor секретов.
- Классификация ошибок (`auth`/`rate_limit`/`retryable`/`validation`/`fatal`) и `request_id`.

### Слой 1 — справочники и гео
- `client.dictionaries`: `geo_regions`, `geo_hierarchy`, `interests`, `keywords`,
  `retargeting_lists`, `sites`, `ad_types`, `time_zones`, `currency`, `bing_types`,
  `audience_demographic_profiles()`, `audience_interests()`, `audience_criteria_types()`,
  `audience_profiles_of_type()` и эскапирующий `dicts(field, params=...)`.
- Атомарный дисковый кэш справочников: TTL 7 суток, `YANDEX_DIRECT_CACHE_DIR`,
  graceful fallback при сбое ФС.
- `RegionSelector(include=..., exclude=...)` — единственный механизм гео (D5);
  резолвит только через справочник, зашитых бизнес-регионов нет.
- `client.clients.get()` → `ClientInfo` с `Restrictions` и `can_create_campaign(count)`.

### Слой 2А — классическая РСЯ (`v5`)
- `CpmBannerCampaign`, `TextCampaign` — тела сверены с документацией (снимок 30.09.2026).
- `CpmBannerAdGroup` и остальные группы; `Type` больше не отправляется в `adgroups/add`.
- `CpmBannerAdBuilderAd` + `client.ads.create_rsya_banner(...)`: медийное объявление
  создаётся по `Creative.CreativeId` (D11).
- `client.ad_images`: `add`, `add_from_file`, `add_from_stream`, `get`, `list`, `delete`
  (методов `update`/`unbind` в API нет).
- `client.creatives` — read-only, плюс `image_creative_ids(names=...)` для поиска
  `CreativeId` по имени.

### Слой 2Б — ЕПК (`v501`)
- `UnifiedCampaign`, `UnifiedStrategy`, `PriorityGoal`: недельный бюджет, `CounterIds`,
  `PriorityGoals`, проверка обязательных полей стратегии, escape-hatch для редких полей.
- `UnifiedAdGroup`: `UnifiedAdGroup: {OfferRetargeting}`, тот же `RegionSelector`.
- `ResponsiveAd`: 1..7 заголовков по 56 символов, 1..3 текстов по 81, 1..5 `AdImageHashes`,
  расширения, видеодополнения, `AgeLabel`; строки не обрезаются молча (D3).
- `campaigns.create_unified`, `update_unified`, `get_unified`, `delete_unified`;
  `campaigns.create()` с `UnifiedCampaign` маршрутизируется на `v501` автоматически.
- `client.ads.create_responsive_ad(...)` — узкий хелпер ЕПК-объявления.

### Слой 3 — ставки и бюджеты
- `models/bid_strategy.py`: `BidStrategy`/`UnifiedStrategy` с `to_payload()`/`from_dict()`
  и `extra` как escape-hatch; `strategy_payload()` для готовых секций стратегии.
- `services/budgets.py`: `CampaignBudget`, `read_budget`, `set_weekly_budget_in_campaign`,
  `verify_weekly_budget`, `ensure_money_confirmed`.
- `campaigns.get_budgets`, `set_weekly_budget`, `set_daily_budget`, `set_bid_strategy`;
  `verify=True` перечитывает бюджеты и бросает `ApiError` с обоими значениями.
- `Settings.daily_budget_cap` (`YANDEX_DIRECT_BUDGET_CAP`) и
  `require_confirm_for_money` (`YANDEX_DIRECT_REQUIRE_CONFIRM_MONEY`, по умолчанию `True`).
- `money.py`: `to_money_units` (×1 000 000), `from_money_units` (`Decimal` с 6 знаками),
  `monthly_to_weekly` (округление до копеек).
- `AdGroupItemBids.bid_type` и `set_bid(..., bid_type=...)`: `search` (`Bid`) / `network` (`ContextBid`).

### Слой 4 — таргетинг
- `constants.py`: матрица «тип группы × вид нацеливания» (`is_allowed`, `explain`,
  `keyword_conflict`), префиксы типов интереса (`segment_external_id`).
- `models/targeting.py`: `DemographicsSpec`, `InterestSpec`, `RetargetingSpec`,
  `RetargetingList`, `RetargetingTarget`, `InterestTarget`, `DemographicsTarget`, `ContextTarget`.
- `ContextTarget` всегда сообщает `ValidationError`: контекстного нацеливания в Direct API v5 нет.
- `client.retargeting_lists` (`retargetinglists` add/update/delete/get,
  `list_for_group_type`, `create_audience_segment`).
- `client.targeting`: `resolve_demographics`, `resolve_interest`, `demographic_segment_names`,
  `create_audience_target`.
- `AutotargetingSetting`, `DynamicSiteAdGroup`, `DynamicFeedAdGroup`.

### Слой 5 — E2E-сборка запуска (в `scripts/`, вне пакета)
- `scripts/_launch_common.py`: `LaunchResult`/`LaunchStep`/`PartialIds`, `preflight`,
  `resolve_geo`, `moderate_ads`, `resume_ads`, `poll_ads`, `rollback` (suspend → archive →
  delete → удаление загруженных изображений, без исключений), `ReuseCache`.
- `scripts/launch_rsy.py` — классическая РСЯ (нужен готовый `CreativeId`).
- `scripts/launch_epk.py` — ЕПК: `adimages/add` → `UnifiedCampaign` → `UnifiedAdGroup` →
  `ResponsiveAd` → модерация.
- `dry_run=True` — ноль сетевых вызовов; имя без маркеров `E2E`/`TEST`/`ТЕСТ` требует `confirm=True`.

---

## 3. Что изменено

| Изменение | Причина | Статус |
|---|---|---|
| `AdImage` → `ImageAdRef` (алиас сохранён) | поле называется `AdImageHash`, а не ID | совместимо |
| `creatives` — только чтение; `creatives/add` для баннерных креативов не существует | API создаёт лишь `VideoExtensionCreative` | breaking для кода, полагавшегося на создание креативов |
| `CpmBannerAdBuilderAd` вместо `BannerAd` в `ads/add` | в `ads/add` нет полей `Title`/`Text`/`ImageId` | breaking |
| Удалены `adimages/update`, `adimages/unbind`, `adimages/remove` | таких методов в API нет | breaking |
| `adgroups/add` больше не отправляет `Type` | API отвергает параметр | исправление контракта |
| `ads.update_text(auto_clamp=True)` сохранён | решение D3: BC важнее нового поведения | совместимо |
| `ads.create_with_payload`: `campaign_id`/`type_` больше не отправляются | `ads/add` их отвергает (ошибка 8000) | совместимо (параметры остались) |
| `readonly=True` блокирует все мутирующие методы, включая новые | DoD №4 | расширение |
| `campaigns.add` чанкуется по 10 | фактический лимит метода | исправление |
| `clients.get`: `FieldNames` → `[ClientInfo, Restrictions]`; `Restrictions` парсится из списка `{Element, Value}`; `ClientInfo` читается как строка | живой `clients/get` отвергал прежние имена полей и плоскую форму ответа (L3, 09.10.2026) | исправление контракта |
| `region_ids=[0]` и пустой список отвергаются локально | ошибка приходит только из API | исправление |
| `campaigns.set_weekly_budget`: CPM с сетевой стратегией, отличной от `MANUAL_CPM`, требует явного `strategy=` | иначе weekly budget молча переключал бы стратегию (D2) | расширение предохранителя |
| Версия `0.5.0` → `1.0.0`, `Development Status` → `Production/Stable` | первая стабильная версия | — |

---

## 4. РСЯ-часть (v5)

- Кампании: `CpmBannerCampaign`, `TextCampaign`; недельный бюджет — в
  `CpmBannerCampaign.BiddingStrategy.Network.ManualCpm.WeeklySpendLimit`.
- Группы: `CpmBannerAdGroup` (подтипы `KEYWORDS` и `USER_PROFILE`), `TextAdGroup`,
  `SmartAdGroup`, `DynamicSiteAdGroup`, `DynamicFeedAdGroup`.
- Объявления: `CpmBannerAdBuilderAd` (`create_rsya_banner`) и `AdText`
  (`create_with_payload` для поисковых объявлений).
- **Креатив обязателен:** баннерный креатив создаётся только в веб-интерфейсе
  Директа, API его не создаёт (D11). SDK даёт два пути: `creative_id` либо поиск
  по имени через `creatives.image_creative_ids(names=[...])` и кэш переиспользования.
- Гео задаётся на группе через `RegionIds`; `[0]` и пустой список отвергаются.

---

## 5. ЕПК-часть (v501)

- Кампания: `UnifiedCampaign` с секциями `BiddingStrategy.Search`/`Network`,
  недельным бюджетом, `CounterIds` (Метрика) и `PriorityGoals`.
- Стратегии типизированы и валидируются: стратегии из `UNIFIED_STRATEGY_REQUIRES_BUDGET`
  требуют недельный бюджет, из `UNIFIED_STRATEGY_REQUIRES_GOAL` — `goal_id`
  (цели Метрики выбирает пользователь, угадывать их SDK не будет).
- Группа: `UnifiedAdGroup` (гео здесь же — тот же `RegionSelector`).
- Объявление: `ResponsiveAd`; изображения — `ad_images.add(...)` →
  `AdImageHashes`. Это и есть полностью автоматический сценарий
  «картинка → объявление с картинкой» (D11).
- Маршрутизация: `create_unified`/`update_unified`/`get_unified`/`delete_unified`,
  а также автоматический выбор `v501` по типу билдера; v5-методы остаются на `v5`.

---

## 6. v5 vs v501 и Client-Login

- Одна версия API на транспорте, переключается параметром; сервисы не знают о версии —
  она определяется типом переданного билдера или явным `api_version`.
- `api_url` может быть задан целиком (`https://api.direct.yandex.com/json/v5` или
  `/v501`): версия вырезается из базового URL и подставляется ровно один раз.
- `client_login` необязателен (D4): без него `Client-Login` не отправляется —
  прямой доступ рекламодателя; с ним — агентский доступ к чужому клиенту.
  Все три сценария (задан / не задан / пустая строка) покрыты тестами.

---

## 7. Tests

- Всего **660 тестов**, все зелёные; HTTP только через `responses`, реальных
  запросов в `pytest` нет (AGENTS.md §5).
- Покрытие пакета — **96 %**, новые модули ≥ 90 %
  (`campaigns.py` 99 %, `models/ad.py` 99 %, `auth.py` 94 %, `cache.py` 91 %,
  `region_selector.py` 92 %, `models/targeting.py` 97 %, `budgets.py` 95 %).
- Файлы этапа:

| Файл | Тестов | Содержание |
|---|---|---|
| `tests/test_task04_stage0.py` | 38 | фундамент: версии, лимиты, ошибки, batch, логи, валидация |
| `tests/test_task04_stage1.py` | 29 | справочники, кэш, `RegionSelector`, лимиты клиента |
| `tests/test_task04_stage2a.py` | 45 | классическая РСЯ: снапшоты payload, креативы, adimages |
| `tests/test_task04_stage2b.py` | 23 | ЕПК: `UnifiedCampaign`, `ResponsiveAd`, маршрутизация v501 |
| `tests/test_task04_stage3.py` | 29 | деньги, стратегии, бюджеты, cap/confirm (+3 D2) |
| `tests/test_task04_stage4.py` | 48 | демография, интересы, ретаргетинг |
| `tests/test_task04_stage5.py` | 20 | E2E-сборка запуска и компенсации |
| `tests/test_task04_stage7.py` | 70 | L2-контракты по всем слоям |
| `tests/test_task04_stage7_quality.py` | 52 | OAuth, сервисные ветки, модели объявлений |
| `tests/test_task04_stage8.py` | 19 | сценарии live-скрипта |

- Регрессия: существовавшие тесты 0.5.0 не удалены и не ослаблены; два теста
  обновлены осознанно — они кодировали заведомо неверные payload'ы
  (`test_ads_create_with_payload`), которые API отвергала.
- Проверки качества (AGENTS.md §3):
  ```text
  ruff check .                     → All checks passed
  mypy yandex_direct_api_client    → Success: no issues found in 55 source files
  pytest                           → 660 passed
  ```

---

## 8. Live smoke

- Постоянный скрипт: `scripts/smoke_campaign_live.py --scenario S-01…S-05|all`.

| Сценарий | Содержание |
|---|---|
| `S-01` | авторизация, лимиты клиента, справочник регионов |
| `S-02` | гео: 5 регионов вне МСК/СПб/ЛО/МО и «вся РФ кроме четырёх» |
| `S-03` | классическая РСЯ: кампания → группа → объявление → чтение → удаление |
| `S-04` | ЕПК: `adimages/add` → кампания → группа → `ResponsiveAd` → чтение → удаление |
| `S-05` | отчёт по кампании: показы, клики, CTR, стоимость |

- Контур D9 соблюдён в коде: сущности только тестовые (имя с `SDK Smoke Test …`),
  всё остаётся в `DRAFT`, модерация и показы не включаются, самоочистка
  `rollback(..., confirm=True)` выполняется всегда, при провале — ненулевой код
  возврата, OAuth-токен не выводится никогда, выводятся ID сущностей,
  `RequestId` и этап ошибки.

### 8.1. Подтверждено живым прогоном (09.10.2026, креды владельца)

- **Авторизация и лимиты клиента (`S-01`, часть 1) — ПРОЙДЕНО.**
  `clients/get` отвечает, `campaigns/list` возвращает 27 кампаний,
  `can_create_campaign` считает лимиты (`CAMPAIGNS_TOTAL_PER_CLIENT=3000`,
  `CAMPAIGNS_UNARCHIVED_PER_CLIENT=1000`).
- При первом же live-вызове вскрылся **дефект контракта `clients/get`** (F-1.3):
  SDK отправлял `FieldNames = [Id, Login, Name, Currency, TimeZone, Agency,
  Restrictions]` и парсил несуществующую плоскую форму ответа. Фактический API
  принимает ровно два имени (`ClientInfo`, `Restrictions`), а `ClientInfo`
  приходит **строкой** (отображаемое имя клиента), `Restrictions` — списком
  `{Element, Value}`. Исправлено в `services/clients.py`; три mock-теста
  (`test_task04_stage1/5/8`) приведены к фактической форме. `ruff`/`mypy --strict`
  чисто, `pytest` — **660 passed**.

### 8.2. Миграция слоя 1 (`dictionaries` → v501) — выполнена 10.10.2026

Сервис `dictionaries` мигрирован под актуальный контракт `v501`:

| Что сверено живым запросом | Было (mock) | Стало (v501) |
|---|---|---|
| Формат запроса | `params: {"getGeoRegions": {...}}` | `params: {"DictionaryNames": ["GeoRegions"]}` |
| Фильтр по стране | `CountryRegion: "RUC"` | фильтра нет — отдаётся всё дерево (16528 регионов) |
| Поля региона | `ParentGeoRegionId`, `CountryRegion`, `IsArea` | `GeoRegionId`, `GeoRegionName`, `GeoRegionType`, `ParentId` |
| Язык имён | русские | английский по умолчанию; `Accept-Language: ru` → русские |
| Справочники `AdTypes`/`Sites`/`RetargetingLists`/`BingTypes`/`Keywords` | есть как под-объекты | в `dictionaries/get` v501 **отсутствуют** — остаются на v5 |

**Изменения:**
- `geo_regions("RUC")` — больше не фильтрует по стране на сервере; клиент фильтрует
  по `GeoRegionType`/`ParentId` локально (через `RegionSelector`).
- `GeoRegion` модель: поля `region_type` (`GeoRegionType`), `parent_id` (`ParentId`);
  `country_region` и `is_area` убраны. `is_top_level` проверяет `region_type == "country"`.
- `RegionSelector` работает с v501 иерархией; исключаемые регионы резолвятся
  динамически из словаря (названия в v501 отличаются от v5).
- Часть словарей (`RetargetingLists`, `Sites`, `AdTypes`, `BingTypes`, `Keywords`,
  `GeoHierarchy`) осталась на v5 — их нет в v501.

**Breaking change** → MAJOR версия + запись в `CHANGELOG.md` (см. §3).  
После миграции: **S-01, S-02, S-04, S-05 — ОК на живом аккаунте.**

---

## 9. Ограничения

1. **Классическая РСЯ требует готового `CreativeId`.** Баннерные креативы API не
   создаёт; автоматический media-flow реализован на ЕПК (D11).
2. **Живой прогон частичен:** S-03 (классическая РСЯ) требует ручной шаг в веб-UI —
   на аккаунте нет креативов правильного типа (`IMAGE_CREATIVE` не подходит для
   `CPM_BANNER_CAMPAIGN`). S-01, S-02, S-04, S-05 — проходят автоматически.
3. **Контекстное нацеливание не поддерживается API v5** — `ContextTarget`
   всегда выбрасывает `ValidationError`; демография, интересы и поведение
   задаются сегментами типа `AUDIENCE`.
4. **Недельный бюджет для `TEXT_CAMPAIGN` не управляется автоматически:**
   `set_weekly_budget` для текстовых кампаний бросает `ValidationError` —
   weekly-budget в ней живёт внутри поисковой стратегии, а для перезаписи нужен
   полный блок из `campaigns/get`, который `get_budgets` не возвращает.
5. **Недельный бюджет для CPM требует `MANUAL_CPM`:** если живая сетевая стратегия
   CPM‑кампании отлична от `MANUAL_CPM` (например `MAX_CLICKS`/`MAX_SHOWS`),
   `set_weekly_budget` без явного `strategy=MANUAL_CPM` бросает `ValidationError` —
   смена стратегии должна быть намеренной (D2).
6. **Дневной бюджет (`DailyBudget`) оставлен deprecated escape-hatch** —
   Яндекс переводит кампании на недельные бюджеты.
7. **`adimages/update`/`unbind` не реализованы:** таких методов в API нет.
8. **Лимиты символов и ставок** проверяются по константам, актуальным на
   30.09.2026; редкие поля стратегий остаются escape-hatch (`extra`/`dict`).

---

## 10. Что осталось

- Закоммитить изменения и выпустить тег `v1.0.0` — **выполнено** (commit `0c58cf4`, tag `v1.0.0`).
- Не в объёме STAGE_05 (отдельные задачи): автооптимизация ставок, стратегии по
  новым полям API, интеграции уровня оркестратора.

---

## 11. Решение D8 (итог)

Отчёт этапа создан **одним файлом рядом с заданием** — `tasks/task04_report.md`
(AGENTS.md §5.1), написан **по завершении всех этапов**, включая решения,
ограничения и честную отметку о фактическом исходе live-прогона: авторизация,
лимиты, гео, ЕПК и отчёты подтверждены на реальных кредах, классическая РСЯ
требует веб-UI креатив (D11).

В `tasks/` для STAGE_05 осталось одно задание этапа — `tasks/task04.md`;
исходные ТЗ этого этапа (`tasks/task04_kilo.md`, `tasks/task04_chatgpt.md`)
удалены. Файлы предыдущих этапов (`task02*`, `task03*`) не трогались: удаление
чужих документов — не решение агента, их судьба решается владельцем.