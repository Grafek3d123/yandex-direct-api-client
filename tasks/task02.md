# ЗАДАЧА: СТАБИЛИЗИРОВАТЬ `yandex-direct-api-client` КАК REUSABLE CAPABILITY

Репозиторий:

https://github.com/Grafek3d123/yandex-direct-api-client

## Цель

Сохранить этот репозиторий как чистую переиспользуемую Python-библиотеку для Yandex Direct API v5.

НЕ превращать его в AI agent.

НЕ добавлять MCP.

НЕ добавлять business orchestration.

НЕ добавлять marketing strategy.

НЕ добавлять Koda-specific logic.

Целевая архитектура:

```text
Koda
  ↓
Private Orchestrator
  ↓
Yandex Direct Client
  ↓
Yandex Direct API
```

---

# 1. Главный принцип

НЕ делать переписывание проекта ради архитектурной чистоты.

Сначала проведи аудит того, что уже есть.

Сохрани существующие полезные механизмы, если они корректны:

* typed models;
* service-oriented API;
* pagination;
* retry;
* rate limiting;
* readonly mode;
* destructive-operation guards;
* reports;
* typed errors;
* OAuth helpers.

---

# 2. Ответственность Direct Client

Репозиторий отвечает за:

* authentication;
* HTTP transport;
* API requests;
* request models;
* response models;
* API validation;
* pagination;
* retries;
* rate limiting;
* API errors;
* campaigns;
* ads;
* ad groups;
* ad group items;
* keywords, если они входят в текущий API;
* retargeting adjustments;
* reports;
* Direct-specific operations.

Репозиторий НЕ отвечает за:

* рекламную стратегию;
* campaign optimization;
* решение, какой бюджет нужен;
* решение, какую campaign менять;
* решение, какое объявление создавать;
* интерпретацию Metrika;
* website changes;
* cross-system workflows;
* natural language;
* AI;
* Koda.

---

# 3. Сохранить текущую service-oriented модель

Если сейчас используется модель:

```python
client.campaigns
client.ads
client.ad_groups
client.ad_group_items
client.retargeting_adjustments
client.reports
```

сохрани её.

Не заменяй её без необходимости на универсальный:

```python
client.call("some_method", payload)
```

---

# 4. Сохранить typed models

Модели должны скрывать от orchestrator raw Yandex JSON.

Цель:

```text
Python model
    ↕
Yandex Direct payload
```

Орchestrator должен работать с Python-объектами и понятными методами client.

---

# 5. Сохранить transport abstraction

Не выносить HTTP в orchestrator.

Transport должен владеть:

* HTTP;
* request headers;
* request ID;
* retry;
* `Retry-After`;
* polling reports;
* rate limit;
* timeout;
* parsing;
* transport errors.

Orchestrator должен вызывать client methods.

---

# 6. Сохранить readonly

Сохрани:

```python
YandexDirectClient(readonly=True)
```

как отдельный защитный механизм.

Readonly полезен для:

* аналитики;
* reporting;
* dry-run;
* тестов;
* безопасного чтения данных.

Это capability-level safety и его не нужно переносить в orchestrator.

---

# 7. Сохранить destructive guards

Сохрани защиту опасных операций:

* delete;
* bulk update;
* массовые изменения;
* другие destructive actions.

Но НЕ создавай здесь пользовательский approval workflow.

Разница:

```text
Direct Client:
"эта операция опасная и требует явного программного допуска"
```

и:

```text
Orchestrator:
"пользователь должен подтвердить бизнес-изменение"
```

Это разные уровни.

---

# 8. Ошибки

Сохрани typed exceptions.

Должны быть понятные категории:

* authentication;
* rate limit;
* report not ready;
* API error;
* validation;
* transport error;
* timeout, если применимо.

Не заменяй их AI-oriented dictionaries.

Orchestrator позже сможет преобразовывать эти ошибки в собственный application result.

---

# 9. Direct-specific mechanics

Все Direct-specific детали должны оставаться внутри этого репозитория.

Например:

* pagination;
* `LimitedBy`;
* report polling;
* HTTP details;
* request IDs;
* batch limits;
* Direct validation;
* Direct-specific error formats;
* Direct request schemas.

Будущий orchestrator НЕ должен знать эти детали.

---

# 10. Reports

Сохрани typed reports.

Отчёты являются capability-level операцией:

```text
campaign stats
ad stats
ad group stats
criteria stats
search queries
account stats
```

если они уже существуют.

Но НЕ добавляй:

```python
analyze_campaign_performance(...)
recommend_budget(...)
optimize_ads(...)
choose_best_campaign(...)
```

Это business logic orchestrator.

---

# 11. OAuth

Сохрани OAuth helpers, если они действительно являются частью reusable Direct client.

Граница:

```text
Direct client:
"как выполнить запрос, имея credentials"
```

и:

```text
Orchestrator:
"какой аккаунт использовать"
```

Client не должен принимать бизнес-решения по выбору рекламного аккаунта.

---

# 12. Не добавлять зависимость от Metrika

НЕ импортируй Metrika client.

НЕ добавляй cross-capability code.

Даже если Direct report содержит данные, связанные с Metrika goals, это всё ещё Direct API data.

Связать:

```text
Metrika data
+
Direct data
```

должен orchestrator.

---

# 13. Не добавлять cross-system workflows

Не создавать:

```python
optimize_using_metrika(...)
apply_recommended_changes(...)
sync_site_with_campaign(...)
```

Правильная схема:

```text
Metrika
   ↓
Orchestrator
   ↓
Direct
```

---

# 14. Провести аудит public API

Каждый public method классифицировать:

```text
KEEP
REFACTOR
REMOVE
UNCERTAIN
```

Метод принадлежит Direct client, если он выполняет concrete Direct API operation.

Метод не принадлежит Direct client, если он принимает бизнес-решение.

---

# 15. Naming

Предпочтительно:

```python
campaigns.list()
campaigns.get()
campaigns.update()

ads.list()
ads.get()
ads.update()

ad_group_items.set_bid()

reports.campaign_stats()
```

Нежелательно:

```python
campaigns.optimize()
ads.improve_conversion()
campaigns.rebalance_budget()
ads.choose_winner()
```

Не создавать бизнес-ориентированные названия внутри API client.

---

# 16. Service boundaries

Проверь сервисы:

```text
Campaigns
Ads
AdGroups
AdGroupItems
RetargetingAdjustments
Reports
```

Каждый должен:

* отвечать за свой resource;
* использовать typed models;
* делегировать transport общему уровню;
* не содержать business workflows.

---

# 17. Тесты

Сохрани или улучши тесты для:

* request construction;
* response parsing;
* pagination;
* retry;
* rate limiting;
* readonly;
* destructive guards;
* reports;
* typed models;
* errors;
* OAuth helpers.

НЕ добавляй:

* AI tests;
* LLM tests;
* natural-language tests;
* MCP tests.

---

# 18. README

README должен описывать репозиторий как:

```text
Typed Python client for Yandex Direct API v5
```

Документировать:

* installation;
* authentication;
* client initialization;
* services;
* reports;
* readonly;
* destructive guards;
* errors;
* configuration;
* tests.

Добавить короткую архитектурную схему:

```text
Private Orchestrator
        ↓
Yandex Direct Client
        ↓
Yandex Direct API
```

Явно написать, что business orchestration находится за пределами этого репозитория.

---

# 19. Не добавлять новую архитектуру

НЕ добавлять:

* AI layer;
* tool registry;
* MCP;
* HTTP server;
* microservice;
* message broker;
* event bus;
* orchestration framework.

---

# 20. Acceptance criteria

После изменений:

1. Client можно импортировать как обычную Python library.
2. Orchestrator не знает HTTP деталей Direct.
3. Orchestrator не знает Direct pagination.
4. Orchestrator не реализует Direct retry logic.
5. Readonly mode работает надёжно.
6. Dangerous operations защищены.
7. Business strategy отсутствует.
8. AI layer отсутствует.
9. MCP отсутствует.
10. Нет зависимости от Metrika.
11. Нет зависимости от Site capability.
12. Client можно тестировать независимо.

---

# 21. Финальный отчёт

Верни:

### Оставлено

Что уже было правильно.

### Изменено

Какие improvements внесены.

### Удалено

Что не относится к Direct capability.

### Public API changes

Какие breaking changes сделаны.

### Осталось

Что сознательно оставить для будущего orchestrator.

### Финальная архитектура

```text
Orchestrator
      ↓
Direct Client
      ↓
Yandex Direct API
```
