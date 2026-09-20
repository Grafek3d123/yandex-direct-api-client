# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
