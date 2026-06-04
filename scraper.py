"""
Duunitori web scraper with 2-step crawling strategy:
  Step 1: Index Scraping - traverse listing pages, extract job links
  Step 2: Detail Hydration - fetch full job descriptions and populate raw_html

Features: pagination, adaptive backoff, cycle-based cooldown, company/location extraction,
          idempotency, transaction-based writes.
"""
import requests
from bs4 import BeautifulSoup
import time
import random
import hashlib
import re
import math
from urllib.parse import urljoin
from typing import Optional
from datetime import datetime, timedelta
from database import init_database, url_exists, insert_raw_posting, get_connection, update_extraction_status
from logger import logger
from location_normalizer import normalize_location

# Duunitori IT sector landing page
BASE_URL = "https://duunitori.fi/tyopaikat/ala/tieto-tietoliikennetekniikka"

# Rate limiting strategies for Duunitori
# Strategy options: 'fast' (~50% success), 'balanced' (70-80%), 'conservative' (90%+)
RATE_LIMIT_STRATEGY = 'balanced'

STRATEGIES = {
    'fast': {
        'MIN_DELAY': 2,
        'MAX_DELAY': 5,
        'BACKOFF_FACTOR': 1.5,
        'JITTER': False,
        'description': 'Fast but ~50% success - gets rate limited quickly'
    },
    'balanced': {
        'MIN_DELAY': 5,
        'MAX_DELAY': 30,
        'BACKOFF_FACTOR': 2,
        'JITTER': True,
        'description': 'Balanced - expect 70-80% hydration success'
    },
    'conservative': {
        'MIN_DELAY': 10,
        'MAX_DELAY': 60,
        'BACKOFF_FACTOR': 2.5,
        'JITTER': True,
        'description': 'Very slow - expect 90%+ success but takes longer'
    }
}

strategy = STRATEGIES[RATE_LIMIT_STRATEGY]
MIN_DELAY = strategy['MIN_DELAY']
MAX_DELAY = strategy['MAX_DELAY']
BACKOFF_FACTOR = strategy['BACKOFF_FACTOR']
USE_JITTER = strategy['JITTER']
MAX_RETRIES = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
]

# Adaptive delay state
rate_limit_delay = MIN_DELAY
last_request_time = 0


def adaptive_delay() -> None:
    global rate_limit_delay, last_request_time
    actual_delay = rate_limit_delay
    if USE_JITTER:
        actual_delay += rate_limit_delay * random.uniform(0, 0.3)
    elapsed = time.time() - last_request_time
    if elapsed < actual_delay:
        time.sleep(actual_delay - elapsed)
    last_request_time = time.time()


def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def on_rate_limit() -> None:
    global rate_limit_delay
    rate_limit_delay = min(rate_limit_delay * BACKOFF_FACTOR, MAX_DELAY)
    logger.warning(f"Rate limit detected. Increasing delay to {rate_limit_delay:.1f}s")


def on_success() -> None:
    global rate_limit_delay
    rate_limit_delay = max(rate_limit_delay * 0.95, MIN_DELAY)


def count_pending_jobs() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM raw_postings WHERE raw_html IS NULL OR raw_html = ''")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def calculate_cycles_needed(total_jobs: int, jobs_per_cycle: int = 500) -> int:
    return math.ceil(total_jobs / jobs_per_cycle)


def is_empty_response(response_text: str) -> bool:
    """Detect silent IP block: HTTP 200 but empty or login-wall page."""
    if not response_text or len(response_text.strip()) < 100:
        return True
    if '<h1' not in response_text.lower() and '<body' not in response_text.lower():
        return True
    if '<form' in response_text.lower() and ('login' in response_text.lower() or 'password' in response_text.lower()):
        if 'sign in' in response_text.lower() or 'login button' in response_text.lower():
            return True
    return False


def wait_for_ip_recovery(hours: int = 4, check_interval: int = 300) -> None:
    end_time = datetime.now() + timedelta(hours=hours)
    logger.warning(f"IP blocked! Waiting until {end_time.strftime('%H:%M:%S')} ({hours}h recovery)...")
    while datetime.now() < end_time:
        hours_left = (end_time - datetime.now()).total_seconds() / 3600
        logger.info(f"IP recovery: {hours_left:.1f}h remaining")
        time.sleep(check_interval)
    logger.info("IP recovery complete. Resuming...")
    time.sleep(5)


def extract_job_metadata(soup: BeautifulSoup) -> tuple:
    """
    Extract company name and location from a hydrated job page.
    Uses 4 fallback strategies for company, 2 for location.

    Returns:
        (company_name, location, company_id, company_registry_id)
    """
    try:
        company_name = "Unknown"
        location = "Unknown"
        company_id = ""
        company_registry_id = ""

        page_text = soup.get_text()

        # Company strategy 1: "CompanyName - City" pattern (most common on Duunitori)
        match = re.search(
            r'^([A-ZÄÖÅa-zäöå0-9\s\-&\.,()]+?)\s*-\s*'
            r'(?:Helsinki|Espoo|Tampere|Turku|Oulu|Jyväskylä|Kuopio|Lappeenranta|'
            r'Joensuu|Pori|Lahti|Vaasa|Seinäjoki|Rovaniemi|Kouvola|Hämeenlinna|'
            r'Porvoo|Raisio|Vantaa|Kauniainen|Mikkeli|Naantali|Salo|Lieto)',
            page_text,
            re.MULTILINE
        )
        if match:
            candidate = match.group(1).strip()
            if 2 < len(candidate) < 200:
                company_name = candidate

        # Company strategy 2: "Toiminimi" header
        if company_name == "Unknown":
            for header in soup.find_all(['h4', 'h3', 'h2', 'label']):
                if 'toiminimi' in header.get_text().lower():
                    elem = header.find_next(['div', 'p', 'span'])
                    if elem:
                        name = elem.get_text(strip=True)
                        if name and name != "Unknown":
                            company_name = name
                            break

        # Company strategy 3: Finnish company suffixes (Oy, Ab, Oyj...)
        if company_name == "Unknown":
            for suffix in [' Oy ', ' Oyj', ' Ab ', ' Ry ', ' Plc', ' Ltd', ' GmbH', ' AG']:
                matches = re.findall(
                    r'([A-ZÄÖÅa-zäöå0-9\s\-&\.]+' + re.escape(suffix) + r')',
                    page_text
                )
                if matches:
                    company_name = matches[0].strip()
                    break

        # Company strategy 4: element-level suffix scan
        if company_name == "Unknown":
            for elem in soup.find_all(['p', 'div', 'span']):
                text = elem.get_text(strip=True)
                if any(s in text for s in [' Oy', 'Oyj', ' Ab', ' Ry', ' Plc']):
                    matches = re.findall(
                        r'^([A-ZÄÖÅa-zäöå0-9\s\-&\.]+?(?:\s(?:Oy|Oyj|Ab|Ry|Plc|Ltd|GmbH))?)',
                        text
                    )
                    if matches and len(matches[0]) > 2:
                        company_name = matches[0].strip()
                        break

        # Location strategy 1: "Työpaikan sijainti" header
        for header in soup.find_all(['h4', 'h3', 'h2']):
            if 'sijainti' in header.get_text().lower():
                elem = header.find_next(['div', 'p', 'span'])
                if elem:
                    loc = elem.get_text(strip=True)[:200]
                    if loc and loc != "Unknown":
                        location = loc
                        break

        # Location strategy 2: scan for Finnish city names
        if location == "Unknown":
            finnish_cities = [
                'Espoo', 'Helsinki', 'Tampere', 'Turku', 'Oulu', 'Jyväskylä', 'Kuopio',
                'Lappeenranta', 'Joensuu', 'Pori', 'Lahti', 'Vaasa', 'Seinäjoki', 'Rovaniemi',
                'Kouvola', 'Hämeenlinna', 'Porvoo', 'Raisio', 'Vantaa', 'Kauniainen',
                'Mikkeli', 'Naantali', 'Salo', 'Lieto',
            ]
            for elem in soup.find_all(['p', 'div', 'span']):
                text = elem.get_text(strip=True)
                for city in finnish_cities:
                    if city in text:
                        location = city
                        break
                if location != "Unknown":
                    break

        location = normalize_location(location)

        # Y-tunnus (company registry ID)
        for text_node in soup.find_all(string=re.compile(r'Y-tunnus', re.IGNORECASE)):
            parent = text_node.parent
            sibling = parent.find_next_sibling()
            if sibling:
                y_tunnus = sibling.get_text(strip=True)
                if re.match(r'\d+-\d+', y_tunnus):
                    company_registry_id = y_tunnus
                    break

        return (company_name, location, company_id, company_registry_id)

    except Exception as e:
        logger.debug(f"Error extracting job metadata: {e}")
        return ("Unknown", "Unknown", "", "")


def validate_title(title: str) -> bool:
    """Return False for error pages and placeholder titles."""
    if not title or len(title.strip()) < 3:
        return False
    invalid = ['pending', 'sign in', 'login', '404', 'error', 'not found',
               'unknown', 'none', 'n/a', 'unavailable', 'page not found']
    return not any(s in title.lower() for s in invalid)


def step1_index_scraping(max_pages: int = 50) -> int:
    """
    Step 1: Traverse listing pages and extract job posting URLs.
    Inserts shell rows (status='pending', raw_html='') for each new URL found.

    Returns:
        Count of new job shells inserted
    """
    logger.info("=" * 70)
    logger.info("STEP 1: INDEX SCRAPING - Extracting job URLs from listing pages")
    logger.info("=" * 70)

    page = 1
    total_new_shells = 0
    consecutive_empty_pages = 0

    while page <= max_pages:
        logger.info(f"Fetching listing page {page}...")
        params = {"sivu": page}

        for attempt in range(MAX_RETRIES):
            try:
                adaptive_delay()

                response = requests.get(
                    BASE_URL,
                    params=params,
                    timeout=10,
                    headers={"User-Agent": get_random_user_agent()}
                )

                if response.status_code == 200:
                    on_success()
                    soup = BeautifulSoup(response.content, "html.parser")

                    job_urls = [
                        urljoin("https://duunitori.fi", link["href"])
                        for link in soup.find_all("a", href=True)
                        if link["href"].startswith("/tyopaikat/tyo/") or link["href"].startswith("/tyopaikat/v/")
                    ]

                    if not job_urls:
                        logger.warning(f"No job links found on page {page}")
                        consecutive_empty_pages += 1
                        if consecutive_empty_pages >= 3:
                            logger.info("Three consecutive empty pages. Stopping index scraping.")
                            return total_new_shells
                        break

                    consecutive_empty_pages = 0
                    logger.info(f"Found {len(job_urls)} job links on page {page}")

                    for job_url in job_urls:
                        if not url_exists(job_url):
                            job_id = hashlib.md5(job_url.encode()).hexdigest()
                            if insert_raw_posting(
                                id=job_id,
                                url=job_url,
                                title="Pending",
                                company="Pending",
                                location="Pending",
                                posted_date="Pending",
                                raw_html="",
                                extraction_status="pending"
                            ):
                                total_new_shells += 1
                        else:
                            logger.debug(f"URL already exists, skipping: {job_url}")

                    page += 1
                    break

                elif response.status_code == 403:
                    on_rate_limit()
                    wait_time = 30 * (BACKOFF_FACTOR ** attempt)
                    logger.warning(f"HTTP 403 on page {page}. Backing off {wait_time:.0f}s...")
                    time.sleep(wait_time)

                elif response.status_code in [429, 503]:
                    on_rate_limit()
                    wait_time = BACKOFF_FACTOR ** attempt
                    logger.warning(f"Rate limited ({response.status_code}). Retrying in {wait_time}s...")
                    time.sleep(wait_time)

                elif response.status_code >= 400:
                    logger.error(f"HTTP {response.status_code} on page {page}. Stopping.")
                    return total_new_shells

            except requests.RequestException as e:
                logger.error(f"Request exception attempt {attempt + 1}: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BACKOFF_FACTOR ** attempt)

        else:
            logger.error(f"Failed to fetch page {page} after {MAX_RETRIES} retries. Stopping.")
            break

    logger.info(f"Step 1 complete. Inserted {total_new_shells} new job shells.")
    return total_new_shells


def step2_detail_hydration() -> int:
    """
    Step 2: Fetch full job pages and populate raw_html, title, company, location.
    Uses cycle-based progressive cooldown (30→60→...→240 min) when IP blocking detected.

    Returns:
        Count of successfully hydrated records
    """
    logger.info("=" * 90)
    logger.info("STEP 2: DETAIL HYDRATION - Smart Cycle-Based Cooldown Strategy")
    logger.info("=" * 90)

    JOBS_PER_CYCLE = 500
    FAILURE_THRESHOLD = 30

    total_pending = count_pending_jobs()
    if total_pending == 0:
        logger.info("No pending records to hydrate.")
        return 0

    cycles_needed = calculate_cycles_needed(total_pending, JOBS_PER_CYCLE)
    logger.info(f"Total jobs to hydrate: {total_pending} | Cycles needed: {cycles_needed}")
    logger.info("=" * 90)

    total_successfully_hydrated = 0

    for cycle_num in range(1, cycles_needed + 1):
        logger.info(f"\n{'='*90}")
        logger.info(f"CYCLE {cycle_num}/{cycles_needed}")
        logger.info(f"{'='*90}")

        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT id, url FROM raw_postings
                WHERE (raw_html IS NULL OR raw_html = '')
                ORDER BY scraped_at ASC
                LIMIT ?
            """, (JOBS_PER_CYCLE,))
            cycle_records = cursor.fetchall()
        finally:
            conn.close()

        if not cycle_records:
            logger.info(f"No more records to hydrate in cycle {cycle_num}.")
            break

        logger.info(f"Hydrating {len(cycle_records)} jobs in this cycle...")

        cycle_hydrated = 0
        consecutive_failures = 0
        cooldown_tier = 1
        cooldown_recoveries = 0

        def _trigger_cooldown(reason: str) -> bool:
            """Apply progressive cooldown. Returns True if we should stop entirely."""
            nonlocal cooldown_tier, cooldown_recoveries, consecutive_failures
            cooldown_minutes = min(cooldown_tier * 30, 240)
            logger.error(f"COOLDOWN TRIGGERED ({reason}) after {consecutive_failures} failures!")
            logger.error(f"Tier {cooldown_tier}: {cooldown_minutes}-minute cooldown...")
            cooldown_recoveries += 1

            if cooldown_recoveries > 1 and cooldown_minutes >= 240:
                logger.error("Max cooldown reached. IP appears permanently blocked. Shutting down.")
                return True

            if cycle_num < cycles_needed:
                logger.info(f"Waiting until {(datetime.now() + timedelta(minutes=cooldown_minutes)).strftime('%H:%M:%S')}...")
                time.sleep(cooldown_minutes * 60)
                cooldown_tier += 1
                consecutive_failures = 0
            return False

        for cycle_idx, (job_id, job_url) in enumerate(cycle_records, 1):
            # Strip favorites suffix — causes 403/login redirect
            if job_url.endswith('/lisaa_suosikkeihin'):
                job_url = job_url[:-len('/lisaa_suosikkeihin')]

            progress = f"[Cycle {cycle_num}/{cycles_needed}] [{cycle_idx}/{len(cycle_records)}]"
            logger.info(f"{progress} Hydrating: {job_url}")

            for attempt in range(MAX_RETRIES):
                try:
                    adaptive_delay()
                    response = requests.get(job_url, timeout=10, headers={"User-Agent": get_random_user_agent()})

                    if response.status_code == 200:
                        on_success()

                        if is_empty_response(response.text):
                            consecutive_failures += 1
                            logger.warning(f"Empty/login response ({consecutive_failures}/{FAILURE_THRESHOLD}). Possible IP block.")
                            if consecutive_failures >= FAILURE_THRESHOLD:
                                total_successfully_hydrated += cycle_hydrated
                                if _trigger_cooldown("empty responses"):
                                    return total_successfully_hydrated
                                break
                            break

                        consecutive_failures = 0
                        soup = BeautifulSoup(response.content, "html.parser")

                        title_elem = soup.find("h1")
                        title = title_elem.get_text(strip=True) if title_elem else "Unknown"

                        if not validate_title(title):
                            consecutive_failures += 1
                            logger.warning(f"Invalid title '{title}' ({consecutive_failures}/{FAILURE_THRESHOLD}). Skipping.")
                            if consecutive_failures >= FAILURE_THRESHOLD:
                                total_successfully_hydrated += cycle_hydrated
                                if _trigger_cooldown("invalid titles"):
                                    return total_successfully_hydrated
                                break
                            break

                        company, location, _, _ = extract_job_metadata(soup)

                        description_container = (
                            soup.find("main") or
                            soup.find("article") or
                            soup.find("div", class_=lambda x: x and "content" in str(x).lower())
                        )
                        if description_container:
                            for tag in description_container(["script", "style"]):
                                tag.decompose()
                            raw_html = description_container.get_text(separator=" ", strip=True)
                        else:
                            raw_html = soup.get_text(separator=" ", strip=True)

                        content_hash = hashlib.md5(raw_html.encode()).hexdigest()

                        conn = get_connection()
                        cur = conn.cursor()
                        try:
                            cur.execute("""
                                UPDATE raw_postings
                                SET title = ?, company = ?, location = ?, raw_html = ?, content_hash = ?
                                WHERE id = ?
                            """, (title, company, location, raw_html, content_hash, job_id))
                            conn.commit()
                            logger.info(f"{progress} ✓ {title[:40]} | {company[:25]} | {location}")
                            cycle_hydrated += 1
                        except Exception as e:
                            logger.error(f"DB update error: {e}")
                            conn.rollback()
                        finally:
                            conn.close()
                        break

                    elif response.status_code == 403:
                        consecutive_failures += 1
                        on_rate_limit()
                        logger.warning(f"HTTP 403 ({consecutive_failures}/{FAILURE_THRESHOLD})")
                        if consecutive_failures >= FAILURE_THRESHOLD:
                            total_successfully_hydrated += cycle_hydrated
                            if _trigger_cooldown("HTTP 403"):
                                return total_successfully_hydrated
                            break
                        break

                    elif response.status_code in [429, 503]:
                        on_rate_limit()
                        time.sleep(BACKOFF_FACTOR ** attempt)

                    elif response.status_code >= 400:
                        consecutive_failures += 1
                        logger.warning(f"HTTP {response.status_code} ({consecutive_failures}/{FAILURE_THRESHOLD})")
                        if consecutive_failures >= FAILURE_THRESHOLD:
                            total_successfully_hydrated += cycle_hydrated
                            if _trigger_cooldown(f"HTTP {response.status_code}"):
                                return total_successfully_hydrated
                            break
                        break

                except requests.RequestException as e:
                    logger.error(f"Request exception attempt {attempt + 1}: {e}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(BACKOFF_FACTOR ** attempt)

            else:
                consecutive_failures += 1
                logger.error(f"Failed to hydrate {job_url} after {MAX_RETRIES} retries ({consecutive_failures}/{FAILURE_THRESHOLD}).")
                update_extraction_status(job_id, "failed")
                if consecutive_failures >= FAILURE_THRESHOLD:
                    total_successfully_hydrated += cycle_hydrated
                    if _trigger_cooldown("max retries exceeded"):
                        return total_successfully_hydrated

        total_successfully_hydrated += cycle_hydrated
        logger.info(f"Cycle {cycle_num} complete. Hydrated: {cycle_hydrated}/{len(cycle_records)}")

        if cycle_num < cycles_needed:
            time.sleep(5)

    logger.info(f"\n{'='*90}")
    logger.info(f"HYDRATION COMPLETE — Total hydrated: {total_successfully_hydrated}")
    logger.info(f"{'='*90}\n")
    return total_successfully_hydrated


def scrape_pipeline() -> None:
    """Main scraping orchestrator: run both steps in sequence."""
    logger.info("Starting Duunitori 2-step scraping pipeline")
    logger.info(f"Rate limit strategy: {RATE_LIMIT_STRATEGY} — {strategy['description']}")
    logger.info(f"  Delays: {MIN_DELAY}s–{MAX_DELAY}s | Backoff: {BACKOFF_FACTOR}x | Jitter: {USE_JITTER}")
    init_database()

    try:
        new_shells = step1_index_scraping()
        hydrated_count = step2_detail_hydration()
        logger.info("=" * 70)
        logger.info(f"Pipeline Summary: {new_shells} shells inserted, {hydrated_count} records hydrated")
        logger.info("=" * 70)
    except Exception as e:
        logger.error(f"Scraping pipeline failed: {e}", exc_info=True)
        raise


def generate_hydration_summary() -> None:
    """Print hydration statistics and top market signals to the log."""
    logger.info("\n" + "=" * 90)
    logger.info("HYDRATION & MARKET SUMMARY REPORT")
    logger.info("=" * 90)

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN raw_html IS NOT NULL AND raw_html != '' THEN 1 ELSE 0 END) as hydrated,
                SUM(CASE WHEN extraction_status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN raw_html IS NULL OR raw_html = '' THEN 1 ELSE 0 END) as pending
            FROM raw_postings
        """)
        total, hydrated, failed, pending = cursor.fetchone()

        logger.info(f"\n  Total:    {total}")
        logger.info(f"  Hydrated: {hydrated} ({100*hydrated/total if total else 0:.1f}%) ✓")
        logger.info(f"  Failed:   {failed} ({100*failed/total if total else 0:.1f}%) ✗")
        logger.info(f"  Pending:  {pending} ({100*pending/total if total else 0:.1f}%) ⏳")

        cursor.execute("SELECT COUNT(*) FROM structured_insights")
        total_extracted = cursor.fetchone()[0]

        if total_extracted > 0:
            logger.info(f"\n  Top roles (from {total_extracted} extracted jobs):")
            cursor.execute("""
                SELECT standardized_role, COUNT(*) as n
                FROM structured_insights
                WHERE standardized_role IS NOT NULL AND standardized_role != 'Unknown'
                GROUP BY standardized_role ORDER BY n DESC LIMIT 10
            """)
            for rank, (role, count) in enumerate(cursor.fetchall(), 1):
                logger.info(f"    {rank:2d}. {role:<45} {count:>4} ({100*count/total_extracted:.1f}%)")

            logger.info(f"\n  Top skills:")
            cursor.execute("""
                SELECT value, COUNT(*) as n
                FROM structured_insights, json_each(structured_insights.skills)
                WHERE skills IS NOT NULL AND skills != '[]'
                GROUP BY value ORDER BY n DESC LIMIT 10
            """)
            for rank, (skill, count) in enumerate(cursor.fetchall(), 1):
                logger.info(f"    {rank:2d}. {skill:<45} {count:>4} ({100*count/total_extracted:.1f}%)")

        logger.info("=" * 90 + "\n")
        conn.close()

    except Exception as e:
        logger.error(f"Error generating hydration summary: {e}")


if __name__ == "__main__":
    scrape_pipeline()
