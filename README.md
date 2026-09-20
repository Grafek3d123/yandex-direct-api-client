# yandex-direct-api-client

Typed, retry-aware Python client for [Yandex.Direct API v5](https://yandex.ru/dev/direct/doc/).

- **Sync** — built on `requests`, no asyncio required
- **Typed** — dataclasses + `py.typed`, IDE autocomplete out of the box
- **Resilient** — automatic retry on `429` (with `Retry-After`) and `202` (report polling)
- **Safe** — `readonly=True` blocks every mutating method
- **Rate-limited** — token-bucket throttling so you rarely hit `429`
- **Batched** — large `ad_ids` lists are auto-chunked to API limits

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

campaigns = client.get_campaigns()
for c in campaigns:
    print(c.id, c.name, c.status)
```

### Environment-variable fallback

```python
# Reads YANDEX_DIRECT_TOKEN / YANDEX_DIRECT_CLIENT_LOGIN from env / .env
client = YandexDirectClient()
```

### Context manager (session reuse, keep-alive)

```python
with YandexDirectClient() as client:
    ads = client.get_ads(campaign_ids=[123456789])
    stats = client.get_stats(ad_ids=[a.id for a in ads], period_days=30)
```

### Readonly mode

```python
client = YandexDirectClient(readonly=True)
client.update_ad(ad_id=1, headline="...", body="...")  # raises YandexDirectError
```

### OAuth: obtain a fresh token

```python
from yandex_direct_api_client.auth import get_new_token

token = get_new_token(client_id="your_app_id", redirect_uri="http://localhost")
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

## Available methods

| Method | Description | Mutates? |
|---|---|---|
| `get_campaigns()` | List campaigns of the client | no |
| `get_ads(ad_ids=None, campaign_ids=None)` | List ads (auto-chunked) | no |
| `get_ads_text_batch(ad_ids)` | Headline + text for many ads in one request | no |
| `get_stats(ad_ids, period_days=30)` | Show/click/CTR/cost/bounce per ad (async report) | no |
| `update_ad(ad_id, headline, body)` | Replace Title + Text of a text ad | **yes** |
| `add_campaign(payload)` | Create a new campaign | **yes** |
| `delete_ad(ad_ids)` | Delete ads by id | **yes** |

## Exceptions

All inherit from `YandexDirectError` and carry the Yandex `request_id`
(`X-Request-Id`) when available — quote it in support tickets.

| Exception | Raised when |
|---|---|
| `AuthError` | HTTP 401/403 — token invalid, expired, or no access |
| `RateLimitError` | HTTP 429 after all retries are exhausted |
| `ReportNotReadyError` | Report stays in `PROGRESS` longer than `report_timeout` |
| `ApiError` | Any other non-2xx response, or `status=ERROR` in body |

## Configuration

| Parameter | Env var | Default | Notes |
|---|---|---|---|
| `token` | `YANDEX_DIRECT_TOKEN` | — | OAuth access token |
| `client_login` | `YANDEX_DIRECT_CLIENT_LOGIN` | — | Customer login |
| `api_url` | `YANDEX_DIRECT_API_URL` | `https://api.direct.yandex.com/v5` | |
| `timeout` | `YANDEX_DIRECT_TIMEOUT` | `30` | Per-HTTP-request seconds |
| `max_retries` | `YANDEX_DIRECT_MAX_RETRIES` | `5` | For 429 and 202 |
| `rate_limit_rps` | `YANDEX_DIRECT_RATE_LIMIT_RPS` | `5` | Token-bucket rate |
| `readonly` | `YANDEX_DIRECT_READONLY` | `False` | Block mutating methods |

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy yandex_direct_api_client
```

## License

MIT © [Grafek3d123](https://github.com/Grafek3d123) — see [LICENSE](LICENSE).
