# Отчёт: боевой тест создания тестовой рекламной кампании

Дата: 2026-09-23
Клиент: DEG13
Скрипт: `scripts/smoke_create_campaign.py`

## Цель

Провести боевой (smoke) тест на живом аккаунте Yandex.Direct: создать тестовую
рекламную кампанию, проверить полный жизненный цикл (create → get → update →
delete) и убедиться, что безопасность (защита от случайного удаления) работает.

## Как запускался тест

Реальные запросы к живому аккаунту, вне обычного прогона `pytest`:

```bash
unset YANDEX_DIRECT_TOKEN && unset YANDEX_DIRECT_REFRESH_TOKEN
export SSL_CERT_FILE=$(.venv/bin/python -c "import certifi; print(certifi.where())")
.venv/bin/python scripts/smoke_create_campaign.py
```

Перед запуском получен OAuth-токен через `python -m yandex_direct_api_client.auth new`
(в `.env` токены были пусты). Для обхода ошибки SSL
(`CERTIFICATE_VERIFY_FAILED`) установлен `certifi` и задан `SSL_CERT_FILE`.

## Результаты боевого теста

| Шаг | Действие | Результат |
|-----|----------|-----------|
| 1 | Чтение кампаний (readonly) | 23 кампании до теста |
| 2 | Создание кампании | id=714686338, имя `SMOKE TEST 2026-09-23 (auto)` |
| 3 | GET по ID | OK: state=OFF, status=DRAFT |
| 4 | UPDATE (переименование) | OK |
| 5 | DELETE без `confirm` | Корректно отклонён: `ValidationError` |
| 6 | DELETE с `confirm=True` | OK |
| 7 | Контроль после удаления | Нет записей — OK |

На аккаунте ничего не осталось — тестовая кампания удалена. Вывод скрипта:

```
INFO Кампаний до теста: 23
INFO Создана кампания id=714686338 name='SMOKE TEST 2026-09-23 (auto)'
INFO GET OK: id=714686338 name='SMOKE TEST 2026-09-23 (auto)' state=OFF status=DRAFT
INFO UPDATE OK: id=714686338
INFO DELETE без confirm корректно отклонён: ValidationError
INFO DELETE OK: кампания 714686338 удалена
INFO Контроль после удаления: нет записей — OK
```

## Найденные проблемы и исправления

### 1. Баг в `delete` — неверный формат `params` (критично)

**Симптом:** `ApiError: API error: Invalid request | status=200`,
`error_detail: "Omitted required parameter SelectionCriteria"`.

**Причина:** delete-запросы отправляли `params` как `{"Ids": [...]}`
(или как голый массив), тогда как API v5 требует
`{"SelectionCriteria": {"Ids": [...]}}` (см. официальную документацию
`campaigns/delete`, `ads/delete`).

**Исправлено** — приведён к виду:

```json
{"method": "delete", "params": {"SelectionCriteria": {"Ids": [...]}}}
```

в сервисах:
- `yandex_direct_api_client/services/campaigns.py`
- `yandex_direct_api_client/services/ads.py`
- `yandex_direct_api_client/services/ad_group_items.py`
- `yandex_direct_api_client/services/retargeting_adjustments.py`

### 2. Smoke-скрипт: недопустимые значения стратегии ставок

**Симптом:** `ApiError: Invalid use of field`,
`error_detail: "...BiddingStrategyType contains an invalid enumeration value..."`
для `MANUAL_BIDDING` и `MAXIMUM_COVERAGE`.

**Причина:** в скрипте использовались значения стратегии, отсутствующие
в допустимом enum API.

**Исправлено** — в `scripts/smoke_create_campaign.py` стратегия заменена на
валидную: `Search=HIGHEST_POSITION`, `Network=SERVING_OFF`.

### 3. Smoke-скрипт: битый контроль после удаления

**Симптом:** шаг 7 обращался к `created_id` уже после обнуления
(`created_id = None`), поэтому проверка «кампании больше нет» всегда
возвращала пустой список и не была осмысленной.

**Исправлено** — в `scripts/smoke_create_campaign.py` GET по ID выполняется
до обнуления `created_id`.

## Проверки

- `pytest` — 105 passed (unit-тесты на mock HTTP не сломаны).
- Боевой smoke-тест — полный жизненный цикл прошёл успешно, на аккаунте чисто.

## Изменённые файлы

- `yandex_direct_api_client/services/campaigns.py` — фикс формата delete
- `yandex_direct_api_client/services/ads.py` — фикс формата delete
- `yandex_direct_api_client/services/ad_group_items.py` — фикс формата delete
- `yandex_direct_api_client/services/retargeting_adjustments.py` — фикс формата delete
- `scripts/smoke_create_campaign.py` — валидная стратегия + фикс контроля
