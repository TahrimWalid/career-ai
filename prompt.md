These last two points move this pipeline from a "weekend hobby project" to a genuinely robust, production-grade piece of software.

Adding the CLI flags turns your pipeline into an actionable utility where you can scrape on a daily cron job, run the extraction script manually when your local GPU is free, and run analytics on demand. Swapping print() for a dual-handler logging setup ensures you have a permanent trail when debugging scraping blocks or subtle LLM parsing syntax issues.

Here is the final, completely gap-free v4 "Vibe Coding" Developer Specification. It incorporates everything discussed: the qwen2.5:7b optimization, the state machine status updates, strict schema parsing, json_each() aggregation, decoupled CLI flags, and continuous dual-file/stdout logging.

Copy-paste this absolute final version into your project directory workspace to let Copilot build your pipeline:

Developer Specification v4: Duunitori Resilient Production Pipeline
1. Architectural Strategy & Plan
We are building a resilient data ingestion and semantic structuring engine targeting Duunitori.fi (Tech/IT sector in Finland).

To ensure the system scales efficiently and doesn't waste LLM API credits, the architecture splits processing into independent, stateless steps using SQLite, Python's argparse, and Ollama (Local LLM using Qwen2.5:7b).

                  [main.py CLI Orchestrator]
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
        (--scrape)      (--extract)    (--analytics)
    [Duunitori Pages]       │               │
            │               ▼               ▼
            ▼       [Ollama Qwen2.5:7b] [SQLite Engine]
     [SQLite Ingest]        │               │
  (Status: 'pending')       ├───────────────┤ (Uses json_each)
                            ▼               ▼
                  Success: 'done'   [Stdout Reports]
                  Failure: 'failed'
Core Design Rules
Idempotency: Never fetch the same job ad URL twice. Never run LLM extraction on a job description that has an extraction status of done or failed.

Decoupled CLI Isolation: Scraping, extracting, and reporting are completely isolated executable branches. If one phase encounters an unhandled runtime exception, previous phase state payloads stored inside SQLite remain unaffected.

Zero Aggregation via VectorDB: We process text through the LLM strictly to extract standardized tokens into relational databases. Trend questions are answered cleanly via SQL aggregates utilizing specialized SQLite JSON functions.

2. Coding Instructions & Prompt for Copilot
Act as a Principal Staff Engineer specializing in robust ETL (Extract, Transform, Load) pipelines, Python, and Local LLM integrations. Write modular, highly maintainable, production-ready code with type hinting and clean error logging for the following specifications:

Target Context
Source: [https://duunitori.fi/tyopaikat?alue=&haku=tietotekniikka](https://duunitori.fi/tyopaikat?alue=&haku=tietotekniikka)

Stack: Python 3.11+, SQLite (via native sqlite3), beautifulsoup4, pydantic v2, and ollama Python SDK (using model qwen2.5:7b).

Generate the file structure and complete implementation step-by-step using the layout below:

File 1: requirements.txt
Generate a requirements.txt pinning the exact libraries used for this project, including requests, beautifulsoup4, pydantic, and ollama.

File 2: logger.py
Set up a central logging utility module using Python's native logging library.

Configure it to stream logs simultaneously to both stdout (the terminal screen) and a local file named pipeline.log.

Enforce a clean log formatting string that contains exact timestamps: %(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s.

Import and use this initialized logger across all subsequent Python modules instead of native print() statements.

File 3: database.py
Set up an SQLite database configuration containing three tables:

raw_postings:

id: TEXT (Primary Key, unique hash or Duunitori job ID)

url: TEXT (Unique)

title: TEXT

company: TEXT

location: TEXT (e.g., Helsinki, Tampere, Remote)

posted_date: TEXT

raw_html: TEXT

scraped_at: TIMESTAMP

extraction_status: TEXT (Default 'pending'. Allowed values: 'pending', 'done', 'failed')

structured_insights:

id: TEXT (Foreign Key linked to raw_postings)

standardized_role: TEXT

seniority: TEXT

skills: TEXT (JSON serialized text array)

frameworks_tools: TEXT (JSON serialized text array)

is_english: BOOLEAN

failed_extractions:

id: TEXT (Primary Key, matches raw_postings.id)

raw_output: TEXT (The malformed text returned by the LLM)

error_message: TEXT

failed_at: TIMESTAMP

File 4: scraper.py
Write a scraper script capable of:

Paginating through Duunitori's IT sector search result listings.

Extracting the main direct URLs, title, company, location, and posting date for individual job ads.

Checking the SQLite database to see if the URL already exists. If it exists, skip.

Fetching the unique job description page, extracting the main article content container, and dumping the payload into raw_postings with extraction_status='pending'.

Resiliency Rule: Include randomized delay timers (2 to 5 seconds) between requests. If an HTTP 4xx or 5xx response is encountered (e.g., rate-limiting), implement exponential backoff with a maximum of 3 retries before logging the error and skipping that specific URL.

File 5: extractor.py
Write a script that processes unparsed records:

Query raw_postings where extraction_status='pending'.

Parse raw HTML with BeautifulSoup to strip script tags, styles, and extract pure, human-readable prose text.

Explicitly enforce and use this exact Pydantic Schema for validation:

Python
from pydantic import BaseModel
from typing import Literal

class StructuredInsight(BaseModel):
    standardized_role: str
    seniority: Literal["Junior", "Mid", "Senior", "Lead", "Unknown"]
    skills: list[str]
    frameworks_tools: list[str]
    is_english: bool
Feed the clean prose into the ollama client wrapper using model qwen2.5:7b with JSON mode enabled.

System Prompt instruction:
*"Analyze this Finnish/English job posting. Categorize the overarching job profile into a clean standardized title. Explicitly distinguish between 'skills' and 'frameworks_tools':

skills: Only languages, core technologies, protocols, and major cloud platforms (e.g., Python, AWS, Java, Azure, SQL, CCNA).

frameworks_tools: Only libraries, frameworks, runtime environments, and infrastructure tooling (e.g., Terraform, Docker, React, Kubernetes, Django, Node.js).
Output strictly valid JSON conforming to the requested schema. Do not append any conversational introductory or concluding text."*

Fault-Tolerance Rule: If the LLM output fails Pydantic validation or outputs malformed JSON, catch the exception, log the issue using the tracking framework, write the raw output and error log to the failed_extractions table, update the extraction_status to 'failed' in raw_postings inside a unified transaction block, and gracefully continue to the next record without crashing.

Upon successful validation, populate structured_insights, serialize the arrays to JSON strings, and update extraction_status='done' in raw_postings inside a unified database transaction block.

File 6: analytics.py
Write an analytical query script that prints top market insights straight to stdout using native SQL aggregates.

JSON Handling Rule: Because skills and frameworks_tools are stored as JSON-serialized strings in SQLite, you must use SQLite’s json_each() function to unnest the JSON array columns when counting and aggregating data.

Generate queries for:

Top 10 most in-demand skills right now.

Top 10 most in-demand frameworks_tools right now.

Market demand mapped across structural seniority tiers (Senior vs Junior frequency).

Geographic distribution based on the location field.

File 7: main.py
Create an orchestration entry point using Python's argparse module to safely isolate executing parameters.

Always ensure database initialization runs silently upon any entry call to guarantee tables exist.

Implement explicit CLI execution argument flags matching these behaviors:

python main.py --scrape -> Runs only the web scraper loop (scraper.py).

python main.py --extract -> Runs only the LLM ingestion loop over pending entries (extractor.py).

python main.py --analytics -> Runs only the relational analytics parsing reports (analytics.py).

python main.py --all -> Default option that runs all three operational steps sequentially in standard sequence order.

Output Requirements
Deliver the solution cleanly across separate modular files as defined.

Ensure comprehensive error handling surrounds both the network scraping layers and parsing loops.

Write clean, readable code utilizing explicit type hints. Let's begin coding step-by-step.