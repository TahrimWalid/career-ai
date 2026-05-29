"""
Duunitori web scraper with 2-step crawling strategy:
  Step 1: Index Scraping - traverse listing pages, extract job links
  Step 2: Detail Hydration - fetch full job descriptions and populate raw_html

Features: pagination, exponential backoff, randomized delays, idempotency, transaction-based writes.
"""
import requests
from bs4 import BeautifulSoup
import time
import random
import hashlib
from urllib.parse import urljoin
from typing import Optional
from database import init_database, url_exists, insert_raw_posting, get_connection, update_extraction_status
from logger import logger
import re
from datetime import datetime, timedelta
import math
from location_normalizer import normalize_location

# Duunitori IT sector landing page
BASE_URL = "https://duunitori.fi/tyopaikat/ala/tieto-tietoliikennetekniikka"

# Rate limiting strategies for Duunitori
# Strategy options: 'fast' (50% success), 'balanced' (70-80%), 'conservative' (90%+)
RATE_LIMIT_STRATEGY = 'balanced'  # Change this to tune hydration success

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

# User agents to rotate and avoid bot detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
]

# Rate limit tracking
rate_limit_delay = MIN_DELAY  # Adaptive delay
last_request_time = 0


def adaptive_delay():
    """
    Apply adaptive rate limiting based on consecutive requests.
    Includes jitter to avoid bot detection patterns.
    """
    global rate_limit_delay, last_request_time
    
    # Calculate delay with optional jitter
    actual_delay = rate_limit_delay
    if USE_JITTER:
        # Add 0-30% random variation to avoid bot detection
        jitter = rate_limit_delay * random.uniform(0, 0.3)
        actual_delay = rate_limit_delay + jitter
    
    # Ensure minimum time between requests
    elapsed = time.time() - last_request_time
    if elapsed < actual_delay:
        time.sleep(actual_delay - elapsed)
    
    last_request_time = time.time()


def get_random_user_agent():
    """Return a random user agent to avoid detection"""
    return random.choice(USER_AGENTS)


def on_rate_limit():
    """Call when rate limited (HTTP 429/503) to increase delay"""
    global rate_limit_delay
    rate_limit_delay = min(rate_limit_delay * BACKOFF_FACTOR, MAX_DELAY)
    logger.warning(f"Rate limit detected (HTTP 429/503). Increasing delay to {rate_limit_delay:.1f}s")


def on_success():
    """Call on successful request to gradually decrease delay"""
    global rate_limit_delay
    rate_limit_delay = max(rate_limit_delay * 0.95, MIN_DELAY)  # Slowly decrease


def count_pending_jobs() -> int:
    """Count total jobs needing hydration"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM raw_postings WHERE raw_html IS NULL OR raw_html = ''")
        count = cursor.fetchone()[0]
        return count
    finally:
        conn.close()


def calculate_cycles_needed(total_jobs: int, jobs_per_cycle: int = 500) -> int:
    """Calculate number of cycles needed based on total jobs. Each cycle does 500 jobs."""
    return math.ceil(total_jobs / jobs_per_cycle)


def is_empty_response(response_text: str) -> bool:
    """Detect if response is blocked (HTTP 200 but empty/no actual HTML)"""
    if not response_text or len(response_text.strip()) < 100:
        return True
    # Check for actual HTML structure
    if '<h1' not in response_text.lower() and '<body' not in response_text.lower():
        return True
    # Check for actual login form (not just the word appearing in content)
    # Real login pages have login forms with specific patterns
    if '<form' in response_text.lower() and ('login' in response_text.lower() or 'password' in response_text.lower()):
        if 'sign in' in response_text.lower() or 'login button' in response_text.lower():
            return True
    return False


def get_ip_block_status() -> dict:
    """Check if IP is currently blocked (persistent across restarts)"""
    # DEPRECATED: Progressive cooldown replaces this
    # All blocking is now handled within the cycle loop
    return {'is_blocked': False}


def wait_for_ip_recovery(hours: int = 4, check_interval: int = 300):
    """
    Sleep and wait for IP to recover from rate limiting.
    Check every check_interval seconds and log progress.
    """
    recovery_time = timedelta(hours=hours)
    start_time = datetime.now()
    end_time = start_time + recovery_time
    
    logger.warning(f"IP blocked detected! Entering {hours}-hour recovery period...")
    logger.warning(f"Recovery window: {start_time.strftime('%Y-%m-%d %H:%M:%S')} to {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    while datetime.now() < end_time:
        remaining = end_time - datetime.now()
        hours_left = remaining.total_seconds() / 3600
        logger.info(f"Waiting for IP recovery... {hours_left:.1f} hours remaining (recovery at {end_time.strftime('%H:%M:%S')})")
        time.sleep(check_interval)
    
    logger.info("IP recovery period complete! Resuming hydration...")
    time.sleep(5)  # Extra buffer


def extract_job_metadata(soup: BeautifulSoup) -> tuple:
    """
    Extract company name, location(s), company_id from job posting HTML.
    Aggressively searches multiple selectors and fallback patterns.
    
    Returns:
        Tuple of (company_name, location, company_id, company_registry_id)
    """
    try:
        company_name = "Unknown"
        location = "Unknown"
        company_id = ""
        company_registry_id = ""
        
        # ===== COMPANY NAME EXTRACTION (Multiple fallback strategies) =====
        # Strategy 1: Extract from "CompanyName - Location" pattern (MOST COMMON)
        # Example: "ReQruitz - Helsinki , Espoo" or "A-Insinöörit Oy - Espoo , Lappeenranta"
        page_text = soup.get_text()
        dash_pattern_matches = re.search(
            r'^([A-ZÄÖÅa-zäöå0-9\s\-&\.,()]+?)\s*-\s*(?:Helsinki|Espoo|Tampere|Turku|Oulu|Jyväskylä|Kuopio|Lappeenranta|Joensuu|Pori|Lahti|Vaasa|Seinäjoki|Rovaniemi|Kouvola|Hämeenlinna|Porvoo|Raisio|Vantaa|Kauniainen|Mikkeli|Naantali|Salo|Lieto)',
            page_text,
            re.MULTILINE
        )
        if dash_pattern_matches:
            potential_company = dash_pattern_matches.group(1).strip()
            if len(potential_company) > 2 and len(potential_company) < 200:  # Sanity check
                company_name = potential_company
        
        # Strategy 2: Look for "Toiminimi" header (explicit company name section)
        if company_name == "Unknown":
            for header in soup.find_all(['h4', 'h3', 'h2', 'label']):
                if 'toiminimi' in header.get_text().lower():
                    company_elem = header.find_next(['div', 'p', 'span'])
                    if company_elem:
                        company_name = company_elem.get_text(strip=True)
                        if company_name and company_name != "Unknown":
                            break
        
        # Strategy 3: Search for company suffixes (Oy, Ab, Oyj, Ry, Plc, Ltd, GmbH)
        if company_name == "Unknown":
            company_suffixes = [' Oy ', ' Oyj', ' Ab ', ' Ry ', ' Plc', ' Ltd', ' GmbH', ' AG']
            for suffix in company_suffixes:
                matches = re.findall(r'([A-ZÄÖÅa-zäöå0-9\s\-&\.]+' + re.escape(suffix) + r')', soup.get_text())
                if matches:
                    company_name = matches[0].strip()
                    break
        
        # Strategy 4: Look in article-box metadata or header structures
        if company_name == "Unknown":
            for elem in soup.find_all(['p', 'div', 'span']):
                text = elem.get_text(strip=True)
                # Check if element contains company suffix patterns
                if any(suffix in text for suffix in [' Oy', 'Oyj', ' Ab', ' Ry', ' Plc']):
                    # Extract company name from this element
                    matches = re.findall(r'^([A-ZÄÖÅa-zäöå0-9\s\-&\.]+?(?:\s(?:Oy|Oyj|Ab|Ry|Plc|Ltd|GmbH))?)', text)
                    if matches and len(matches[0]) > 2:
                        company_name = matches[0].strip()
                        break
        
        # ===== LOCATION EXTRACTION (Multiple fallback strategies) =====
        # Strategy 1: Look for "Työpaikan sijainti" (explicit location section)
        for header in soup.find_all(['h4', 'h3', 'h2']):
            if 'sijainti' in header.get_text().lower():
                loc_elem = header.find_next(['div', 'p', 'span'])
                if loc_elem:
                    location = loc_elem.get_text(strip=True)[:200]  # Limit to 200 chars
                    if location and location != "Unknown":
                        break
        
        # Strategy 2: Search for common Finnish cities/regions
        if location == "Unknown":
            finnish_locations = [
                'Espoo', 'Helsinki', 'Tampere', 'Turku', 'Oulu', 'Jyväskylä', 'Kuopio', 
                'Lappeenranta', 'Joensuu', 'Pori', 'Lahti', 'Vaasa', 'Seinäjoki', 'Rovaniemi',
                'Kouvola', 'Hämeenlinna', 'Porvoo', 'Raisio', 'Vantaa', 'Kauniainen',
                'Mikkeli', 'Naantali', 'Salo', 'Lieto', 'Turku'
            ]
            # Look for these in order of appearance
            for location_elem in soup.find_all(['p', 'div', 'span']):
                loc_text = location_elem.get_text(strip=True)
                for city in finnish_locations:
                    if city in loc_text:
                        # Extract just the city name, not the entire element
                        # Take first 100 chars containing the city to avoid massive blocks
                        location = city
                        break
                if location != "Unknown":
                    break
        
        # Normalize location to primary Finnish city (handles multi-city, case issues, etc.)
        location = normalize_location(location)
        
        # ===== COMPANY REGISTRY ID (Y-tunnus) EXTRACTION =====
        for text_node in soup.find_all(string=re.compile(r'Y-tunnus', re.IGNORECASE)):
            parent = text_node.parent
            next_sibling = parent.find_next_sibling()
            if next_sibling:
                y_tunnus = next_sibling.get_text(strip=True)
                if re.match(r'\d+-\d+', y_tunnus):
                    company_registry_id = y_tunnus
                    break
        
        return (company_name, location, company_id, company_registry_id)
    
    except Exception as e:
        logger.debug(f"Error extracting job metadata: {e}")
        return ("Unknown", "Unknown", "", "")


def validate_title(title: str) -> bool:
    """
    Validate job title - exclude placeholders and error pages.
    
    Returns:
        True if title looks valid, False if it's a placeholder or error
    """
    if not title or len(title.strip()) < 3:
        return False
    
    invalid_titles = [
        'pending', 'sign in', 'login', '404', 'error', 'not found',
        'unknown', 'none', 'n/a', 'unavailable', 'page not found'
    ]
    
    title_lower = title.lower()
    if any(invalid in title_lower for invalid in invalid_titles):
        return False
    
    return True


def step1_index_scraping(max_pages: int = 50) -> int:
    """
    Step 1: Traverse listing pages and extract job posting URLs.
    Insert shell rows into raw_postings with extraction_status='pending'.
    
    Args:
        max_pages: Maximum pages to traverse
    
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
                # Adaptive rate limiting
                adaptive_delay()
                
                response = requests.get(
                    BASE_URL,
                    params=params,
                    timeout=10,
                    headers={"User-Agent": get_random_user_agent()}
                )
                
                if response.status_code == 200:
                    on_success()  # Success - decrease delay
                    logger.debug(f"HTTP 200 OK for page {page}")
                    soup = BeautifulSoup(response.content, "html.parser")
                    
                    # Extract job posting links
                    # Look for anchors where href starts with /tyopaikat/tyo/ or /tyopaikat/v/
                    job_urls = []
                    for link in soup.find_all("a", href=True):
                        href = link["href"]
                        if href.startswith("/tyopaikat/tyo/") or href.startswith("/tyopaikat/v/"):
                            full_url = urljoin("https://duunitori.fi", href)
                            job_urls.append(full_url)
                    
                    if not job_urls:
                        logger.warning(f"No job links found on page {page}")
                        consecutive_empty_pages += 1
                        if consecutive_empty_pages >= 3:
                            logger.info("Three consecutive empty pages. Stopping index scraping.")
                            return total_new_shells
                        break
                    
                    consecutive_empty_pages = 0
                    logger.info(f"Found {len(job_urls)} job links on page {page}")
                    
                    # Insert new jobs into database as shell rows
                    for job_url in job_urls:
                        if not url_exists(job_url):
                            job_id = hashlib.md5(job_url.encode()).hexdigest()
                            title = "Pending"  # Will be extracted in step 2
                            company = "Pending"
                            location = "Pending"
                            posted_date = "Pending"
                            
                            success = insert_raw_posting(
                                id=job_id,
                                url=job_url,
                                title=title,
                                company=company,
                                location=location,
                                posted_date=posted_date,
                                raw_html="",  # Empty, will be hydrated in step 2
                                extraction_status="pending"
                            )
                            if success:
                                total_new_shells += 1
                        else:
                            logger.debug(f"URL already exists, skipping: {job_url}")
                    
                    page += 1
                    break  # Move to next page
                
                elif response.status_code in [429, 503]:
                    on_rate_limit()  # Increase adaptive delay
                    wait_time = BACKOFF_FACTOR ** attempt
                    logger.warning(f"Rate limited (HTTP {response.status_code}). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                
                elif response.status_code >= 400:
                    logger.error(f"HTTP error {response.status_code} on page {page}")
                    return total_new_shells
            
            except requests.RequestException as e:
                logger.error(f"Request exception on attempt {attempt + 1}: {e}")
                if attempt < MAX_RETRIES - 1:
                    wait_time = BACKOFF_FACTOR ** attempt
                    time.sleep(wait_time)
        
        else:
            logger.error(f"Failed to fetch page {page} after {MAX_RETRIES} retries. Stopping.")
            break
    
    logger.info(f"Step 1 complete. Inserted {total_new_shells} new job shells.")
    return total_new_shells


def step2_detail_hydration() -> int:
    """
    Step 2: Fetch full job descriptions with SMART CYCLE-BASED COOLDOWN.
    - Calculates total cycles needed (500 jobs per cycle)
    - Hydrates 500 jobs per cycle
    - Detects IP blocking (HTTP 200 but empty responses)
    - Automatically waits 4 hours and resumes next cycle
    
    Returns:
        Count of successfully hydrated records across all cycles
    """
    logger.info("=" * 90)
    logger.info("STEP 2: DETAIL HYDRATION - Smart Cycle-Based Cooldown Strategy")
    logger.info("=" * 90)
    
    JOBS_PER_CYCLE = 500
    total_pending = count_pending_jobs()
    
    if total_pending == 0:
        logger.info("No pending records to hydrate.")
        return 0
    
    cycles_needed = calculate_cycles_needed(total_pending, JOBS_PER_CYCLE)
    logger.info(f"Total jobs to hydrate: {total_pending}")
    logger.info(f"Jobs per cycle: {JOBS_PER_CYCLE}")
    logger.info(f"Cycles needed: {cycles_needed}")
    logger.info("=" * 90)
    
    total_successfully_hydrated = 0
    
    for cycle_num in range(1, cycles_needed + 1):
        logger.info(f"\n{'='*90}")
        logger.info(f"CYCLE {cycle_num}/{cycles_needed}")
        logger.info(f"{'='*90}")
        
        # Query jobs for this cycle
        conn = get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT id, url, title FROM raw_postings
                WHERE (raw_html IS NULL OR raw_html = '')
                ORDER BY scraped_at ASC
                LIMIT ?
            """, (JOBS_PER_CYCLE,))
            
            cycle_records = cursor.fetchall()
            conn.close()
            
            if not cycle_records:
                logger.info(f"No more records to hydrate in cycle {cycle_num}.")
                break
            
            logger.info(f"Hydrating {len(cycle_records)} jobs in this cycle...")
            
            cycle_hydrated = 0
            # Progressive Cooldown State Tracking
            consecutive_failures = 0  # Track consecutive errors (403, empty response, parse errors)
            FAILURE_THRESHOLD = 30  # Trigger cooldown after N consecutive failures
            cooldown_tier = 1  # Escalation level (1=30min, 2=60min, 3=90min, ..., max 240min/4hr)
            cooldown_recoveries = 0  # Track how many times we've recovered from cooldown
            
            # IMPORTANT: Check at cycle start if we need to wait for previous recovery
            # This persists cooldown state across cycles
            if cooldown_recoveries > 0:
                logger.warning(f"[Cycle {cycle_num}] Resuming after cooldown recovery #{cooldown_recoveries}")
            
            for cycle_idx, record in enumerate(cycle_records, 1):
                job_id = record[0]
                job_url = record[1]
                
                # CRITICAL FIX: Strip "/lisaa_suosikkeihin" from favorites URLs
                # We were scraping "Add to Favorites" pages which return 403/login redirects
                # The actual job posting is at the clean URL without this suffix
                if job_url.endswith('/lisaa_suosikkeihin'):
                    job_url = job_url[:-len('/lisaa_suosikkeihin')]
                
                progress = f"[Cycle {cycle_num}/{cycles_needed}] [{cycle_idx}/{len(cycle_records)}]"
                logger.info(f"{progress} Hydrating: {job_url}")
                
                for attempt in range(MAX_RETRIES):
                    try:
                        # Adaptive rate limiting
                        adaptive_delay()
                        
                        response = requests.get(
                            job_url,
                            timeout=10,
                            headers={"User-Agent": get_random_user_agent()}
                        )
                        
                        if response.status_code == 200:
                            on_success()  # Decrease delay on success
                            logger.debug(f"HTTP 200 OK for {job_url}")
                            
                            # CHECK FOR SILENT BLOCK (HTTP 200 but empty response or login page)
                            if is_empty_response(response.text):
                                consecutive_failures += 1
                                logger.warning(f"Empty/login response detected ({consecutive_failures}/{FAILURE_THRESHOLD}). Possible IP block.")
                                
                                if consecutive_failures >= FAILURE_THRESHOLD:
                                    # Trigger progressive cooldown
                                    cooldown_minutes = min(cooldown_tier * 30, 240)  # Escalate: 30→60→90→120→...→240 min
                                    logger.error(f"COOLDOWN TRIGGERED after {consecutive_failures} consecutive failures!")
                                    logger.error(f"Escalation Tier {cooldown_tier}: Initiating {cooldown_minutes}-minute cooldown...")
                                    total_successfully_hydrated += cycle_hydrated
                                    cooldown_recoveries += 1
                                    
                                    # Check if we've exceeded recovery capacity
                                    if cooldown_recoveries > 1 and cooldown_minutes >= 240:
                                        logger.error(f"CRITICAL: System has recovered {cooldown_recoveries} times and is at max cooldown (4 hours).")
                                        logger.error(f"IP appears permanently blocked. Gracefully shutting down.")
                                        return total_successfully_hydrated
                                    
                                    # Wait for cooldown period
                                    if cycle_num < cycles_needed:
                                        logger.info(f"Cooldown for {cooldown_minutes} minutes (expires at {(datetime.now() + timedelta(minutes=cooldown_minutes)).strftime('%H:%M:%S')})...")
                                        time.sleep(cooldown_minutes * 60)
                                        cooldown_tier += 1  # Escalate to next tier
                                        consecutive_failures = 0  # Reset failure counter
                                        break  # Exit current cycle to start next one
                                    else:
                                        logger.info("All cycles complete. Hydration finished.")
                                        return total_successfully_hydrated
                                
                                break  # Skip this record, try next
                            
                            # Valid response - parse and hydrate
                            consecutive_failures = 0  # Reset counter on successful content
                            soup = BeautifulSoup(response.content, "html.parser")
                            
                            # Extract metadata
                            title_elem = soup.find("h1")
                            title = title_elem.get_text(strip=True) if title_elem else "Unknown"
                            
                            # Validate title
                            if not validate_title(title):
                                consecutive_failures += 1
                                logger.warning(f"Invalid title for {job_id}: {title} ({consecutive_failures}/{FAILURE_THRESHOLD}). Skipping.")
                                
                                if consecutive_failures >= FAILURE_THRESHOLD:
                                    # Trigger progressive cooldown
                                    cooldown_minutes = min(cooldown_tier * 30, 240)
                                    logger.error(f"COOLDOWN TRIGGERED after {consecutive_failures} consecutive parse/validation failures!")
                                    logger.error(f"Escalation Tier {cooldown_tier}: Initiating {cooldown_minutes}-minute cooldown...")
                                    total_successfully_hydrated += cycle_hydrated
                                    cooldown_recoveries += 1
                                    
                                    if cooldown_recoveries > 1 and cooldown_minutes >= 240:
                                        logger.error(f"CRITICAL: System has recovered {cooldown_recoveries} times and is at max cooldown (4 hours).")
                                        logger.error(f"Data quality appears degraded. Gracefully shutting down.")
                                        return total_successfully_hydrated
                                    
                                    if cycle_num < cycles_needed:
                                        logger.info(f"Cooldown for {cooldown_minutes} minutes (expires at {(datetime.now() + timedelta(minutes=cooldown_minutes)).strftime('%H:%M:%S')})...")
                                        time.sleep(cooldown_minutes * 60)
                                        cooldown_tier += 1
                                        consecutive_failures = 0
                                        break
                                    else:
                                        logger.info("All cycles complete. Hydration finished.")
                                        return total_successfully_hydrated
                                break
                            
                            # Extract company, location, and other metadata
                            company, location, company_id, company_registry_id = extract_job_metadata(soup)
                            
                            # Extract full description text
                            description_container = soup.find("main") or soup.find("article") or soup.find("div", class_=lambda x: x and "content" in str(x).lower())
                            
                            if description_container:
                                for tag in description_container(["script", "style"]):
                                    tag.decompose()
                                raw_html = description_container.get_text(separator=" ", strip=True)
                            else:
                                raw_html = soup.get_text(separator=" ", strip=True)
                            
                            # Update database
                            conn = get_connection()
                            cursor = conn.cursor()
                            
                            try:
                                cursor.execute("""
                                    UPDATE raw_postings
                                    SET title = ?, company = ?, location = ?, raw_html = ?
                                    WHERE id = ?
                                """, (title, company, location, raw_html, job_id))
                                
                                conn.commit()
                                logger.info(f"{progress} ✓ Hydrated | Company: {company} | Location: {location}")
                                cycle_hydrated += 1
                            
                            except Exception as e:
                                logger.error(f"Database update error: {e}")
                                conn.rollback()
                            finally:
                                conn.close()
                            
                            break  # Move to next record
                        
                        elif response.status_code == 403:
                            # HTTP 403 Forbidden - IP is being blocked!
                            consecutive_failures += 1
                            logger.warning(f"HTTP 403 Forbidden ({consecutive_failures}/{FAILURE_THRESHOLD}). IP likely blocked.")
                            
                            if consecutive_failures >= FAILURE_THRESHOLD:
                                # Trigger progressive cooldown
                                cooldown_minutes = min(cooldown_tier * 30, 240)  # Escalate: 30→60→90→120→...→240 min
                                logger.error(f"COOLDOWN TRIGGERED after {consecutive_failures} HTTP 403 errors!")
                                logger.error(f"Escalation Tier {cooldown_tier}: Initiating {cooldown_minutes}-minute cooldown...")
                                total_successfully_hydrated += cycle_hydrated
                                cooldown_recoveries += 1
                                
                                # Check if we've exceeded recovery capacity
                                if cooldown_recoveries > 1 and cooldown_minutes >= 240:
                                    logger.error(f"CRITICAL: System has recovered {cooldown_recoveries} times and is at max cooldown (4 hours).")
                                    logger.error(f"IP appears permanently blocked. Gracefully shutting down.")
                                    return total_successfully_hydrated
                                
                                # Wait for cooldown period
                                if cycle_num < cycles_needed:
                                    logger.info(f"Cooldown for {cooldown_minutes} minutes (expires at {(datetime.now() + timedelta(minutes=cooldown_minutes)).strftime('%H:%M:%S')})...")
                                    time.sleep(cooldown_minutes * 60)
                                    cooldown_tier += 1  # Escalate to next tier
                                    consecutive_failures = 0  # Reset failure counter
                                    break  # Exit current cycle to start next one
                                else:
                                    logger.info("All cycles complete. Hydration finished.")
                                    return total_successfully_hydrated
                            
                            break  # Skip this record
                        
                        elif response.status_code in [429, 503]:
                            on_rate_limit()
                            wait_time = BACKOFF_FACTOR ** attempt
                            logger.warning(f"Rate limited (HTTP {response.status_code}). Retrying in {wait_time}s...")
                            time.sleep(wait_time)
                        
                        elif response.status_code >= 400:
                            # Other 4xx/5xx errors count as failures
                            consecutive_failures += 1
                            logger.warning(f"HTTP error {response.status_code} for {job_url} ({consecutive_failures}/{FAILURE_THRESHOLD})")
                            
                            if consecutive_failures >= FAILURE_THRESHOLD:
                                # Trigger progressive cooldown
                                cooldown_minutes = min(cooldown_tier * 30, 240)
                                logger.error(f"COOLDOWN TRIGGERED after {consecutive_failures} HTTP errors!")
                                logger.error(f"Escalation Tier {cooldown_tier}: Initiating {cooldown_minutes}-minute cooldown...")
                                total_successfully_hydrated += cycle_hydrated
                                cooldown_recoveries += 1
                                
                                if cooldown_recoveries > 1 and cooldown_minutes >= 240:
                                    logger.error(f"CRITICAL: System has recovered {cooldown_recoveries} times and is at max cooldown (4 hours).")
                                    logger.error(f"IP appears permanently blocked. Gracefully shutting down.")
                                    return total_successfully_hydrated
                                
                                if cycle_num < cycles_needed:
                                    logger.info(f"Cooldown for {cooldown_minutes} minutes (expires at {(datetime.now() + timedelta(minutes=cooldown_minutes)).strftime('%H:%M:%S')})...")
                                    time.sleep(cooldown_minutes * 60)
                                    cooldown_tier += 1
                                    consecutive_failures = 0
                                    break
                                else:
                                    logger.info("All cycles complete. Hydration finished.")
                                    return total_successfully_hydrated
                            break
                    
                    except requests.RequestException as e:
                        logger.error(f"Request exception on attempt {attempt + 1}: {e}")
                        if attempt < MAX_RETRIES - 1:
                            wait_time = BACKOFF_FACTOR ** attempt
                            time.sleep(wait_time)
                
                else:
                    consecutive_failures += 1
                    logger.error(f"Failed to hydrate {job_url} after {MAX_RETRIES} retries ({consecutive_failures}/{FAILURE_THRESHOLD}).")
                    update_extraction_status(job_id, "failed")
                    
                    if consecutive_failures >= FAILURE_THRESHOLD:
                        # Trigger progressive cooldown
                        cooldown_minutes = min(cooldown_tier * 30, 240)
                        logger.error(f"COOLDOWN TRIGGERED after {consecutive_failures} max-retry failures!")
                        logger.error(f"Escalation Tier {cooldown_tier}: Initiating {cooldown_minutes}-minute cooldown...")
                        total_successfully_hydrated += cycle_hydrated
                        cooldown_recoveries += 1
                        
                        if cooldown_recoveries > 1 and cooldown_minutes >= 240:
                            logger.error(f"CRITICAL: System has recovered {cooldown_recoveries} times and is at max cooldown (4 hours).")
                            logger.error(f"Network connectivity appears severely degraded. Gracefully shutting down.")
                            return total_successfully_hydrated
                        
                        if cycle_num < cycles_needed:
                            logger.info(f"Cooldown for {cooldown_minutes} minutes (expires at {(datetime.now() + timedelta(minutes=cooldown_minutes)).strftime('%H:%M:%S')})...")
                            time.sleep(cooldown_minutes * 60)
                            cooldown_tier += 1
                            consecutive_failures = 0
                            break
                        else:
                            logger.info("All cycles complete. Hydration finished.")
                            return total_successfully_hydrated
            
            total_successfully_hydrated += cycle_hydrated
            logger.info(f"Cycle {cycle_num} complete. Hydrated: {cycle_hydrated}/{len(cycle_records)}")
            
            # Wait before next cycle (unless it's the last one)
            if cycle_num < cycles_needed:
                logger.info(f"[TEST MODE] Skipping cooldown, starting cycle {cycle_num + 1} immediately...")
                time.sleep(5)  # Minimal 5-second buffer for DB operations
        
        except Exception as e:
            logger.error(f"Error in cycle {cycle_num}: {e}")
            continue
    
    logger.info(f"\n{'='*90}")
    logger.info(f"HYDRATION COMPLETE")
    logger.info(f"Total hydrated across all cycles: {total_successfully_hydrated}")
    logger.info(f"{'='*90}\n")
    return total_successfully_hydrated


def scrape_pipeline() -> None:
    """
    Main scraping orchestrator: run both steps in sequence.
    """
    logger.info("Starting Duunitori 2-step scraping pipeline")
    logger.info(f"Rate limit strategy: {RATE_LIMIT_STRATEGY}")
    logger.info(f"  {strategy['description']}")
    logger.info(f"  Delays: {MIN_DELAY}s - {MAX_DELAY}s, Backoff: {BACKOFF_FACTOR}x, Jitter: {USE_JITTER}")
    init_database()
    
    try:
        # Step 1: Index scraping
        new_shells = step1_index_scraping()
        
        # Step 2: Detail hydration
        hydrated_count = step2_detail_hydration()
        
        logger.info("=" * 70)
        logger.info(f"Pipeline Summary: Inserted {new_shells} shells, Hydrated {hydrated_count} records")
        logger.info("=" * 70)
    
    except Exception as e:
        logger.error(f"Scraping pipeline failed: {e}", exc_info=True)
        raise


def generate_hydration_summary() -> None:
    """
    Generate comprehensive hydration and market summary report.
    Shows success/failure breakdown, top roles, skills, and tools.
    """
    logger.info("\n" + "=" * 90)
    logger.info("HYDRATION & MARKET SUMMARY REPORT")
    logger.info("=" * 90)
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # === HYDRATION METRICS ===
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN raw_html IS NOT NULL AND raw_html != '' THEN 1 ELSE 0 END) as successfully_hydrated,
                SUM(CASE WHEN extraction_status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                SUM(CASE WHEN raw_html IS NULL OR raw_html = '' THEN 1 ELSE 0 END) as pending_count
            FROM raw_postings
        """)
        total_jobs, hydrated, failed_count, pending = cursor.fetchone()
        
        hydration_pct = 100 * hydrated / total_jobs if total_jobs > 0 else 0
        failure_pct = 100 * failed_count / total_jobs if total_jobs > 0 else 0
        pending_pct = 100 * pending / total_jobs if total_jobs > 0 else 0
        
        logger.info("\n📊 HYDRATION STATISTICS:")
        logger.info(f"  Total jobs in database:      {total_jobs}")
        logger.info(f"  Successfully hydrated:       {hydrated:>6} ({hydration_pct:>5.1f}%) ✓")
        logger.info(f"  Failed to hydrate:           {failed_count:>6} ({failure_pct:>5.1f}%) ✗")
        logger.info(f"  Pending hydration:           {pending:>6} ({pending_pct:>5.1f}%) ⏳")
        
        # === EXTRACT TOP ROLES (if any extracted) ===
        cursor.execute("""
            SELECT COUNT(*) FROM structured_insights
        """)
        total_extracted = cursor.fetchone()[0]
        
        if total_extracted > 0:
            logger.info(f"\n🎯 MARKET DEMAND BY ROLE (From {total_extracted} extracted jobs):")
            
            cursor.execute("""
                SELECT 
                    standardized_role,
                    COUNT(*) as demand_count,
                    ROUND(COUNT(*) * 100.0 / ?, 1) as percentage
                FROM structured_insights
                WHERE standardized_role IS NOT NULL AND standardized_role != 'Unknown'
                GROUP BY standardized_role
                ORDER BY demand_count DESC
                LIMIT 10
            """, (total_extracted,))
            
            roles = cursor.fetchall()
            if roles:
                for rank, (role, count, pct) in enumerate(roles, 1):
                    logger.info(f"  {rank:2d}. {role:<50} {count:>4} jobs ({pct:>5.1f}%)")
            
            # === TOP SKILLS ===
            logger.info(f"\n💻 TOP IN-DEMAND SKILLS (Top 10):")
            
            cursor.execute("""
                SELECT 
                    value as skill,
                    COUNT(*) as demand_count
                FROM structured_insights, json_each(structured_insights.skills)
                WHERE skills IS NOT NULL AND skills != '[]'
                GROUP BY value
                ORDER BY demand_count DESC
                LIMIT 10
            """)
            
            skills = cursor.fetchall()
            if skills:
                for rank, (skill, count) in enumerate(skills, 1):
                    pct = 100 * count / total_extracted
                    logger.info(f"  {rank:2d}. {skill:<50} {count:>4} mentions ({pct:>5.1f}%)")
            
            # === TOP FRAMEWORKS & TOOLS ===
            logger.info(f"\n🔧 TOP IN-DEMAND FRAMEWORKS & TOOLS (Top 10):")
            
            cursor.execute("""
                SELECT 
                    value as tool,
                    COUNT(*) as demand_count
                FROM structured_insights, json_each(structured_insights.frameworks_tools)
                WHERE frameworks_tools IS NOT NULL AND frameworks_tools != '[]'
                GROUP BY value
                ORDER BY demand_count DESC
                LIMIT 10
            """)
            
            tools = cursor.fetchall()
            if tools:
                for rank, (tool, count) in enumerate(tools, 1):
                    pct = 100 * count / total_extracted
                    logger.info(f"  {rank:2d}. {tool:<50} {count:>4} mentions ({pct:>5.1f}%)")
            
            # === SENIORITY DISTRIBUTION ===
            logger.info(f"\n📈 SENIORITY LEVEL DISTRIBUTION:")
            
            cursor.execute("""
                SELECT 
                    seniority,
                    COUNT(*) as count
                FROM structured_insights
                GROUP BY seniority
                ORDER BY 
                    CASE 
                        WHEN seniority = 'Lead' THEN 1
                        WHEN seniority = 'Senior' THEN 2
                        WHEN seniority = 'Mid' THEN 3
                        WHEN seniority = 'Junior' THEN 4
                        ELSE 5
                    END
            """)
            
            seniority_levels = cursor.fetchall()
            if seniority_levels:
                for level, count in seniority_levels:
                    pct = 100 * count / total_extracted
                    logger.info(f"  {level:<20} {count:>4} jobs ({pct:>5.1f}%)")
        
        # === COMPANY DISTRIBUTION ===
        logger.info(f"\n🏢 COMPANY EXTRACTION QUALITY:")
        
        cursor.execute("""
            SELECT COUNT(*) FROM raw_postings 
            WHERE company = 'Unknown' AND raw_html IS NOT NULL AND raw_html != ''
        """)
        unknown_companies = cursor.fetchone()[0]
        unknown_pct = 100 * unknown_companies / hydrated if hydrated > 0 else 0
        
        logger.info(f"  Unknown companies:          {unknown_companies:>6} ({unknown_pct:>5.1f}%) of hydrated")
        
        # === FAILED JOBS (if any) ===
        if failed_count > 0:
            logger.info(f"\n❌ FAILED HYDRATION JOBS ({failed_count} total):")
            
            cursor.execute("""
                SELECT id, title, url FROM raw_postings
                WHERE extraction_status = 'failed'
                LIMIT 20
            """)
            
            failed_jobs = cursor.fetchall()
            for idx, (job_id, title, url) in enumerate(failed_jobs, 1):
                logger.info(f"  {idx:2d}. {job_id} | {title or 'Unknown'}")
            
            if failed_count > 20:
                logger.info(f"  ... and {failed_count - 20} more failed jobs")
        
        logger.info("=" * 90 + "\n")
        
        conn.close()
    
    except Exception as e:
        logger.error(f"Error generating hydration summary: {e}")


if __name__ == "__main__":
    scrape_pipeline()
