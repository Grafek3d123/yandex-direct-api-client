# yandex-direct-api-client

Typed, retry-aware Python client for [Yandex.Direct API v5](https://yandex.ru/dev/direct/doc/).

- **Sync** — built on `requests`, no asyncio required
- **Typed** — dataclasses + `py.typed`, IDE autocomplete out of the box
- **Resilient** — automatic retry on `429` (with `Retry-After`) and `202` (report polling)
- **Safe** — `readonly=True` blocks every mutating method
- **Rate-limited** — token-bucket throttling so you rarely hit `429`
- **Paginated** — auto-follows `LimitedBy` to fetch all pages
- **Namespaced** — `client.campaigns.list()`, `client.ads.update()`, `client.reports.get_ad_stats()`

## Architecture & Scope

This repository is a **pure capability layer** — a typed API client, nothing more:

```text
Private Orchestrator          ← business logic, strategy, user approval (NOT this repo)
        ↓
Yandex Direct Client          ← this repository
        ↓
Yandex Direct API v5
```

The client owns everything Direct-specific:

- authentication (OAuth helpers) and HTTP transport (headers, request IDs, timeouts)
- retry with `Retry-After`, token-bucket rate limiting, report polling (`201/202`)
- pagination (`LimitedBy`), batch limits and chunking
- typed request/response models (callers never touch raw Yandex JSON)
- typed errors (`AuthError`, `RateLimitError`, `ApiError`, ...)
- capability-level safety: `readonly=True` and `confirm=True` guards

Explicitly **out of scope** (belongs to the orchestrator above):

- advertising strategy, campaign optimization, budget decisions
- user-facing approval workflows (the client's `confirm` is a programmatic
  safety gate, not a business approval)
- AI / LLM integration, MCP, natural language
- Metrika client or any cross-capability code (report `goals` are plain
  Direct API fields — correlating them with Metrika data is the orchestrator's job)
- website changes, cross-system workflows

## Install

```bash
pip install yandex-direct-api-client
```

For local development:

```bash
git clone https://github.com/Grafek3d123/yandex-direct-api-client.git
cd yandex-direct-api-client
pip install -e ".[dev]"
```

## Quickstart

```python
from yandex_direct_api_client import YandexDirectClient

client = YandexDirectClient(
    token="00000000000000000000000000000000",
    client_login="DEG13",
)

campaigns = client.campaigns.list()
for c in campaigns:
    print(c.id, c.name, c.status)
```

### Environment-variable fallback

```python
# Reads YANDEX_DIRECT_TOKEN / YANDEX_DIRECT_CLIENT_LOGIN from env
client = YandexDirectClient()
```

### Context manager (session reuse, keep-alive)

```python
with YandexDirectClient() as client:
    ads = client.ads.list(campaign_ids=[123456789])
    stats = client.reports.get_ad_stats(ad_ids=[a.id for a in ads])
```

### Readonly mode

```python
client = YandexDirectClient(readonly=True)
client.ads.update_text(ad_id=1, headline="...", body="...")  # raises ValidationError
```

### Destructive operations require `confirm=True`

Irreversible operations (delete) and bulk mutations (batch update) require
an explicit `confirm=True` flag. This prevents accidental data loss:

```python
# Raises ValidationError — no request is sent
client.ads.delete([1, 2, 3])

# Explicit confirmation — request is sent
client.ads.delete([1, 2, 3], confirm=True)

# Bulk update also requires confirmation
client.ads.update([...], confirm=True)

# Single-ad update_text does NOT require confirm
client.ads.update_text(1, "New title", "New text")
```

### Pagination

All `list()` methods auto-follow `LimitedBy` to return all results:

```python
# Fetches all ads in the campaign, even if > 10 000
all_ads = client.ads.list(campaign_ids=[123])
```

### OAuth: obtain a fresh token

```python
from yandex_direct_api_client.auth import get_new_token

token = get_new_token(client_id="your_app_id", client_secret="your_secret")
print(token.access_token, token.refresh_token, token.expires_in)
```

### OAuth: refresh an existing token

```python
from yandex_direct_api_client.auth import refresh_token

new = refresh_token(
    client_id="your_app_id",
    client_secret="your_app_secret",
    refresh_token="...",
)
```

## API Reference

### `client.campaigns`

| Method | Description | Mutates? |
|---|---|---|
| `list(states=None, statuses=None)` | List campaigns (auto-paginated) | no |
| `get(ids)` | Get campaigns by IDs | no |
| `create(campaign)` | Create a campaign | **yes** |
| `update(campaign)` | Update a campaign | **yes** |
| `delete(ids, confirm=False)` | Delete campaigns by IDs | **yes** |

### `client.ads`

| Method | Description | Mutates? |
|---|---|---|
| `list(campaign_ids=None, ...)` | List ads (auto-paginated) | no |
| `get(ids, include_text=False)` | Get ads by IDs | no |
| `create(ads)` | Create ads (batch, up to 200) | **yes** |
| `update(ads, confirm=False)` | Update ads (batch, up to 200) | **yes** |
| `update_text(ad_id, headline, body)` | Update Title/Text of a text ad | **yes** |
| `create_with_payload(campaign_id, text, image=None, ad_group_id=None)` | Create a text ad from typed models | **yes** |
| `delete(ids, confirm=False)` | Delete ads by IDs | **yes** |

### `client.ad_groups`

| Method | Description | Mutates? |
|---|---|---|
| `list(campaign_ids=None, ...)` | List ad groups (auto-paginated) | no |
| `get(ids)` | Get ad groups by IDs | no |

### `client.ad_group_items` (keywords)

| Method | Description | Mutates? |
|---|---|---|
| `list(campaign_ids=None, ad_group_ids=None)` | List keywords (auto-paginated) | no |
| `get(ids)` | Get keywords by IDs | no |
| `add(items)` | Add keywords (typed `AdGroupItem` or raw dicts, up to 200) | **yes** |
| `set_bid(item_id, bid)` | Set a single keyword bid | **yes** |
| `set_bids(bids, confirm=False)` | Set keyword bids in bulk (up to 200) | **yes** |
| `delete(ids, confirm=False)` | Delete keywords by IDs | **yes** |

### `client.retargeting_adjustments`

| Method | Description | Mutates? |
|---|---|---|
| `list(campaign_ids=None)` | List retargeting bid adjustments | no |
| `get(ids)` | Get adjustments by IDs | no |
| `add(adjustments)` | Add adjustments (typed model or dicts) | **yes** |
| `update(adjustments, confirm=False)` | Bulk update adjustments | **yes** |
| `delete(ids, confirm=False)` | Delete adjustments by IDs | **yes** |

### `client.reports`

| Method | Description | Mutates? |
|---|---|---|
| `get(report_type, field_names, date_from/date_to or date_range_type, ...)` | Universal report: filters, order, goals, attribution, VAT, chunking | no |
| `account_stats(...)` | ACCOUNT_PERFORMANCE_REPORT | no |
| `campaign_stats(campaign_ids=None, ...)` | CAMPAIGN_PERFORMANCE_REPORT | no |
| `ad_group_stats(...)` | ADGROUP_PERFORMANCE_REPORT | no |
| `criteria_stats(...)` | CRITERIA_PERFORMANCE_REPORT (keywords) | no |
| `search_queries(...)` | SEARCH_QUERY_PERFORMANCE_REPORT | no |
| `get_ad_stats(ad_ids=None, ...)` | AD_PERFORMANCE_REPORT → `List[StatRow]` (legacy) | no |

Reports are async on the API side: the client polls `202/PROGRESS` with
`Retry-In` until ready (configurable `report_timeout`), retries `429` with
backoff, and converts errors to typed exceptions. Large requests are split
automatically: ID filters chunked by 1000 values, long date ranges split
into windows (`max_days`).

```python
from datetime import date
from yandex_direct_api_client.models import ReportFilter, ReportOrder

result = client.reports.campaign_stats(
    campaign_ids=[1, 2],
    date_from=date(2026, 9, 1),
    date_to=date(2026, 9, 15),
    goals=["12345"],                       # conversions by Metrika goal
    filters=[ReportFilter("Clicks", "GREATER_THAN", ["10"])],
    order_by=[ReportOrder("Clicks", ascending=False)],
)
for row in result.rows:
    print(row.get("CampaignName"), row.as_int("Clicks"), row.as_money("Cost"))

result.to_csv()      # CSV string
result.to_json()     # JSON string
result.to_dicts()    # list[dict]
result.to_dataframe()  # pandas (optional dependency)
```

## Exceptions

All inherit from `YandexDirectError` and carry the Yandex `request_id`
(`X-Request-Id`) when available — quote it in support tickets.

| Exception | Raised when |
|---|---|
| `AuthError` | HTTP 401/403 — token invalid, expired, or no access |
| `RateLimitError` | HTTP 429 after all retries are exhausted |
| `ReportNotReadyError` | Report stays in PROGRESS longer than `report_timeout` |
| `ApiError` | Any other non-2xx response, or `status=ERROR` in body |
| `ValidationError` | Client-side validation (readonly mode, bad args) |

## Configuration

| Parameter | Env var | Default | Notes |
|---|---|---|---|
| `token` | `YANDEX_DIRECT_TOKEN` | — | OAuth access token |
| `client_login` | `YANDEX_DIRECT_CLIENT_LOGIN` | — | Customer login |
| `api_url` | `YANDEX_DIRECT_API_URL` | `https://api.direct.yandex.com/json/v5` | |
| `timeout` | `YANDEX_DIRECT_TIMEOUT` | `30` | Per-HTTP-request seconds |
| `max_retries` | `YANDEX_DIRECT_MAX_RETRIES` | `5` | For 429 and 202 |
| `rate_limit_rps` | `YANDEX_DIRECT_RATE_LIMIT_RPS` | `5` | Token-bucket rate |
| `readonly` | `YANDEX_DIRECT_READONLY` | `False` | Block mutating methods |

## Tests

```bash
pip install -e ".[dev]"

pytest                            # unit tests: mocked HTTP, no live API needed
ruff check .
mypy yandex_direct_api_client
```

Manual live checks (require a real token in `.env`, hit the real API):

```bash
python scripts/check_api.py               # readonly smoke over real campaigns
python scripts/smoke_create_campaign.py   # full lifecycle: create → update → pause → delete
```

## License

MIT © [Grafek3d123](https://github.com/Grafek3d123) — see [LICENSE](LICENSE).
