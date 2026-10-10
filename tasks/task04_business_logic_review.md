# Обсуждение: граница ответственности SDK и бизнес-приложения

**Статус:** к обсуждению, **реализация отложена**.
**Дата:** 01.10.2026
**Контекст:** `tasks/task04.md`, `tasks/task04_report.md` (STAGE_05, версия 1.0.0)
**Блокер:** сначала живой прогон `scripts/smoke_campaign_live.py --scenario all`
на креды владельца (D9). До него любые правки в поведении SDK делать нельзя —
иначе непроверенный код снова уйдёт в непроверенный релиз.

---

## 1. Вопрос

Критерий, который предъявляется к SDK: **вся бизнес-логика отсутствует, пакет
является только транспортом**. Решения по бизнесу и «придумывание» кампаний
принимаются в бизнес-приложении.

**Ответ по текущему состоянию: критерию соответствует не полностью.**
Транспортный слой чистый, но в пакете есть десять мест, где SDK принимает
бизнес-решение сам.

---

## 2. Что соответствует критерию (менять не нужно)

| Слой | Файл | Почему это транспорт, а не бизнес |
|---|---|---|
| HTTP-вызовы, версии API | `transport.py` | `v5`/`v501`, URL, заголовки, `Client-Login` |
| Batch, чанкинг, ошибки | `services/_base.py` | авто-чанкинг по лимитам, `BatchResult`, классификация ошибок |
| Retry, rate-limit, redaction | `retry.py`, `logs.py` | инфраструктурная надёжность |
| Валидация лимитов API | `validation.py`, `models/targeting.py:_validate_rules` | контракт документации, а не бизнес-правило |
| Матрица «группа × нацеливание» | `constants.py:is_allowed` | ограничение API v5 |
| Резолв гео | `region_selector.py:resolve()` | поиск имени в справочнике; бизнес-гео не зашито |
| Кэш справочников | `cache.py` | инфраструктура |
| Модели, `to_payload`/`from_dict` | `models/*` | сериализация, без решений |
| E2E-сборка запуска | `scripts/_launch_common.py` | **вне пакета**, в `scripts/` — корректно |

Отдельно проверено и не найдено: генерации кампаний, ставок, бюджетов, ключевых
слов, audiences; функций вида `plan`/`decide`/`choose`/`recommend`/`optimize`;
магических значений ставок (`_\d{5,7}`); хардкода российских регионов в коде
(найден только в docstring примера).

---

## 3. Нарушения: где SDK решает за бизнес

### Категория A — критичные (решение необратимо, дефолт неявный)

| # | Место | Что зашито | Чем плохо | Статус |
|---|---|---|---|---|
| A1 | `models/targeting.py:489` | `name: str = "SDK audience"` | SDK сам придумывает имя бизнес-сущности. Владелец аккаунта увидит в интерфейсе «SDK audience» вместо названия сегмента компании | ✅ **выполнено** (09.10.2026): `name: Optional[str] = None`, `ValidationError` при отсутствии имени |
| A2 | `models/targeting.py:149` | `GENDER_SEGMENT_NAMES = {"Мужчины", "Женчины"}` | русская локализация зашита в код. На клиенте с другой локалью справочника резолв пола упадёт или найдёт не тот сегмент | ✅ **выполнено** (09.10.2026): A2.2 — `GENDER_SEGMENT_NAMES` удалено; `DemographicsSpec.gender_names` обязательно при `gender != ALL`; вспомогательный `TargetingService.demographic_segment_names("GENDER")` |
| A3 | `region_selector.py:123` | `country_region: str = "RUC"` | страна выбрана за бизнеса. `RUC` — не универсальный дефолт | ✅ **выполнено** (09.10.2026): дефолт `RUC` оставлен, явно подсвечен в docstring + комментарии в коде |
| A4 | `region_selector.py:113-120` | В docstring зашит конкретный бизнес-запрос: «вся РФ, кроме Москвы, МО, СПб и ЛО» | документация SDK не должна содержать запрос конкретного клиента | ✅ **выполнено** (09.10.2026): бизнес-пример вырезан, заменён нейтральным `exclude=["Region A", "Region B"]` |
| A5 | `services/budgets.py:168` | `set_weekly_budget_in_campaign` для CPM **принудительно перезаписывает** `Network.BiddingStrategyType → MANUAL_CPM` | вызов «поставить бюджет» молча **меняет стратегию кампании**. Побочный эффект денежной мутации, не видимый в сигнатуре метода | ✅ **выполнено** (09.10.2026): A5.2 — `strategy:` теперь не молчаливо перезаписывает; при конфликте бросает `ValidationError`

### Категория B — дефолты с escape-hatch (терпимы, но спорны)

| # | Место | Дефолт | Escape-hatch | Статус |
|---|---|---|---|---|
| B1 | `models/campaign_payloads.py:418` | `TextCampaign(weekly_budget=…)` → `AVERAGE_CPC` | `bidding_strategy=` | ✅ B1/B2-2: warning при выборе стратегии по умолчанию |
| B2 | `models/campaign_payloads.py:291` | `CpmBannerCampaign(weekly_budget=…)` → `MANUAL_CPM` | `bidding_strategy=` | ✅ B1/B2-2: warning при выборе стратегии по умолчанию |
| B3 | `models/campaign_payloads.py:732` | `UnifiedCampaign`: `search=AVERAGE_CPC, network=NETWORK_DEFAULT` | `search`/`network` явно | ✅ B1/B2-2: warning при `None` |
| B4 | `models/campaign_payloads.py:558` | `PriorityGoal.value = 1` | явный параметр | ✅ B1/B2-2: warning при `None` |
| B5 | `models/campaign_payloads.py:186` | `daily_budget_mode = "STANDARD"` | явный параметр | ✅ B1/B2-2: warning при `None` |
| B6 | `models/campaign_payloads.py:422` | `network_enabled=False` → `SERVING_OFF` | `network_enabled=True` (→ `MAX_CPM`) | ✅ B1/B2-2: warning при `None` |
| B7 | `models/ad_group_payloads.py:264` | `AutotargetingSetting.enabled = True` | явный параметр | ✅ B1/B2-2: warning при `None` |
| B8 | `services/campaigns.py:655` | по стратегии выбирается форма тела при `set_weekly_budget` | эвристика внутри | ✅ закрыт: D1 (TEXT→`ValidationError`, а не `UnifiedCampaign`) + A5 (стратегия CPM не молча перезаписывается) |

**Что это значит:** «escape-hatch» — это уже существующий способ переопределить дефолт (явный параметр или секция `bidding_strategy`). Для B1–B7 владелец попросил, чтобы **выбор по умолчанию не шёл незаметно**: SDK эмиттирует `logging.warning`, а явное значение (escape-hatch) подавляет его. B1/B2‑1 (делать стратегию обязательной) отклонено владельцем — breaking для README и ~9 тестов; для остальных B‑дефолтов аналогичный warn‑and‑override применяется без смены сигнатур (escape-hatch уже есть).

---

## 4. Побочно найденные дефекты (не про границу ответственности)

Это не про бизнес-логику, это баги — НАЙДЕНЫ во время аудита, **D1 исправлен**
(коммит pending подтверждения владельца), **D2 закрыт** по решению владельца
(09.10.2026): требовать явной `strategy=` для CPM с не-`MANUAL_CPM`.

### D1. `services/campaigns.py:655-663` — неверная форма тела для `TEXT_CAMPAIGN` — ИСПРАВЛЕН

`set_weekly_budget` ветвился по `known.strategy == STRATEGY_AVERAGE_CPC`.
Но `AVERAGE_CPC` — и поисковая стратегия `TEXT_CAMPAIGN`, и `UNIFIED_CAMPAIGN`,
поэтому текстовой кампании собиралось тело `{"Type": "TEXT_CAMPAIGN",
"UnifiedCampaign": {...}}` — несоответствие блока и типа → `InvalidRequest`.
`_weekly_block_of` (`budgets.py:130`) при этом не читал `TextCampaign`, так
что `weekly` был `None` даже при наличии бюджета.

```python
if known is not None and known.strategy == STRATEGY_AVERAGE_CPC:
    body["UnifiedCampaign"] = {...}   # campaigns.py:656
```

Воспроизведено на разборе ответа API:

```
вход:  TEXT_CAMPAIGN, Search.AVERAGE_CPC.AverageCpc.WeeklySpendLimit=500000000
       read_budget() -> type=TEXT_CAMPAIGN, strategy=AVERAGE_CPC
       => set_weekly_budget выберет ветку UnifiedCampaign   # неверно
```

Итог: у текстовой кампании недельный бюджет в `Search.AverageCpc` не пишется
туда, куда ожидает API, а `body["Type"]` остаётся `TEXT_CAMPAIGN`. Форма тела
не соответствует типу кампании.

Дополнительно: `_weekly_block_of` (`budgets.py:130`) обходил только
`CpmBannerCampaign` и `UnifiedCampaign` — `TextCampaign` не смотрел вовсе,
поэтому `read_budget` для текстовой кампании возвращал `weekly=None`, хотя
бюджет в ответе есть.

**Фикс (минимальный, без костылей):**

1. `services/campaigns.py:655` — условие теперь `known.type == "UNIFIED_CAMPAIGN"
   and known.strategy == STRATEGY_AVERAGE_CPC`. `TEXT_CAMPAIGN` и
   `CPM_BANNER_CAMPAIGN` идут в `set_weekly_budget_in_campaign` (CPM работает,
   TEXT → `ValidationError` — честное отказ вместо неверного тела). Для
   `UNIFIED_CAMPAIGN` `api_version` остаётся `v501`.
2. `services/budgets.py:130` — `"TextCampaign"` добавлен в список блоков
   `_weekly_block_of`, теперь `read_budget` видит недельный бюджет текстовой
   кампании.
3. Тесты в `tests/test_task04_stage3.py`:
   `test_read_budget_text_campaign_weekly` (читается `weekly=6`),
   `test_set_weekly_budget_text_campaign_rejected` (TEXT → `ValidationError`,
   без выходящего `update`).

Проверено: `ruff`/`mypy --strict` чисто, `pytest` — **660 passed** (D1: +2, D2: +3).
Регрессий для `UNIFIED_CAMPAIGN`/`CPM_BANNER_CAMPAIGN` нет (ветвь по стратегии
не удалена, только дополнена проверкой типа).

### D2. `models/targeting.py:154` + `budgets.py:170` — см. A2 и A5

Уточнение по A5: `set_weekly_budget_in_campaign` вызывается из
`campaigns.set_weekly_budget` **только** если кампания не является
`UNIFIED_CAMPAIGN` с `AVERAGE_CPC` (после фикса D1). Для остальных типов — CPM —
он же принудительно ставит `MANUAL_CPM`/`SERVING_OFF`. Если у CPM-кампании была
другая сетевая стратегия (`MAX_CLICKS`, `MAX_SHOWS`) — бюджет перезапишется
`MANUAL_CPM`.

**Решение владельца (09.10.2026):** требовать явной `strategy=`.

Реализовано на уровне сервиса `CampaignsService.set_weekly_budget`:
- если `known.type == CPM_BANNER_CAMPAIGN` и `known.strategy is not None` и
  `known.strategy != MANUAL_CPM` и **не передан** `strategy` → `ValidationError`
  (weekly budget поддерживается только при `MANUAL_CPM`; смена стратегии должна
  быть намеренной).
- при явном `strategy=MANUAL_CPM` смена стратегии разрешается (сознательная
  перезапись); при `strategy` равной другому значению — передаётся как escape-hatch.

A2 (`GENDER_SEGMENT_NAMES` удалены) и A5.2 (body-level guard в
`set_weekly_budget_in_campaign`) остаются в силе. D2 закрыт: побочный эффект
денежной мутации больше не скрыт — вызов без `strategy=` падает с понятной
ошибкой. +3 unit‑теста (`test_set_weekly_budget_cpm_with_other_strategy_requires_explicit`,
`test_set_weekly_budget_cpm_explicit_manual_cpm_overrides_other`,
`test_set_weekly_budget_cpm_already_manual_cpm_succeeds`).

### D3. `services/clients.py` — неверный контракт `clients/get` — ИСПРАВЛЕН (L3, 09.10.2026)

При первом живом `S-01` вызов `clients/get` падал с `ApiError: Invalid request`.
SDK отправлял `FieldNames = [Id, Login, Name, Currency, TimeZone, Agency,
Restrictions]` и парсил ответ как плоский объект клиента. Живой API:

- принимает ровно два имени — `ClientInfo` и `Restrictions` (иные → `InvalidRequest`);
- `ClientInfo` возвращает **строкой** (отображаемое имя клиента), а не объектом;
- `Restrictions` — список `{Element, Value}` (12 записей), а не словарь;
- поля `Id`/`Login`/`Currency`/`TimeZone` сервис вообще не отдаёт.

**Фикс (минимальный, сигнатуры публичных методов не меняются):** `get()` шлёт
`[ClientInfo, Restrictions]` и берёт первый элемент списка `Clients`;
`ClientInfo.from_dict` читает имя из строковой секции; `restrictions` разбирает
список `{Element, Value}` (словарная форма оставлена escape-hatch для моков).
`preflight.describe()` честно печатает `клиент=?, валюта=?` — API эти поля не
возвращает. Мок-тесты `test_task04_stage1/5/8` приведены к фактической форме.
Проверено: `ruff`/`mypy --strict` чисто, `pytest` — **660 passed**; live `S-01`
часть «авторизация + лимиты» проходит (`кампааний=23`, лимиты распарсены).

### D4. `services/dictionaries.py` + `region_selector.py` — дрейф контракта справочников — НАЙДЕН (L3, 09.10.2026), требует решения владельца

Live `S-01` (гео-часть) и `S-02` падают: справочник `dictionaries` построен на
устаревшем контракте и сверялся только mock-моками. Актуальная документация и
живой запрос показывают:

- сервис переехал на **`v501`**; формат запроса — `params: {"DictionaryNames":
  [...]}`, а не под-объекты `{"getGeoRegions": {...}}` (иначе — «Omitted required
  parameter DictionaryNames»);
- **нет фильтра по стране** и поля `CountryRegion` в ответе: `GeoRegions` отдаёт
  всё мировое дерево (17 344 записи) с полями `GeoRegionId/GeoRegionName/
  GeoRegionType/ParentId`; РФ — поддерево узла `Country` «Russia» (`GeoRegionId=225`);
- имена регионов **англоязычны по умолчанию**; `Accept-Language: ru` (в SDK не
  отправляется) возвращает русские («Москва», «Санкт-Петербург»);
- словарей `AdTypes`/`Sites`/`RetargetingLists`/`BingTypes`/`Keywords` в
  `dictionaries/get` **больше нет**.

Следствие: `geo_regions("RUC")` → `InvalidRequest`; `RegionSelector.resolve()`
не может построить «вся РФ кроме четырёх» (нет страновой выборки). Это **миграция
слоя 1** со сменой публичного контракта (`dictionaries`-методы, семантика
`geo_regions`, заголовок локали в транспорте, судьба удалённых словарей) → по
AGENTS.md §6 breaking → MAJOR + `CHANGELOG`, нужно явное решение владельца.
В текущем diff **не выполнялась** (не молчаливая правка проверяемого 1.0.0).

---

## Примечание: `l1.txt` — выполнено

`l1.txt` (22 КБ) — выгрузка официальной документации Yandex **Direct** API
(не Metrika): 276 строк, 268 из них ссылки (`https://yandex.com/dev/direct/...`)
— это **лишь оглавление**, а не тело спецификации (`llms-full.txt` —
мнегабайтный, меняется со временем). Больше не в репо. Канонические URL
добавлены в `AGENTS.md` (ссылка на `index.yaml`, `llms-full.txt` + `webfetch`
по запросу); текст справки в репо не вендорится.

---

## 5. Варианты решения (нужно выбрать)

### Вариант 1 — «Строгий транспорт»
Все дефолты A и B становятся **обязательными параметрами**. Пустой
`UnifiedCampaign()` или `CpmBannerCampaign()` без стратегии → `ValidationError`.

- **Плюс:** критерий выполнен буквально, ни одного неявного решения.
- **Минус:** breaking change для 1.0.0; каждый вызов в `scripts/` и в 638
  тестах станет длиннее; типовое использование («создай ЕПК с недельным
   бюджетом») превращается в 8 строк вместо одной, а тестов стало 660 вместо 638.

### Вариант 2 — «Транспорт + явная политика»
Дефолты A1-A5, B1-B8 **убираются или делаются обязательными**, но SDK
получает отдельный слой `presets.py` вне транспорта, где каждая стратегия —
явно именованный пресет: `STRATEGY_MANUAL_CPM`, `STRATEGY_AVERAGE_CPC`.
Бизнес-приложение выбирает пресет **явным вызовом**.

- **Плюс:** критерий выполнен; типовые сценарии остаются короткими; в коде
  видно, где кончается транспорт и начинается политика.
- **Минус:** новая публичная поверхность; нужно продумать, где живёт слой.

### Вариант 3 — «Минимальный»
Оставить B как есть (это честные дефолты с escape-hatch), убрать только
критичные A1-A5 и починить D1.

- **Плюс:** маленький diff, ничего не ломает.
- **Минус:** критерий формально не выполнен — дефолты стратегий остаются.

### Вариант 4 — «Документация»
Ничего не менять, только явно описать в README: «дефолты SDK — это примеры,
бизнес-приложение обязано задавать свои значения».

- **Плюс:** ноль риска перед релизом.
- **Минус:** критерий не выполнен, это передача ответственности на
  дисциплину пользователя.

---

## 6. Что нужно от владельца

1. **Какой вариант** из раздела 5 (или свой).
2. **(закрыто A2)** — справочник локализован; SDK не зашивает имена полов, а
   требует `gender_names` от бизнеса (discovery через `demographic_segment_names`).
3. **(закрыто A3)** — `country_region="RUC"` оставлен дефолтом, подсвечен в коде/доке.
4. **Имена сущностей** — закрыто: A1 решено (имя обязательно, `name: Optional[str]=None`).
5. **B-дефолты стратегий** — escape-hatch, не блокируют 1.0.0; B8 пересекается с A5 и закрыт.
6. **A5 (CPM→`MANUAL_CPM`)** — закрыто: A5.2 (не перезаписывать молча; `strategy=`).

> Вопросы по B1–B8 (дефолты с escape-hatch) не требуют немедленного решения —
> см. §5. Если владелец захочет убрать дефолты полностью (B), это уже minor/major.

---

## 7. Статус на 09.10.2026

- ✅ **A1–A5** выполнено; B1–B7 закрыты warn‑and‑override; `ruff`/`mypy --strict` чисто,
  `pytest` — **660 passed** (+3 D2).
- ✅ **D1** починен (+2 теста).
- ✅ **D2** закрыт по решению владельца (09.10.2026): CPM с не-`MANUAL_CPM` требует явного `strategy=`; service-level guard +3 теста.
- ✅ **D3** (`clients/get`) починен по живому прогону 09.10.2026: `[ClientInfo,
  Restrictions]`, `Restrictions` из `{Element, Value}`; `pytest` — 660 passed.
- ⛔ **D4** (`dictionaries` + `RegionSelector`) — live-прогон 09.10.2026 вскрыл
  дрейф контракта (справочник на `v501`, `DictionaryNames`, нет страновой
  выборки/`CountryRegion`, англ. имена без `Accept-Language`). Требует решения
  владельца (breaking → MAJOR), в текущем diff не выполнялась.
- ⏳ Живой прогон `scripts/smoke_campaign_live.py`: авторизация/лимиты подтверждены;
  гео (`S-01`/`S-02`) и `S-03…S-05` ждут миграции D4.
- ⏸️ Коммит/релиз 1.0.0 — ждут явного разрешения владельца.

### Дальнейшие шаги
1. **D4:** принять решение по миграции `dictionaries`/`RegionSelector` на `v501`
   (AGENTS.md §6) — затем допрогонеть `scripts/smoke_campaign_live.py --scenario all`
   и зафиксировать вывод в `task04_report.md` §8.
2. Проверить D1 на живом `campaigns/get` для `TEXT_CAMPAIGN` (после снятия D4-блокировки гео).
3. `ruff check .`, `mypy yandex_direct_api_client`, `pytest` — уже зелёные (660 passed).
4. D2 решён — уточнять больше не нужно.

---

## 8. Что не предлагается

- **Не** переносить в SDK оркестрацию запуска кампаний — она уже правильно
  живёт в `scripts/`.
- **Не** добавлять автооптимизацию ставок, подбор стратегий по статистике,
  генерацию ключевых слов — это бизнес-приложение по определению.
- **Не** трогать `RegionSelector` как механизм (D5 из `task04_report.md`
  остаётся в силе) — спорна только строка `country_region = "RUC"`.
