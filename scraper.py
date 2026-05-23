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

# Duunitori IT sector landing page
BASE_URL = "https://duunitori.fi/tyopaikat/ala/tieto-tietoliikennetekniikka"

# Resilience parameters
MIN_DELAY = 2
MAX_DELAY = 5
MAX_RETRIES = 3
BACKOFF_FACTOR = 2

# Rate limit tracking
rate_limit_delay = MIN_DELAY  # Adaptive delay
last_request_time = 0


def adaptive_delay():
    """
    Apply adaptive rate limiting based on consecutive requests.
    Increases delay if rate limited, decreases if requests are successful.
    """
    global rate_limit_delay, last_request_time
    
    # Ensure minimum time between requests
    elapsed = time.time() - last_request_time
    if elapsed < rate_limit_delay:
        time.sleep(rate_limit_delay - elapsed)
    
    last_request_time = time.time()


def on_rate_limit():
    """Call when rate limited to increase delay"""
    global rate_limit_delay
    rate_limit_delay = min(rate_limit_delay * BACKOFF_FACTOR, 30)  # Cap at 30s
    logger.warning(f"Rate limit detected. Increasing delay to {rate_limit_delay:.1f}s")


def on_success():
    """Call on successful request to gradually decrease delay"""
    global rate_limit_delay
    rate_limit_delay = max(rate_limit_delay * 0.95, MIN_DELAY)  # Slowly decrease


def extract_job_metadata(soup: BeautifulSoup) -> tuple:
    """
    Extract company name, location(s), company_id from job posting HTML.
    
    Returns:
        Tuple of (company_name, location, company_id, company_registry_id)
    """
    try:
        company_name = "Unknown"
        location = "Unknown"
        company_id = ""
        company_registry_id = ""
        
        # Find company name from "Toiminimi" section
        for header in soup.find_all(['h4', 'h3', 'h2', 'label']):
            if 'toiminimi' in header.get_text().lower():
                # Next element should contain company name
                company_elem = header.find_next(['div', 'p', 'span'])
                if company_elem:
                    company_name = company_elem.get_text(strip=True)
                    break
        
        # Find location from "Työpaikan sijainti" section
        for header in soup.find_all(['h4', 'h3', 'h2']):
            if 'sijainti' in header.get_text().lower():
                # Next element should contain location
                loc_elem = header.find_next(['div', 'p', 'span'])
                if loc_elem:
                    location = loc_elem.get_text(strip=True)
                    break
        
        # If location extraction failed, try common Finnish cities
        if location == "Unknown":
            finnish_cities = ['Espoo', 'Helsinki', 'Tampere', 'Turku', 'Oulu', 'Jyväskylä', 'Kuopio', 
                            'Lappeenranta', 'Joensuu', 'Pori', 'Lahti', 'Vaasa', 'Seinäjoki']
            for city in finnish_cities:
                if city in soup.get_text():
                    location = city
                    break
        
        # Extract company registry ID (Y-tunnus) - usually shown on the page
        for text_node in soup.find_all(string=re.compile(r'Y-tunnus')):
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
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
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
    Step 2: Fetch full job descriptions for rows where raw_html is empty.
    Update raw_postings with clean text content.
    
    Returns:
        Count of successfully hydrated records
    """
    logger.info("=" * 70)
    logger.info("STEP 2: DETAIL HYDRATION - Fetching full job descriptions")
    logger.info("=" * 70)
    
    # Query for rows with empty raw_html
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, url, title FROM raw_postings
            WHERE raw_html IS NULL OR raw_html = ''
            ORDER BY scraped_at ASC
        """)
        
        pending_records = cursor.fetchall()
        conn.close()
        
        if not pending_records:
            logger.info("No pending records to hydrate.")
            return 0
        
        logger.info(f"Found {len(pending_records)} records pending hydration.")
        
        successfully_hydrated = 0
        
        for idx, record in enumerate(pending_records, 1):
            job_id = record[0]
            job_url = record[1]
            
            logger.info(f"[{idx}/{len(pending_records)}] Hydrating: {job_url}")
            
            for attempt in range(MAX_RETRIES):
                try:
                    # Adaptive rate limiting
                    adaptive_delay()
                    
                    response = requests.get(
                        job_url,
                        timeout=10,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    )
                    
                    if response.status_code == 200:
                        on_success()  # Success - decrease delay
                        logger.debug(f"HTTP 200 OK for {job_url}")
                        soup = BeautifulSoup(response.content, "html.parser")
                        
                        # Extract metadata
                        title_elem = soup.find("h1")
                        title = title_elem.get_text(strip=True) if title_elem else "Unknown"
                        
                        # Validate title (skip if it's a placeholder or error page)
                        if not validate_title(title):
                            logger.warning(f"Invalid title for {job_id}: {title}. Skipping.")
                            break
                        
                        # Extract company, location, and other metadata
                        company, location, company_id, company_registry_id = extract_job_metadata(soup)
                        
                        # Extract full description text
                        description_container = soup.find("main") or soup.find("article") or soup.find("div", class_=lambda x: x and "content" in str(x).lower())
                        
                        if description_container:
                            # Clean text: remove scripts, styles, extract prose
                            for tag in description_container(["script", "style"]):
                                tag.decompose()
                            
                            raw_html = description_container.get_text(separator=" ", strip=True)
                        else:
                            raw_html = soup.get_text(separator=" ", strip=True)
                        
                        # Update the row with hydrated data
                        conn = get_connection()
                        cursor = conn.cursor()
                        
                        try:
                            cursor.execute("""
                                UPDATE raw_postings
                                SET title = ?, company = ?, location = ?, raw_html = ?
                                WHERE id = ?
                            """, (title, company, location, raw_html, job_id))
                            
                            conn.commit()
                            logger.info(f"Successfully hydrated: {job_id} | Company: {company} | Location: {location}")
                            # Keep status as 'pending' - will be marked 'done' by extraction pipeline
                            successfully_hydrated += 1
                        
                        except Exception as e:
                            logger.error(f"Database update error: {e}")
                            conn.rollback()
                        finally:
                            conn.close()
                        
                        break  # Move to next record
                    
                    elif response.status_code in [429, 503]:
                        on_rate_limit()  # Increase adaptive delay
                        wait_time = BACKOFF_FACTOR ** attempt
                        logger.warning(f"Rate limited (HTTP {response.status_code}). Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    
                    elif response.status_code >= 400:
                        logger.warning(f"HTTP error {response.status_code} for {job_url}")
                        break
                
                except requests.RequestException as e:
                    logger.error(f"Request exception on attempt {attempt + 1}: {e}")
                    if attempt < MAX_RETRIES - 1:
                        wait_time = BACKOFF_FACTOR ** attempt
                        time.sleep(wait_time)
            
            else:
                logger.error(f"Failed to hydrate {job_url} after {MAX_RETRIES} retries. Marking as failed.")
                # Mark this record as failed so we don't retry it on next run
                update_extraction_status(job_id, "failed")
    
    except Exception as e:
        logger.error(f"Error in detail hydration: {e}")
    finally:
        if conn:
            conn.close()
    
    logger.info(f"Step 2 complete. Successfully hydrated {successfully_hydrated} records.")
    return successfully_hydrated


def scrape_pipeline() -> None:
    """
    Main scraping orchestrator: run both steps in sequence.
    """
    logger.info("Starting Duunitori 2-step scraping pipeline")
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


if __name__ == "__main__":
    scrape_pipeline()
