# 🇫🇮 Duunitori Career-AI
### A Finnish IT Job Market Analysis Pipeline — Built Honestly

> **What started as a simple scraper became a lesson in data integrity, algorithmic bias, and why honest engineering matters more than clean numbers.**

---

## The Real Story

Most portfolio projects show you the finished result. This one shows you the mess in between.

I built a pipeline to analyze the Finnish IT job market — 2,002 jobs scraped from Duunitori.fi, structured with a local LLM, and analyzed for market trends. Along the way:

- Discovered **50.7% of the raw data was duplicates** — silently inflating every metric
- Fixed deduplication, then realized the fix introduced **systematic bias** (95% of Finnish-language postings removed overnight)
- Watched the "Finnish language required" stat swing from **5% → 82.5% → back to uncertain** across three runs
- Stopped chasing a precise number and instead **documented why it couldn't be measured reliably from this data**

That last part — choosing honesty over false precision — is the actual point of this project.

---

## What It Does

A 5-phase data pipeline:

```
Phase 1: Scrape       → Crawl 50 Duunitori listing pages, extract 2,002 job URLs
Phase 2: Hydrate      → Fetch full job pages, store raw HTML (98.2% success)
Phase 3: Deduplicate  → Remove 1,016 duplicate postings (MD5 content hash)
Phase 4: Extract      → Local LLM (Ollama qwen2.5:3b) parses skills, seniority, roles
Phase 5: Analyze      → Market intelligence report with honest uncertainty bounds
```

**Output:** An interactive HTML report + SQLite database of 882 unique, structured IT job postings from Finland (May 2026).

---

## Key Findings

From 882 unique IT jobs on Duunitori:

| Signal | Finding | Confidence |
|--------|---------|------------|
| Top skill | Python (12.2%) | High |
| #2 skill | AWS (10.5%) | High |
| Container tools | Docker + K8s = 29.3% of jobs | High |
| Geographic concentration | Helsinki + Espoo = 71.2% | High |
| Junior roles available | 22.8% | Medium |
| Finnish language required | Unmeasurable from this data | Honest |

**On the Finnish language finding:** The pipeline detected 82.5% of jobs had Finnish-language postings. But this reflects *posting language availability*, not a language requirement — Duunitori posts many roles in both Finnish and English simultaneously. The true requirement rate cannot be determined from posting language alone. This limitation is documented rather than papered over.

---

## Why The Bias Problem Matters

Here's what actually happened with deduplication:

```
Naive dedup  →  kept "first" version  →  5% Finnish required
Smart dedup  →  kept Finnish version  →  82.5% Finnish required
Reality      →  both numbers are artifacts of the algorithm, not the market
```

When you have the same job posted in two languages, choosing *which copy to keep* doesn't reveal market truth — it reveals your algorithm's preference. Reporting either number as "accurate" would have been misleading.

The correct answer was: *"This cannot be reliably measured from this dataset. Here's why."*

That realization — choosing to document uncertainty instead of manufacturing precision — is what this project actually demonstrates.

---

## Technical Stack

```
Python 3.x          Pipeline orchestration
SQLite3             Data persistence
Ollama (local LLM)  Structured extraction (qwen2.5:3b)
Pydantic            Schema validation
MD5 hashing         Content deduplication
Adaptive backoff    Rate limit management (2–240 min cooldown)
Chart.js            Interactive HTML report
```

**No external APIs. No cloud costs. Runs entirely locally.**

---

## Architecture

```
main.py                 CLI orchestrator (--scrape, --extract, --analytics, --all)
scraper.py              Web scraping + detail hydration
extractor.py            LLM-based structured extraction
analytics.py            Market analysis + data quality checks
database.py             SQLite operations + UPSERT patterns
location_normalizer.py  City name consolidation (130 variants → 41 cities)
generate_report.py      Interactive HTML output
```

---

## Data Quality — Honestly

**What works well:**
- 98.2% hydration success (1,966 / 2,002 jobs)
- 100% extraction success on deduplicated set (882 / 882)
- 97.97% seniority coverage (only 2% unknown)
- Bias detection built into analytics phase

**Known limitations (not solved, documented):**
- Location normalization incomplete — "Kouvola, Kouvola", "HELSINKI", "Sofia" remain
- Finnish language requirement unmeasurable from posting language alone
- Single source bias — Duunitori represents one slice of the Finnish market
- No salary, remote work, or contract type data
- Point-in-time snapshot (May 2026) — trends shift

**Missing context that would improve this:**
- Multi-board scraping (LinkedIn, Jobly, Monster Finland)
- Manual validation sample for Finnish language detection
- Monthly runs for trend tracking

---

## What This Project Is Good For

✅ Understanding Finnish IT skill demand (Python, AWS, Docker dominate)  
✅ Geographic hiring concentration (Helsinki/Espoo = 71% of roles)  
✅ Seniority distribution in Finnish tech market  
✅ Demonstrating end-to-end pipeline engineering  
✅ A case study in algorithmic bias detection  

❌ Salary benchmarking (no data)  
❌ Precise Finnish language requirement rates (unreliable from this data)  
❌ Remote work prevalence (not captured)  
❌ Company-level hiring patterns (too aggregated)  

---

## Lessons Learned

**Duplicates hide in plain sight.** Half the raw dataset was redundant — and every metric looked plausible until deduplication exposed the inflation.

**Deduplication encodes choices.** "Keep the first version" sounds neutral. It isn't. Every deduplication strategy has a bias. Audit yours before reporting.

**Precision is not accuracy.** Reporting 82.5% with two decimal places implies certainty that doesn't exist. Sometimes "we can't measure this reliably" is the most accurate statement you can make.

**Backups saved the project.** Lost data once mid-pipeline. Pre-phase auto-backups (timestamped SQLite copies) recovered everything. Now mandatory in any pipeline I build.

**Rate limiting is a negotiation.** Aggressive scraping → 50% success. Progressive backoff (2s → 240min cooldown) → 98.2% success. Respecting the server is also good engineering.

---

## Running It

```bash
# Full pipeline (~6-8 hours due to rate limiting + LLM extraction)
python main.py --all

# Individual phases
python main.py --scrape      # Scrape + hydrate
python main.py --extract     # LLM extraction
python main.py --analytics   # Generate report

# View results
open report.html
```

**Requirements:** Python 3.10+, Ollama with qwen2.5:3b installed locally.

---

## Project Context

Built as a portfolio piece while transitioning into cloud/networking. The irony of using a data pipeline to analyze the job market I'm trying to enter was intentional.

The Finnish IT market data here is real and current as of May 2026. Use it for career planning, not hiring decisions.

---

*README written with AI assistance for clarity and structure. All technical findings, limitations, and honest assessments are my own. The bias detection section reflects a genuine mistake I caught and corrected mid-project — not a retrospective cleanup.*

---

**Dataset:** Duunitori.fi | **Period:** May 2026 | **Jobs:** 882 unique | **Version:** 1.0
