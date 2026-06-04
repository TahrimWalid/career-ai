# Finnish IT Job Market Intelligence Pipeline

### 1,998 jobs scraped. 100% extracted. Built to answer one question: *what does the Finnish tech market actually hire for?*

> **What started as a simple scraper became a lesson in data integrity, algorithmic bias, and why honest engineering matters more than clean numbers.**

---

## The Real Story

Most portfolio projects show you the finished result. This one shows you the mess in between.

I needed to make data-driven decisions about which skills to invest in while transitioning into cloud/networking roles in Finland. So I built a pipeline to analyze the real market — 2,002 jobs scraped from Duunitori.fi, structured with a local LLM, and analyzed for actionable signals. Along the way:

- Discovered **54% of the raw data was duplicates** — silently inflating every metric
- Fixed deduplication, then realized the fix introduced **systematic bias** (Finnish-language jobs appearing to dominate overnight)
- Watched the "Finnish language required" stat swing from **5% → 82.5% → 4.5%** across three runs — each technically correct, none actually meaningful
- Stopped chasing a precise number and instead **documented why it can't be measured reliably from this data**

That last part — choosing honest uncertainty over false precision — is the actual point of this project.

---

## What It Does

A 5-phase ETL pipeline:

```
Phase 1: Scrape       → Crawl Duunitori index pages, collect 2,002 job URLs
Phase 2: Hydrate      → Fetch full job pages with adaptive rate limiting (96.7% success)
Phase 3: Extract      → Local LLM (qwen2.5:3b via Ollama) parses each posting into
                        structured JSON: role, seniority, skills, tools, language flags
Phase 4: Analytics    → Aggregation, duplicate detection, data quality checks,
                        market insight generation
Phase 5: Report       → Interactive HTML dashboard with Chart.js visualisations
```

**Output:** `report.html` + a fully queryable SQLite database of 1,998 extracted IT job records from Finland (May 2026 snapshot). Zero cloud dependencies — everything runs locally.

---

## Key Findings

From 1,998 IT job postings on Duunitori.fi (May 2026):

| Signal | Finding | Confidence |
|--------|---------|------------|
| Most demanded skill | AWS | High |
| Second most demanded | Python | High |
| Top framework/tool | Docker | High |
| Geographic concentration | Helsinki + Espoo = **83%** of all roles | High |
| Dominant work arrangement | Hybrid = **98.2%** — full remote is rare (0.5%) | High |
| Dominant seniority tier | Mid-level = **89%** of postings | Medium |
| Junior roles | 0.5% of explicit postings — most entry roles unlabelled | Medium |
| Finnish language required | ~4.5% of postings — but see caveat below | Low |

**Note on skill percentages:** The analytics run on all extracted records, which include ~54% potential duplicates (Finnish/English pairs of the same posting). Absolute counts are inflated; the *ranking order* and *relative dominance* of AWS, Python, and Docker are reliable.

**On the Finnish language finding:** The pipeline detected 4.5% of postings explicitly flagging Finnish as required. But Duunitori lists many roles in both Finnish and English simultaneously — the detected rate reflects posting language distribution, not actual market requirements. The true rate is unmeasurable from this dataset. It is reported as-is rather than papered over.

---

## Why The Bias Problem Matters

Here's what actually happened with the Finnish language stat:

```
Strategy A: keep first-seen version  →  5%    Finnish required
Strategy B: prefer Finnish version   →  82.5% Finnish required
Strategy C: current (neutral)        →  4.5%  Finnish required

Reality: all three numbers are artifacts of the algorithm, not the market
```

When a job exists as both Finnish and English postings, *which copy you keep* determines the stat — not the underlying hiring reality. Reporting any of these as "the answer" would be misleading.

The correct answer was: *"This cannot be reliably measured from this dataset. Here's why."*

That choice — documenting uncertainty instead of manufacturing precision — is what this project actually demonstrates about engineering judgment.

---

## Market Insights That Are Reliable

Despite the caveats, several signals come through clearly:

**Skills:** AWS and Python co-occur in ~77% of all postings. If you're in Finnish IT, these two are table stakes. Docker is the dominant infrastructure tool.

**Geography:** 83% of roles concentrate in Helsinki–Espoo. Tampere is a distant third at 3.6%. If you're not in the capital region, the addressable market shrinks significantly.

**Work arrangement:** The hybrid-or-nothing reality is stark — 98.2% hybrid, 0.6% on-site, and only 0.5% fully remote. Companies have made their decision.

**Seniority:** The market is overwhelmingly Mid-level (89%). Senior (4.2%) and Lead (2.4%) roles are comparatively scarce. Junior-labelled roles are nearly absent at 0.5% — entry-level positions either aren't posted on Duunitori, or they're unlabelled.

**Top employers:** 681 unique companies hiring. The market is distributed, not dominated by a handful of giants.

---

## Technical Stack

```
Python 3.12         Pipeline orchestration
SQLite3             Data persistence (UPSERT patterns for idempotent retries)
Ollama              Local LLM inference — no API keys, no cloud cost
qwen2.5:3b          Extraction model (~45s/job on modest hardware)
Pydantic v2         JSON schema validation with field-level constraints
MD5 hashing         Content-addressed deduplication
Adaptive backoff    Rate limit negotiation (2s base → 240 min max cooldown)
Chart.js            Interactive HTML report
```

**No external APIs. No cloud costs. Fully reproducible on any machine with Ollama installed.**

---

## Architecture

```
main.py                 CLI entry point + auto-backup orchestration
  --scrape              Phase 1+2: index crawl → detail hydration
  --extract             Phase 3: LLM extraction with seniority heuristic override
  --analytics           Phase 4+5: aggregation → report.html
  --all                 Full pipeline
  --reset-extraction    Wipe and re-extract (non-destructive to raw scrape)

scraper.py              Two-step hydration: shell rows → full HTML
                        Adaptive delay with cycle-based cooldown escalation
extractor.py            Ollama LLM → Pydantic validation → DB insert
                        Post-parse seniority heuristics (Finnish + English signals)
analytics.py            Data quality checks → market stats → HTML generation
database.py             SQLite schema + UPSERT operations + auto-backup triggers
location_normalizer.py  ~130 raw city variants → 41 canonical Finnish cities
```

---

## Data Quality — Honestly

**What works:**
- 96.7% hydration success (1,932 / 1,998 fetched)
- **100% extraction rate** (1,998 / 1,998 — including retry of all previously-failed jobs)
- 5.5% unknown company names — low noise
- 2.7% unknown locations — near-complete geographic coverage
- Duplicate detection flags 54% of records; pipeline makes this visible rather than silently filtering

**Known limitations (documented, not solved):**
- Location normalization handles most cases but leaves edge cases: "Kouvola, Kouvola" (duplicate suffix), "Helsinki, Finland" (country appended), non-Finnish cities like "Sofia"
- Finnish language requirement is structurally unmeasurable from this dataset
- Seniority heuristics improved with Finnish keywords (`harjoittelija`, `kesätyö`, `vanhempi`, `pääsuunnittelija`, `päällikkö`) but the LLM still defaults many ambiguous postings to Mid
- Single-source snapshot — Duunitori is one slice of the Finnish market

**Skill percentages are inflated by duplicate records.** The analytics pipeline aggregates skills across all rows in `structured_insights`, including the ~1,046 content-hash copies created during extraction deduplication. Because dedup copies the source extraction rather than filtering, every skill in a bilingual posting gets counted once per copy. This inflates absolute skill percentages by roughly the duplicate rate (~54%) — a skill appearing in "80% of jobs" is realistically present in ~52% of unique postings. The fix (aggregating over one row per `content_hash`) would require careful revalidation of all reported numbers. For now, treat absolute skill percentages as upper bounds; ranking order is reliable.

**Two inconsistent duplicate-detection strategies coexist.** `extractor.py` uses content-hash deduplication (identical `raw_html` = duplicate) to avoid redundant LLM calls. The data quality section of the analytics report uses title-hash deduplication (identical lowercased title = potential duplicate) to report the overall "duplicate rate." These strategies measure different things: content-hash is stricter and misses reposts with slightly different HTML; title-hash catches those but can falsely flag different roles that share a generic title. The analytics output presents the title-hash count without flagging the distinction, so the reported duplicate rate won't match what extraction logs show.

**What would improve it:**
- Multi-board scraping (LinkedIn Finland, Jobly, Monster)
- Monthly runs for trend detection
- Manual validation sample to calibrate Finnish language detection

---

## What This Project Is Good For

**Good for:**
- Understanding which skills Finnish IT companies actually demand (AWS + Python + Docker)
- Geographic hiring distribution across Finnish cities
- Work arrangement reality-check (hybrid is the overwhelming norm)
- A reusable local-LLM ETL pattern for structured job market analysis
- An honest case study in pipeline bias detection and data integrity

**Not suitable for:**
- Salary benchmarking (not captured)
- Reliable Finnish language requirement rates (see bias section)
- Trend analysis (single point-in-time snapshot)
- Company-level hiring patterns (too aggregated)

---

## Lessons Learned

**Duplicates hide in plain sight.** 54% of the raw dataset was redundant. Every metric looked plausible until deduplication exposed the inflation — because inflated and uninflated rates were both "in range."

**Deduplication encodes choices.** "Keep the first version" sounds neutral. It isn't. Every deduplication strategy has a bias. Audit yours before reporting.

**Precision is not accuracy.** Reporting 82.5% with two decimal places implies certainty that doesn't exist. Sometimes "we can't measure this reliably" is the most accurate statement you can make.

**Post-LLM heuristics are worth it.** The model under-detects Finnish-language seniority signals (`harjoittelija`, `päällikkö`) that humans read immediately. A small keyword override layer applied after parsing — not before — catches these without hallucinating.

**Adaptive backoff is a negotiation.** Naive scraping hit ~50% success. Cycle-based cooldown escalation (30→60→90→120→240 min on threshold failures) got to 96.7%. Respecting rate limits is also good engineering.

**Backups prevent catastrophe.** Auto-timestamped SQLite copies before every phase have already saved a full run's worth of data. Now a non-negotiable pattern in any pipeline I build.

---

## Running It

```bash
# Prerequisites
pip install -r requirements.txt
ollama pull qwen2.5:3b   # ~2GB model download

# Full pipeline (~6–8 hours: scrape 3.5h + extract 6h + analytics 0.2s)
python main.py --all

# Or phase-by-phase
python main.py --scrape      # Phase 1+2: index crawl + hydration
python main.py --extract     # Phase 3: LLM extraction
python main.py --analytics   # Phase 4+5: analytics + report.html

# Retry only failed extractions without touching completed records
python main.py --extract     # Idempotent — skips already-extracted jobs

# View the report
open report.html             # or xdg-open report.html on Linux
```

---

## Project Context

Built while transitioning into cloud/networking roles (CCNA + AZ-104 track). The irony of using a data pipeline to analyze the job market I'm trying to enter was intentional — if I was going to make bets on which skills to learn, I wanted real data behind them.

The Finnish IT market data here is real and current as of May 2026. Use it for career planning, not hiring decisions.

---

*All findings, limitations, and honest assessments are my own. The bias detection section reflects a genuine mistake caught and corrected mid-project — not a retrospective cleanup.*

---

**Source:** Duunitori.fi | **Snapshot:** May 2026 | **Records:** 1,998 extracted | **Extraction rate:** 100%
