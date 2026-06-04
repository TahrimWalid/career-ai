# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## What This Project Is

A 5-phase ETL pipeline that scrapes Finnish IT job postings from Duunitori.fi, extracts structured insights using a local LLM, and generates market intelligence reports.

**Why it exists:** Built to analyze real Finnish IT job market demand — specifically to understand which skills, tools, and seniority levels are actually being hired for in Finland as of May 2026. The author is transitioning into cloud/networking roles (CCNA + AZ-104 track) and built this to make data-driven decisions about skill acquisition.

**What makes it non-trivial:**
- Duunitori posts many jobs in both Finnish and English simultaneously, creating ~50% duplicate content that silently inflates all metrics
- The deduplication strategy itself introduces bias (keeping Finnish vs English versions changes the "Finnish required" stat from 5% → 82.5%)
- Rate limiting is aggressive — naive scraping yields ~50% hydration; adaptive backoff gets to 98.2%
- LLM extraction is the bottleneck: ~6 hours for 986 jobs at ~45s/job on qwen2.5:3b

**Current dataset state:** 882 unique extracted jobs, 986 unique deduplicated postings, from a raw scrape of 2,002 URLs (May 2026 snapshot).

---

## Running the Pipeline

```bash
# Full pipeline (~6-8 hours: scrape 3.5h + extract 6h + analytics 0.2s)
python main.py --all

# Individual phases
python main.py --scrape      # Phase 1+2: index scraping + detail hydration
python main.py --extract     # Phase 3: LLM extraction via Ollama
python main.py --analytics   # Phase 4: analytics to stdout + report.html

# Analytics only (no scraping/extraction, uses existing DB)
python main.py --analytics
```

**Prerequisites:** Python 3.10+, Ollama running locally with `qwen2.5:3b` pulled (`ollama pull qwen2.5:3b`).

**Rate limit strategies** (set in scraper.py):
- `fast` → ~50% hydration success (too aggressive)
- `balanced` → ~70-80% success
- `conservative` → ~90%+ success, significantly slower

---

## Architecture

**Phase flow:**
```
main.py (CLI + backup orchestration)
  → scraper.py     (Phase 1: index crawl → Phase 2: detail hydration)
  → extractor.py   (Phase 3: Ollama LLM extraction + Pydantic validation)
  → analytics.py   (Phase 4: aggregation, quality checks, market insights)
  → generate_report.py (Phase 5: interactive HTML report)
```

**Key design decisions to understand before editing:**

`scraper.py` — 2-step hydration strategy. Step 1 inserts shell rows (URL + MD5 hash as ID, status=`pending`) into `raw_postings`. Step 2 hydrates those rows with full HTML. This separation allows resuming hydration after failures without re-scraping the index. Adaptive delay uses configurable strategies with cycle-based cooldown escalation (30→60→90→120→240 min) when consecutive failures hit threshold=30.

`extractor.py` — Calls Ollama (`qwen2.5:3b`) for each hydrated posting. Validates JSON response with Pydantic (`StructuredInsight` schema). Writes successes to `structured_insights`, failures to `failed_extractions`. Idempotent — skips already-extracted records. Hardcoded model: `extractor.py:119`.

`database.py` — Manages three SQLite tables. Uses UPSERT (`INSERT OR REPLACE`) pattern for idempotent extraction retries. Schema migrations applied inline at `init_database()`. Auto-backup runs before each phase via `main.py`.

`location_normalizer.py` — Maps ~130 raw city name variants to 41 canonical Finnish cities. Called during hydration. Known limitation: some variants remain unresolved ("Kouvola, Kouvola", "HELSINKI" vs "Helsinki", non-Finnish cities like "Sofia").

`analytics.py` — Runs data quality checks (duplicate detection, company/location extraction quality, Finnish language analysis) before generating market stats. The Finnish language detection specifically should be interpreted with caution — see Known Data Issues below.

---

## Database Schema

```sql
raw_postings:
  id TEXT PRIMARY KEY          -- MD5 hash of URL
  url TEXT UNIQUE
  title, company, location, posted_date TEXT
  raw_html TEXT                -- full page content
  scraped_at TIMESTAMP
  extraction_status TEXT       -- 'pending' | 'done' | 'failed'

structured_insights:
  id TEXT PRIMARY KEY          -- FK to raw_postings.id
  standardized_role TEXT
  seniority TEXT               -- CHECK: 'Junior'|'Mid'|'Senior'|'Lead'|'Unknown'
  skills TEXT                  -- JSON array of skill strings
  frameworks_tools TEXT        -- JSON array of tool strings
  is_english BOOLEAN
  finnish_language_required BOOLEAN
  extracted_at TIMESTAMP

failed_extractions:
  id TEXT PRIMARY KEY          -- FK to raw_postings.id
  raw_output TEXT              -- what the LLM actually returned
  error_message TEXT           -- Pydantic or parse error
  failed_at TIMESTAMP
```

`extraction_status` lifecycle: `pending` → `done` (success) or `failed`.

Backup files: `duunitori_pipeline_backup_<timestamp>.db` — accumulate in working directory, safe to delete old ones.

---

## Known Issues — Fix These Before Editing

**Location normalization incomplete**
`location_normalizer.py` handles most cases but leaves some unresolved: "Kouvola, Kouvola" (duplicated name), "HELSINKI" (case variant), "Helsinki, Finland" (country suffix), and non-Finnish cities ("Sofia", "Katowice"). These appear in geographic analytics output. Fix in `location_normalizer.py` normalization mappings.

---

## Known Data Issues — Don't Try To "Fix" These

**Finnish language requirement is not reliably measurable from this dataset.**
Duunitori posts many roles in both Finnish and English simultaneously. The `finnish_language_required` field reflects which language version was kept after deduplication, not actual market demand. Previous attempts to "fix" this by preferring Finnish versions during dedup swung the stat from 5% → 82.5%. Neither number is trustworthy. Report it as "posting language availability" only.

**Skills/frameworks category overlap**
Python, Java, AWS appear in both `skills` and `frameworks_tools` rankings. The LLM doesn't consistently categorize these. Don't try to enforce strict separation without a validated taxonomy — the current conservative approach is preferable to hallucinated precision.

**23% of jobs have no skills extracted**
LLM defaults to empty array when uncertain rather than guessing. This is intentional conservative behavior, not a bug.

---

## Ollama Integration

Connects to `http://localhost:11434` (Ollama default). If `ollama` package is not installed, `Client` is set to `None` and all extraction calls return `None` gracefully.

Model: `qwen2.5:3b` (hardcoded in `extractor.py:119`). Switching to a larger model will improve extraction quality but significantly increase runtime. At `qwen2.5:3b`, expect ~45s per job.

Timeout: 86400s (24h) — intentionally large to handle slow hardware.

---

## What Good Output Looks Like

After a full pipeline run you should see:
- `raw_postings`: ~2,000 rows, ~98% with `extraction_status='done'`
- `structured_insights`: ~880-990 rows (after dedup)
- `failed_extractions`: ideally 0, acceptable <5%
- `report.html`: interactive charts, opens in browser
- Console: geographic distribution, top skills, seniority breakdown, data quality report

If `structured_insights` count is much lower than `raw_postings done` count — the extraction bottleneck is still running or failed silently. Check `failed_extractions` table and pipeline logs.