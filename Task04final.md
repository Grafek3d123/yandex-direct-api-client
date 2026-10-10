# Task04 Final Instructions — What Remains & How to Run Live

## Status Summary (from `tasks/task04_report.md`)

- **Stages 0–9 implemented** — all code complete, 660 tests green, `ruff`/`mypy --strict` clean.
- **Live smoke partially run (09.10.2026)** — auth & client limits (`S-01` part 1) confirmed on real creds.
- **BLOCKED**: geo scenarios `S-01` (dictionaries) & `S-02` (RegionSelector) fail because the `dictionaries` service was built against an **outdated v5 contract**; live API now requires **v501** with different request/response format (§8.2 of report).
- **Result**: `S-03…S-05` (RSYA, EPK, reports) never executed — they depend on geo resolution.

---

## 1. What Must Be Finished (Critical Path)

### 1.1 Migrate Layer 1 (`dictionaries` + `RegionSelector`) to v501 Contract

**Files to change:**
- `yandex_direct_api_client/services/dictionaries.py` — rewrite request/response handling
- `yandex_direct_api_client/services/_base.py` — add `Accept-Language` header support (for Russian region names)
- `yandex_direct_api_client/models/dictionary.py` — update `GeoRegion` model fields
- `yandex_direct_api_client/models/region_selector.py` — adapt resolver to new fields (`GeoRegionType`, `ParentId`, no `CountryRegion`)
- Tests in `tests/test_task04_stage1.py` — align mocks to real v501 responses

**Contract differences (live vs. mock):**

| Aspect | Old Mock (v5) | Live API (v501) |
|--------|---------------|-----------------|
| Request param | `{"getGeoRegions": {"CountryRegion": "RUC"}}` | `{"DictionaryNames": ["GeoRegions"]}` |
| Country filter | Supported | **Not supported** — returns full world tree (17k regions) |
| Region fields | `GeoRegionId`, `ParentGeoRegionId`, `CountryRegion`, `IsArea` | `GeoRegionId`, `GeoRegionName`, `GeoRegionType`, `ParentId` |
| Language | Russian by default | English default; `Accept-Language: ru` → Russian |
| Other dicts | `AdTypes`, `Sites`, `RetargetingLists`, `BingTypes`, `Keywords` as sub-objects | **Absent** from `dictionaries/get` |

**Impact on `RegionSelector`:**
- `geo_regions("RUC")` → must fetch all + filter client-side by `GeoRegionType`/`ParentId` (no server-side country filter)
- Resolver must work with `GeoRegionType` (e.g., "region", "city") and `ParentId` hierarchy
- Russian names require `Accept-Language: ru` on the dictionaries call

**Breaking change** → requires **MAJOR version bump** + `CHANGELOG.md` entry + explicit owner approval (AGENTS.md §6).

### 1.2 Complete Live Smoke Run

After migration passes all mock tests:

```bash
# From repo root
cd /Users/evgenii_reponin/Git/yandex-direct-api-client

# Run full scenario suite (S-01 through S-05)
python scripts/smoke_campaign_live.py --scenario all
```

**Expected sequence:**
1. `S-01` — auth, client limits, **dictionaries (geo_regions)**
2. `S-02` — geo: 5 regions outside MSK/SPb/LO/MO + "all Russia except four"
3. `S-03` — classic RSYA: campaign → group → ad → read → delete
4. `S-04` — EPK: `adimages/add` → UnifiedCampaign → UnifiedAdGroup → ResponsiveAd → read → delete
5. `S-05` — campaign report: impressions, clicks, CTR, CPM

**Constraints (D9, enforced in script):**
- All entities created with names like `SDK Smoke Test YYYYMMDDHHMMSS`
- Everything stays in `DRAFT`; `Network = SERVING_OFF` or `suspend` in `finally`
- `rollback(..., confirm=True)` runs even on failure
- Non-zero exit code on any failure
- **OAuth token never printed** — only `RequestId`, entity IDs, error stage

### 1.3 Commit & Release (Owner-Only)

```bash
# After live smoke passes
git add -A
git commit -m "feat: release 1.0.0 — full RSYA/EPK support, v5/v501, dictionaries migration"
git tag v1.0.0
git push origin main --tags
```

> **Do NOT commit/push without explicit owner instruction** (AGENTS.md §1).

---

## 2. How to Run on Real Account (Credentials in `.env`)

### 2.1 Prerequisites

- `.env` file exists at repo root with:
  ```
  YANDEX_DIRECT_TOKEN=...          # OAuth access token (required)
  YANDEX_DIRECT_CLIENT_LOGIN=...   # Optional: for agency access to client account
  YANDEX_DIRECT_API_URL=https://api.direct.yandex.com/json/v5  # or /v501 base
  YANDEX_DIRECT_LOG_BODIES=0       # Set 1 to debug payloads (never in production)
  ```
- Token must have `yandex_direct` scope and access to a **test client** (not production business account).

### 2.2 Environment Loading

The SDK loads `.env` automatically via `Settings.from_env()` in `config.py`.  
**Never open `.env` in the editor** — credentials stay in the file.

### 2.3 Running Live Scripts

```bash
# Activate venv if needed
source .venv/bin/activate

# Quick connectivity / auth check (S-01 part 1)
python scripts/smoke_campaign_live.py --scenario S-01

# Full geo verification (S-02) — requires Layer 1 migration first
python scripts/smoke_campaign_live.py --scenario S-02

# Classic RSYA flow (S-03) — requires pre-existing CreativeId from web UI
python scripts/smoke_campaign_live.py --scenario S-03

# EPK full auto flow (S-04) — uploads images via adimages, no manual steps
python scripts/smoke_campaign_live.py --scenario S-04

# Reports (S-05) — reads existing campaigns
python scripts/smoke_campaign_live.py --scenario S-05

# All at once
python scripts/smoke_campaign_live.py --scenario all
```

### 2.4 E2E Launch Scripts (Dry-Run First)

```bash
# Classic RSYA — needs CreativeId (from web UI)
python scripts/launch_rsy.py --creative-id 123456789 --dry-run

# EPK — fully automated: adimages → campaign → group → ResponsiveAd
python scripts/launch_epk.py --dry-run

# Live run (requires confirm=True because names lack E2E/TEST markers)
python scripts/launch_epk.py --confirm
```

---

## 3. Validation Gates Before Live Run

```bash
# Must pass before any live execution
ruff check .
mypy yandex_direct_api_client
pytest -q
# All three must be clean (660 passed)
```

---

## 4. Files to Watch / Modify for Layer 1 Migration

| File | Purpose |
|------|---------|
| `services/dictionaries.py` | Core rewrite — request format, response parsing, v501 routing |
| `services/_base.py` | Add `Accept-Language` header propagation for dictionaries calls |
| `models/dictionary.py` | `GeoRegion` fields: `GeoRegionType`, `ParentId` (drop `CountryRegion`, `ParentGeoRegionId`, `IsArea`) |
| `models/region_selector.py` | Resolver logic for new hierarchy; client-side country filtering |
| `tests/test_task04_stage1.py` | Update mocks to match real v501 responses (capture from live run) |
| `config.py` | Possibly add `YANDEX_DIRECT_DICT_LANG` env for language control |

---

## 5. Decision Required from Owner

1. **Approve Layer 1 migration** as breaking change (MAJOR) with `CHANGELOG.md` entry.
2. **Confirm test client** for live run (token in `.env` must target a disposable test account).
3. **Authorize commit/tag** after full live smoke passes.

---

## 6. What Is NOT in Scope for This Task

- Auto-bid optimization strategies beyond typed set
- Orchestrator-level integrations
- Metrika API client (goals/counters managed externally)
- Production campaign creation for the business (only technical smoke on test entities)

---

## 7. Quick Reference: Key Commands

```bash
# Validate code
ruff check . && mypy yandex_direct_api_client && pytest -q

# Live smoke (after Layer 1 migration)
python scripts/smoke_campaign_live.py --scenario all

# E2E launch dry-run
python scripts/launch_epk.py --dry-run
python scripts/launch_rsy.py --creative-id <ID> --dry-run

# Version bump & release (owner only)
# edit pyproject.toml version + yandex_direct_api_client/_version.py
git commit -am "chore: version 1.0.0"
git tag v1.0.0
git push origin main --tags
```