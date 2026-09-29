# task03 — ОТЧЁТ: расширение покрытия клиента (треки A и B)

Версия: **0.4.1 → 0.5.0** (minor bump по AGENTS.md §6: только добавления,
breaking changes нет). Все проверки зелёные: `ruff` / `mypy` / `pytest`.

---

## 1. Трек A — завершение жизненного цикла существующих ресурсов

### A.1. `client.ad_groups` (API `adgroups`)

Было read-only (list, get). Добавлены мутации:

| Метод | Эндпоинт | confirm |
|---|---|---|
| `create(ad_groups)` | `adgroups/add` | — |
| `update(ad_groups)` | `adgroups/update` | — |
| `delete(ids, confirm=False)` | `adgroups/delete` | да |

- `create`/`update` принимают типизированную модель `AdGroup` или raw-dict
  (паттерн `AdGroupInput = Union[AdGroup, Mapping]`), batch-чанкинг по 200.
- Модель `AdGroup` получила `to_new_payload()` / `to_update_payload()`.

**Исправлен баг модели.** По официальному справочнику `adgroups/add|get` поле
называется `NegativeKeywordSharedSetIds` (единственное число) и является
`ArrayOfLong`, то есть приходит/уходит через обёртку `{ "Items": [...] }`,
тогда как `RegionIds` — обычный массив. Прежняя модель использовала неверное
имя (`NegativeKeywordsSharedSetIds`) и голый список. Теперь:
`from_dict` снимает обёртку `Items`, `to_new_payload` её эмитирует.

**Исправлен wiring-баг.** В `client.py` `AdGroupService` конструировался без
`readonly=ro`. После добавления мутаций это означало бы, что `readonly=True`
не блокирует `ad_groups.create/update/delete`. Исправлено — теперь все
мутации корректно под readonly-guard (подтверждено тестом).

### A.2. `client.campaigns` (API `campaigns`)

Добавлены batch-методы управления состоянием (приватный хелпер
`_state_action`, `SelectionCriteria.Ids`, чанкинг по 1000):

| Метод | Эндпоинт | ключ результата | confirm |
|---|---|---|---|
| `suspend(ids)` | `campaigns/suspend` | `SuspendResults` | — |
| `resume(ids)` | `campaigns/resume` | `ResumeResults` | — |
| `archive(ids, confirm=False)` | `campaigns/archive` | `ArchiveResults` | да |
| `unarchive(ids)` | `campaigns/unarchive` | `UnarchiveResults` | — |

### A.3. `client.ads` (API `ads`)

Аналогично + модерация:

| Метод | Эндпоинт | ключ результата | confirm |
|---|---|---|---|
| `suspend(ids)` | `ads/suspend` | `SuspendResults` | — |
| `resume(ids)` | `ads/resume` | `ResumeResults` | — |
| `archive(ids, confirm=False)` | `ads/archive` | `ArchiveResults` | да |
| `unarchive(ids)` | `ads/unarchive` | `UnarchiveResults` | — |
| `moderate(ids)` | `ads/moderate` | `ModerateResults` | — |

Все методы трека A: typed, docstring на русском, item-level ошибки через
`check_item_errors` → `ApiError`; `confirm` только для `delete`/`archive`.

---

## 2. Трек B — новые ресурсы API

Каждый сервис подключён как свойство `client.<name>`, модели с `from_dict` +
`to_new_payload`/`to_update_payload`, имена эндпоинтов подтверждены
официальным справочником (URL в docstring сервиса).

### B.1. `client.negative_keywords` (API `negativekeywordsharedsets`)
- Подтверждено: https://yandex.ru/dev/direct/doc/ru/negativekeywordsharedsets/negativekeywordsharedsets.html
- Методы `add, update, delete, get`; объект `NegativeKeywordSharedSets`,
  поля `Id/Name/NegativeKeywords/Associated`; лимит **30** объектов/Id за вызов.
- Модель `NegativeKeywordSharedSet`. Привязка набора к группе — через
  `AdGroup.NegativeKeywordSharedSetIds` + `ad_groups.update` (не отдельный сервис).

### B.2. `client.audience_targets` (API `audiencetargets`)
- Подтверждено: https://yandex.ru/dev/direct/doc/ru/audiencetargets/audiencetargets.html
- Реальные методы API: `add, delete, suspend, resume, get, setBids`
  (метода `update` НЕТ — смена ставки/приоритета через `setBids`,
  состава — create+delete). Реализовано как `create/delete/suspend/resume/
  set_bids` + `list/get`.
- Объект `AudienceTargets`, поля `Id/AdGroupId/CampaignId/RetargetingListId/
  InterestId/ContextBid/StrategyPriority/State`.
- Модель `AudienceTarget`.

### B.3. `client.retargeting_conditions`
- **Важно про имя эндпоинта.** Отдельный сервис `retargetingconditions`
  НЕ подтверждается актуальным справочником: страницы
  `.../retargetingconditions/...` отдают 404, архивных снимков нет. После
  обновления до единой перфоманс-кампании условия ретаргетинга управляются
  сервисом `audiencetargets` полем `RetargetingListId`
  (подтверждено: https://yandex.ru/dev/direct/doc/en/objects/audience-target).
- Поэтому сервис реализован как обёртка над `audiencetargets`
  (`create/delete/get/list` с фильтром `RetargetingListIds`). Ограничение
  задокументировано в docstring сервиса и модели. Не путать с
  `retargeting_adjustments` (корректировки ставок).
- Модель `RetargetingCondition`.

### B.4. `client.ad_extensions` (API `sitelinks`, `adextensions`)
- Быстрые ссылки: https://yandex.ru/dev/direct/doc/ru/sitelinks/sitelinks.html
  методы `add, get, delete`; объект `SitelinksSets` (`Id` + массив `Sitelink`
  с `Title/Href/Description/TurboPageId`).
- Уточнения: https://yandex.ru/dev/direct/doc/ru/adextensions/adextensions.html
  методы `add, get, delete`; объект `AdExtensions` (`Callout.CalloutText`,
  тип `CALLOUT`).
- Реализовано: `list_sitelinks/get_sitelinks/create_sitelinks/delete_sitelinks`
  и `list_callouts/get_callouts/create_callouts/delete_callouts`
  (обновление = create + delete по семантике API).
- Модели `Sitelink`, `SitelinksSet`, `Callout`.

### B.5. Bidding strategies — справка (без нового сервиса)
Стратегия задаётся внутри `campaigns.create/update` (поле `BiddingStrategy`).
Отдельный сервис `biddingstrategies` НЕ создан — это reference-данные, не CRUD
(см. §7).

---

## 3. Созданные / изменённые файлы

**Новые сервисы:**
- `yandex_direct_api_client/services/negative_keywords.py`
- `yandex_direct_api_client/services/audience_targets.py`
- `yandex_direct_api_client/services/retargeting_conditions.py`
- `yandex_direct_api_client/services/ad_extensions.py`

**Новые модели:**
- `yandex_direct_api_client/models/negative_keyword.py`
- `yandex_direct_api_client/models/audience_target.py`
- `yandex_direct_api_client/models/retargeting_condition.py`
- `yandex_direct_api_client/models/ad_extension.py`

**Новые тесты:**
- `tests/test_task03_track_a.py`
- `tests/test_task03_track_b.py`

**Изменённые (код):**
- `yandex_direct_api_client/models/ad_group.py` — поля `region_ids`,
  `negative_keywords_shared_set_ids`, `to_new_payload`/`to_update_payload`,
  снятие/эмиссия обёртки `Items`, верное имя поля.
- `yandex_direct_api_client/services/ad_groups.py` — `create`/`update`/`delete`.
- `yandex_direct_api_client/services/campaigns.py` — `_state_action` + 4 метода.
- `yandex_direct_api_client/services/ads.py` — `_state_action` + 5 методов.
- `yandex_direct_api_client/client.py` — readonly для `ad_groups`, 4 новых
  сервиса + свойства.
- `yandex_direct_api_client/models/__init__.py`,
  `yandex_direct_api_client/services/__init__.py`,
  `yandex_direct_api_client/__init__.py` — экспорт новых имён.

**Изменённые (версия/доки):**
- `yandex_direct_api_client/_version.py`, `pyproject.toml` — 0.5.0.
- `CHANGELOG.md` — секция `[0.5.0]` (Added + Fixed).
- `README.md` — таблицы методов A + секции сервисов B.

---

## 4. Добавленные unit-тесты

**51 тест** (mock HTTP через `responses`, без живых запросов):
- `test_task03_track_a.py` — **23** теста: `AdGroup` payload/from_dict
  (обёртка `Items`), `ad_groups` create/update/delete (+typed/raw, item-error,
  confirm, empty), `campaigns`/`ads` suspend/resume/archive/unarchive/moderate
  (+item-error, confirm), readonly-guard.
- `test_task03_track_b.py` — **28** тестов: list/get/create/update/delete для
  negative_keywords; create/set_bids/suspend/delete для audience_targets;
  list/create/delete для retargeting_conditions; sitelinks и callouts
  list/create/delete; item-error; confirm; readonly-guard.

Покрытие каждого нового публичного метода: построение запроса, разбор
ответа, item-level ошибки, `confirm`/`readonly`-гарды, typed/raw payloads,
пагинация для `list`.

---

## 5. Результаты проверок

```text
ruff check .                      → All checks passed!
mypy yandex_direct_api_client     → Success: no issues found in 35 source files
pytest -q                         → 156 passed
```

Было 105 тестов (baseline v0.4.1) → стало **156** (+51).

Grep-проверка «вне объёма» в `yandex_direct_api_client/`:
`metrika|openai|llm|mcp|langchain|anthropic` → **пусто**.

---

## 6. Версия и документация

- Версия 0.4.1 → **0.5.0** (`_version.py`, `pyproject.toml`).
- `CHANGELOG.md`: секция `[0.5.0]` — `Added` (треки A и B) и `Fixed`
  (баг модели `AdGroup`, readonly-wiring `ad_groups`).
- `README.md`: обновлены таблицы `campaigns`/`ads`/`ad_groups` (трек A),
  добавлены секции `negative_keywords`/`audience_targets`/
  `retargeting_conditions`/`ad_extensions` (трек B).
- Breaking changes нет: сигнатуры существующих публичных методов не менялись
  (только добавления методов/сервисов).

---

## 7. Что намеренно НЕ сделано

- **`biddingstrategies` как отдельный сервис** — reference-данные, не CRUD;
  стратегия задаётся полем `BiddingStrategy` в `campaigns.create/update` (§B.5).
- **`audiencetargets.update`** — метода нет в API; реализованы `set_bids`
  (ставка/приоритет) и create+delete (состав).
- **Отдельный эндпоинт `retargetingconditions`** — отсутствует в актуальном
  справочнике; реализовано через `audiencetargets` (ограничение задокументировано).
- **`adextensions.update` / `sitelinks.update`** — обновления нет по семантике
  API; обновление = create + delete.
- Бизнес-стратегия, оптимизация ставок, approval-workflow, AI/LLM, MCP,
  Metrika-клиент, cross-system workflows — вне capability-слоя (AGENTS.md/task02).

---

## 8. Ограничения и что остаётся оркестратору

- **`retargeting_conditions` завязан на `audiencetargets`.** Если оркестратор
  работает с legacy-клиентом, где отдельный `retargetingconditions` ещё
  существует, стоит сверить эндпоинт под свою ревизию API. В актуальном v5 —
  только через `audiencetargets`/`RetargetingListId`.
- **Ставки `ContextBid`/цены** в `audiencetargets` передаются целыми числами,
  умноженными на 1 000 000 (валюта пользователя). Клиент НЕ конвертирует —
  это бизнес-семантика, остаётся оркестратору.
- **`negative_keywords` лимит 30** — зашит в чанкинг; количество наборов на
  пользователя тоже ограничено (Clients.get → Restrictions).
- **`moderate`** принимает только объявления со статусом DRAFT; проверка статуса
  — ответственность оркестратора.
- **`archive`/`unarchive`**: `unarchive` недоступен для CONVERTED; лимит
  неархивных кампаний 1000 — мониторинг лимитов вне клиента.
- Клиент остаётся тонким capability-слоем: стратегия показов, распределение
  бюджета, связывание целей Директа с Метрикой, approval-логика — оркестратор.

---

## 9. Живой прогон на реальном аккаунте (дополнение)

После первичной сдачи выполнен живой smoke на аккаунте `DEG13`
(`scripts/smoke_task03_live.py`): созданы кампания (OFF, старт завтра) +
2 группы + 3 объявления (DRAFT), прогнаны новые методы, всё удалено
(кампаний снова 23, сирот нет). **Результат: 18 OK, 5 expected (реальные
state-ограничения DRAFT), 0 FAIL.**

Прогон вскрыл 6 реальных дефектов request-контрактов, которые mock-тесты
ловить не могли (запрос несуществующего `State` у групп; `CampaignId`/`Type`
в `adgroups/update` и `ads/add`; пустой `SelectionCriteria` у `ad_groups.list`).
Все исправлены и закрыты 5 регресс-тестами. Подробности — в
`tasks/task03_live_report.md` и в CHANGELOG (`[0.5.0]` → `Fixed`).

Итоговые проверки после фикса: `pytest` 160 passed, `ruff` чистый, `mypy`
чистый (35 файлов).
