# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install (editable, with dev dependencies)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_search.py -v

# Run a single test
pytest tests/test_search.py::TestSimilarity::test_exact_match -v

# Run with coverage
pytest --cov=discogs_sync
```

Build backend is `setuptools.build_meta` (not `setuptools.backends._legacy:_Backend`).

## Running Without pip install

`discogs-sync.py` at the project root is a thin entry point that bootstraps `sys.path` and calls `cli.main()`. No pip install required:

```bash
python discogs-sync.py wantlist list --output-format json
```

This is the invocation style used by the OpenClaw skill (`SKILL.md`).

## Architecture

```
CLI (cli.py) → Click command groups
  ├── auth.py / config.py / client_factory.py  → OAuth + personal token + credential storage
  ├── sync_wantlist.py / sync_collection.py    → add/remove/list/sync
  ├── marketplace.py                           → pricing via master versions
  ├── search.py                                → multi-pass release matching
  ├── parsers.py                               → CSV/JSON input parsing
  ├── rate_limiter.py                          → proactive throttling
  └── output.py                                → Rich tables + JSON dual-mode
```

### API Call Flow

Every Discogs API call goes through `search._api_call_with_retry(lambda, limiter)`:
1. `limiter.wait_if_needed()` — sleeps based on `X-Discogs-Ratelimit-Remaining` header tracking
2. Execute the lambda (actual API call)
3. `limiter.update_from_headers()` — update remaining count from response
4. On failure: retry up to 3 times with 5s delay

The rate limiter is a global singleton (`rate_limiter.get_rate_limiter()`). Normal interval is 1.1s; slows to 2s when remaining ≤ 5; pauses 10s when remaining ≤ 2.

### Search Resolution

`search_release()` runs three passes, returning early when a match exceeds threshold:
1. **Structured**: artist + album + format + year → type=master
2. **Relaxed**: artist + album only → type=master
3. **Freetext**: `"artist album"` → type=release

Scoring: 40% artist similarity + 40% title similarity + 10% year + 10% format (uses `difflib.SequenceMatcher`).

After search, `resolve_to_release_id()` converts master_id → release_id:
- master_id + format specified → find matching version from `master.versions`
- master_id + no format → use `master.main_release`
- release_id only → use directly

### Sync Pattern (Wantlist & Collection)

Both follow the same three-step pattern:
1. Resolve each `InputRecord` → `release_id` via search
2. Fetch current items from Discogs API (paginated)
3. Diff target vs current → add missing, skip existing, optionally remove extras

Duplicate detection uses a three-tier check:
1. **release_id match** — exact release_id already in collection/wantlist
2. **master_id match** — same master_id (different pressing of same album)
3. **Fuzzy match** — artist similarity ≥ 0.85 AND title similarity ≥ 0.85 (catches cases where API response lacks master_id but the album is clearly the same)

The fuzzy match uses `_similarity()` from `search.py` (`difflib.SequenceMatcher`, case-insensitive). Threshold constant: `FUZZY_MATCH_THRESHOLD = 0.85` in both sync modules.

Each item produces a `SyncAction` (ADD/REMOVE/SKIP/ERROR). Individual failures don't abort the batch. `SyncReport` aggregates actions and computes exit code (0=success, 1=partial, 2=complete failure).

Collection differs from wantlist: uses folder_id (default 1 for adds, 0 for reads), removing requires instance_id, and `--allow-duplicate` bypasses the duplicate check.

### Output Modes

All commands support `--output-format table|json`. The `output.py` module provides per-entity formatters (`output_wantlist`, `output_collection`, `output_marketplace`, `output_sync_report`). JSON mode writes to stdout; Rich tables and status messages write to stderr via `error_console`.

## Key Conventions

- Python 3.10+ required (uses `match`/`case`, `X | None` union syntax)
- All tests mock the Discogs client — no live API calls in tests
- `conftest.py` provides `sample_csv`, `sample_json`, `tmp_csv`, `tmp_json` fixtures
- Format synonyms normalized in `parsers.normalize_format()`: LP/record/12" → Vinyl, compact disc → CD, tape/mc → Cassette
- Config stored at `~/.discogs-sync/config.json`
- User agent: `DiscogsSyncTool/0.1`
