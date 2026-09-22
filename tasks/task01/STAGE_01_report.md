# STAGE_01 — Отчёт

## 1. Краткий итог этапа

Проведён полный аудит репозитория `yandex-direct-api-client` и выполнена
фундаментальная переработка архитектуры: клиент переведён на namespace-API
(`client.campaigns.list()` и т.д.), код разделён по ответственности
(транспорт / модели / сервисы), добавлена авто-пагинация, исправлены
семантические баги моделей и реализован механизм подтверждения опасных
операций (`confirm=True`). Все проверки проходят: 58 тестов, ruff,
mypy --strict.

## 2. Архитектура до изменений

Плоская структура из 8 модулей:

```
yandex_direct_api_client/
├── __init__.py     # экспорты
├── client.py       # ВСЁ: HTTP, retry, чанкинг, пагинация, бизнес-логика (~530 строк)
├── models.py       # все dataclass'ы в одном файле
├── retry.py        # TokenBucket + request_with_retry
├── auth.py         # OAuth code-flow + refresh + CLI
├── config.py       # Settings + env fallback
├── exceptions.py   # иерархия исключений
└── _version.py
```

Публичный API был flat-методами на клиенте:
`get_campaigns()`, `get_ads()`, `get_ads_text_batch()`, `get_stats()`,
`update_ad()`, `add_campaign()`, `delete_ad()`.

## 3. Обнаруженные проблемы

1. **Монолитный `client.py`** — HTTP-транспорт, retry, чанкинг, пагинация
   (отсутствующая), парсинг ответов и бизнес-логика всех ресурсов в одном
   классе. Расширять (добавлять новые ресурсы) означало раздувать этот файл.
2. **Нет пагинации** — API возвращает максимум 10 000 объектов за запрос
   (подтверждено официальной документацией: структура `Page`/`LimitedBy`).
   У клиентов с >10 000 объявлений данные молча терялись.
3. **Неправильный лимит чанкинга** — `SelectionCriteria.Ids` для campaigns/get
   ограничен 1000 элементами (по документации), в коде использовалось 20000.
4. **`StatRow.merged_with` суммировал `bounce_rate`** — математически
   некорректно: bounce_rate это процент, при агрегации по дням нужно
   средневзвешенное (bounces / clicks).
5. **`bounce_rate` вообще не пересчитывался** при агрегации — просто
   `self.bounce_rate + other.bounce_rate`, что могло дать >100%.
6. **Избыточный `threading.Lock`** вокруг `session.post` — `requests.Session`
   потокобезопасен для отдельных запросов; lock лишь создавал сериализацию.
7. **Дублирование моделей** — `AdTextEntry` повторял `Ad` + `AdText`.
8. **Нет защиты опасных операций** — `delete_ad()` удалял данные без
   какого-либо подтверждения.
9. **`DEFAULT_CHUNK_SIZE` в config** — константа объявлена, но после
   рефакторинга не использовалась нигде.
10. **Неполное покрытие ресурсов** — не было `campaigns.update`,
    `campaigns.delete`, `ads.create`, `ads.update` (batch), `ad_groups`.

## 4. Целевая архитектура

```
yandex_direct_api_client/
├── __init__.py          # публичные экспорты
├── client.py            # facade: YandexDirectClient + namespace-свойства
├── _transport.py        # HTTP-транспорт (Session, retry, rate limit, error parsing)
├── config.py            # Settings, defaults, env
├── exceptions.py        # иерархия исключений
├── retry.py             # TokenBucket, request_with_retry (429/202)
├── auth.py              # OAuth (не менялся)
├── models/              # типизированные модели, по файлу на сущность
│   ├── _helpers.py      # to_int/to_float/to_date/to_optional_int
│   ├── campaign.py      # Campaign
│   ├── ad.py            # Ad, AdText
│   ├── ad_group.py      # AdGroup
│   ├── stats.py         # StatRow
│   └── token.py         # TokenResponse
└── services/            # по классу на ресурс
    ├── _base.py         # chunked, fetch_all_pages, ensure_confirmed, лимиты
    ├── campaigns.py     # CampaignService: list/get/create/update/delete
    ├── ads.py           # AdService: list/get/create/update/update_text/delete
    ├── ad_groups.py     # AdGroupService: list/get
    └── reports.py       # ReportService: get_ad_stats + parse_stats_tsv
```

Принципы: без DI-фреймворков, event bus, CQRS, абстрактных базовых классов
сервисов. Разделение только по реальной ответственности. Сервисы получают
`Transport` в конструкторе — это единственная «инъекция», и она тривиальна.

## 5. Выполненные изменения

1. **Извлечён `_transport.py`** — `Transport` инкапсулирует Session, retry,
   token bucket и разбор error-блоков. Сервисы работают только с ним.
2. **Создан пакет `models/`** — модели разнесены по сущностям, общие
   конвертеры в `_helpers.py`, добавлен `AdGroup`, в `Campaign` добавлено
   поле `type`.
3. **Создан пакет `services/`** — по классу на ресурс, общая логика
   (чанкинг, пагинация, confirm, проверка item-errors) в `_base.py`.
4. **`client.py` переписан как facade** — `YandexDirectClient` создаёт
   Transport и четыре сервиса, экспонирует их через свойства-неймспейсы.
5. **Добавлена авто-пагинация** — `fetch_all_pages()` следует за `LimitedBy`
   (официальный механизм постраничной выборки) во всех `list()`-методах.
6. **Исправлены лимиты чанкинга** — campaigns/get: 1000 Ids (было 20000);
   mutate-операции: 200.
7. **Исправлен `StatRow.merged_with`** — bounce_rate теперь средневзвешенное:
   `total_bounces / total_clicks * 100`; ctr пересчитывается от сумм.
8. **Добавлен `confirm=True`** — см. раздел 9.
9. **Удалены артефакты** — `AdTextEntry`, `DEFAULT_CHUNK_SIZE`,
   `threading.Lock`, параметр `chunk_size` конструктора.
10. **Обновлены** README.md, CHANGELOG.md, версия 0.1.0 → 0.2.1.

## 6. Созданные и изменённые файлы

**Созданы:**
- `yandex_direct_api_client/_transport.py`
- `yandex_direct_api_client/models/__init__.py`
- `yandex_direct_api_client/models/_helpers.py`
- `yandex_direct_api_client/models/campaign.py`
- `yandex_direct_api_client/models/ad.py`
- `yandex_direct_api_client/models/ad_group.py`
- `yandex_direct_api_client/models/stats.py`
- `yandex_direct_api_client/models/token.py`
- `yandex_direct_api_client/services/__init__.py`
- `yandex_direct_api_client/services/_base.py`
- `yandex_direct_api_client/services/campaigns.py`
- `yandex_direct_api_client/services/ads.py`
- `yandex_direct_api_client/services/ad_groups.py`
- `yandex_direct_api_client/services/reports.py`
- `STAGE_01_report.md` (этот файл)

**Изменены:**
- `yandex_direct_api_client/client.py` — переписан как facade
- `yandex_direct_api_client/__init__.py` — обновлены экспорты
- `yandex_direct_api_client/config.py` — удалён DEFAULT_CHUNK_SIZE
- `yandex_direct_api_client/_version.py` — 0.2.1
- `pyproject.toml` — версия 0.2.1
- `README.md` — новый API, раздел про confirm
- `CHANGELOG.md` — записи 0.2.0 и 0.2.1
- `scripts/check_api.py` — адаптирован к новому API
- `tests/conftest.py` — убран chunk_size
- `tests/test_client.py` — переписан + тесты confirm и пагинации
- `tests/test_models.py` — адаптирован, тесты AdGroup и нового merged_with
- `tests/test_readonly.py` — адаптирован, расширен

**Удалены:**
- `yandex_direct_api_client/models.py` (заменён пакетом `models/`)

## 7. Ключевые архитектурные решения

**Namespace-API вместо flat-методов.** `client.campaigns.list()` масштабируется
без загрязнения класса клиента: новый ресурс = новый файл в `services/`,
одно свойство в facade. Flat-вариант (`get_campaigns`, `get_ads`,
`get_ads_text_batch`...) при 10+ ресурсах превратился бы в нечитаемый список.

**Transport как единственный слой HTTP.** Сервисы не знают про Session,
retry или заголовки. Это позволило вынести общий код проверки ошибок
(`post_result`) и переиспользовать его во всех сервисах без дублирования
(раньше разбор `UpdateResults`/`AddResults`/`DeleteResults` копипастился).

**Dataclass'ы сохранены.** Pydantic не引入ён: текущий подход (dataclass +
`from_dict` + поле `raw` для доступа к нестандартным полям) не требует
зависимостей, полностью типизирован под mypy --strict и покрывает задачу.
`raw` сохранён как escape-hatch для полей, не попавших в модель.

**Пагинация через `LimitedBy`.** Реализована строго по официальной
документации: `Page.Limit/Offset` в запросе, `LimitedBy` в ответе —
следующий запрос с `Offset=LimitedBy`. Пользователь получает полный список,
не думая о страницах.

**confirm как явный keyword-аргумент.** Проверка выполняется ДО отправки
любого HTTP-запроса (в `ensure_confirmed`), поэтому при `confirm=False`
сеть вообще не трогается. Это предсказуемо и тестируемо.

## 8. Breaking changes

Все зафиксированы в CHANGELOG.md (0.2.0):

| Было (0.1.0) | Стало (0.2.x) |
|---|---|
| `client.get_campaigns()` | `client.campaigns.list()` |
| `client.get_ads(ad_ids=..., campaign_ids=...)` | `client.ads.get(ids=...)` / `client.ads.list(campaign_ids=...)` |
| `client.get_ads_text_batch(ids)` | `client.ads.get(ids, include_text=True)` |
| `client.get_stats(...)` | `client.reports.get_ad_stats(...)` |
| `client.update_ad(id, h, b)` | `client.ads.update_text(id, h, b)` |
| `client.add_campaign(payload)` | `client.campaigns.create(payload)` |
| `client.delete_ad(ids)` | `client.ads.delete(ids, confirm=True)` |
| `YandexDirectClient(chunk_size=...)` | параметр удалён |
| модель `AdTextEntry` | удалена (заменена `Ad` + `AdText`) |
| `StatRow.merged_with` | bounce_rate теперь средневзвешенное |
| `parse_stats_tsv` в `client.py` | перемещён в `services/reports.py` |

Версия поднята 0.1.0 → 0.2.1 (minor-бампы: 0.2.0 — реструктуризация,
0.2.1 — confirm-механизм; библиотека в beta, MAJOR-бамп не применялся).

## 9. Состояние безопасности операций

Три уровня защиты:

1. **`readonly=True`** — блокирует ВСЕ mutating-методы на уровне клиента
   (проверяется в каждом сервисе через `_ensure_writable`).
2. **`confirm=True`** — требуется для необратимых и массовых операций:
   - `ads.delete(ids, confirm=True)` — удаление объявлений
   - `campaigns.delete(ids, confirm=True)` — удаление кампаний
   - `ads.update(ads, confirm=True)` — массовое изменение (batch)
   Без флага бросается `ValidationError` ДО отправки запроса.
3. **Одиночные операции** (`update_text`, `campaigns.update`, `create`)
   не требуют confirm — они точечны и обратимы/безопасны по своей природе.

`update_text` внутри себя вызывает `self.update(..., confirm=True)` —
это внутренний вызов, подтверждение пользователем уже получено на уровне
`update_text`.

## 10. Результаты проверок

| Проверка | Результат |
|---|---|
| `pytest tests/` | **58 passed** (было 40) |
| `ruff check .` | All checks passed |
| `mypy yandex_direct_api_client` | Success: no issues in 22 files (strict) |
| `pip install -e ".[dev]"` | OK (пакет собирается, py.typed на месте) |

Реальных HTTP-запросов в тестах нет — все через `responses` (mock).

## 11. Нерешённые проблемы

- `ads.list()` без фильтров возвращает ВСЕ объявления клиента — для очень
  больших аккаунтов это может быть долго; осознанно оставлено (пагинация
  внутри работает корректно), но стоит добавить ленивый итератор.
- `AdGroupService` и `ReportService` не имеют readonly/confirm-механизмов,
  т.к. реализуют только читающие операции. При добавлении мутаций их нужно
  будет оснастить теми же guard'ами.
- `fetch_all_pages` ищет первый список в `result` по эвристике — при
  появлении сервисов с несколькими списками в ответе потребуется явный
  ключ (сейчас для campaigns/ads/adgroups работает корректно).

## 12. Что сознательно НЕ реализовано

- Остальные ресурсы API (keywords, bids, audiences, changes, sitelinks,
  vcards, ...) — по заданию этапа.
- Расширенная статистика (CAMPAIGN_PERFORMANCE_REPORT, SEARCH_QUERY_REPORT,
  построчная разбивка по дням) — только существовавший AD_PERFORMANCE_REPORT.
- Async-интерфейс — по требованиям основной интерфейс синхронный.
- Pydantic/attrs — не нужны, dataclass'ы справляются.
- DI-фреймворки, event bus, CQRS, repository-паттерн — не решают задач.
- MCP, AI, оптимизатор, генерация текстов — вне скоупа проекта.
- Typed-модели для тел запросов мутаций (create/update принимают dict) —
  схемы Yandex Direct для add/update кампаний огромны и часто меняются;
  premature typing дал бы хрупкий API. Отложено до следующего этапа.

## 13. Следующий этап (рекомендации)

1. Расширить покрытие ресурсов по приоритету полезности: `keywords`
   (list/get/update/suspend), `bids` (get/set), `changes` (checkDictionaries /
  checkCampaigns — для инкрементальной синхронизации).
2. Добавить ленивую пагинацию (итератор/генератор) для больших выборок.
3. Typed-модели для мутаций, начиная с самых стабильных (TextAd add/update).
4. Рассмотреть `suspend`/`resume` для кампаний и объявлений (частая
   операция оптимизатора).
5. Интеграционные smoke-тесты против sandbox-аккаунта (опционально, за
   флагом, не в CI по умолчанию).
