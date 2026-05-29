"""
SQLite database configuration and initialization for the Duunitori pipeline.
Contains three tables: raw_postings, structured_insights, and failed_extractions.
"""
import sqlite3
from pathlib import Path
from datetime import datetime
from logger import logger

DB_FILE = Path("duunitori_pipeline.db")


def get_connection() -> sqlite3.Connection:
    """
    Get a connection to the SQLite database.
    
    Returns:
        sqlite3.Connection object
    """
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    """
    Initialize the SQLite database with required tables if they don't exist.
    Creates: raw_postings, structured_insights, failed_extractions
    Applies migrations for new columns if they don't exist.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Table 1: raw_postings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_postings (
                id TEXT PRIMARY KEY,
                url TEXT UNIQUE NOT NULL,
                title TEXT,
                company TEXT,
                location TEXT,
                posted_date TEXT,
                raw_html TEXT,
                scraped_at TIMESTAMP,
                extraction_status TEXT DEFAULT 'pending' CHECK(extraction_status IN ('pending', 'done', 'failed'))
            )
        """)
        
        # Table 2: structured_insights
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS structured_insights (
                id TEXT PRIMARY KEY,
                standardized_role TEXT,
                seniority TEXT,
                skills TEXT,
                frameworks_tools TEXT,
                is_english BOOLEAN,
                finnish_language_required BOOLEAN,
                extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id) REFERENCES raw_postings(id) ON DELETE CASCADE
            )
        """)
        
        # Table 3: failed_extractions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS failed_extractions (
                id TEXT PRIMARY KEY,
                raw_output TEXT,
                error_message TEXT,
                failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id) REFERENCES raw_postings(id) ON DELETE CASCADE
            )
        """)
        
        # MIGRATION: Add finnish_language_required column if it doesn't exist
        cursor.execute("PRAGMA table_info(structured_insights)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'finnish_language_required' not in columns:
            logger.info("Migrating structured_insights: Adding finnish_language_required column...")
            cursor.execute("""
                ALTER TABLE structured_insights
                ADD COLUMN finnish_language_required BOOLEAN DEFAULT NULL
            """)
            logger.info("Migration completed successfully")
        
        conn.commit()
        logger.info("Database initialized successfully")
        
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def url_exists(url: str) -> bool:
    """
    Check if a URL already exists in the raw_postings table.
    
    Args:
        url: The job posting URL to check
    
    Returns:
        True if URL exists, False otherwise
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT 1 FROM raw_postings WHERE url = ?", (url,))
        exists = cursor.fetchone() is not None
        return exists
    finally:
        conn.close()


def insert_raw_posting(
    id: str,
    url: str,
    title: str,
    company: str,
    location: str,
    posted_date: str,
    raw_html: str,
    extraction_status: str = "pending"
) -> bool:
    """
    Insert a raw job posting into the database.
    
    Args:
        id: Unique job ID (can be derived from URL hash or Duunitori ID)
        url: Job posting URL
        title: Job title
        company: Company name
        location: Job location
        posted_date: Date posted
        raw_html: Raw HTML content of the job description
        extraction_status: Extraction status (default: 'pending')
    
    Returns:
        True if successful, False otherwise
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO raw_postings 
            (id, url, title, company, location, posted_date, raw_html, scraped_at, extraction_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (id, url, title, company, location, posted_date, raw_html, datetime.now(), extraction_status))
        
        conn.commit()
        logger.info(f"Inserted raw posting: {id} - {title}")
        return True
        
    except sqlite3.IntegrityError as e:
        logger.warning(f"Duplicate entry or constraint violation: {e}")
        return False
    except sqlite3.Error as e:
        logger.error(f"Error inserting raw posting: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_pending_extractions(limit: int = 50) -> list[dict]:
    """
    Get pending job postings that need LLM extraction.
    
    Args:
        limit: Maximum number of records to fetch
    
    Returns:
        List of pending raw_postings as dictionaries
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, url, title, company, location, raw_html
            FROM raw_postings
            WHERE extraction_status = 'pending'
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
        
    except sqlite3.Error as e:
        logger.error(f"Error fetching pending extractions: {e}")
        return []
    finally:
        conn.close()


def insert_structured_insight(
    id: str,
    standardized_role: str,
    seniority: str,
    skills: str,
    frameworks_tools: str,
    is_english: bool = None,
    finnish_language_required: bool = None
) -> bool:
    """
    Insert a structured insight into the database.
    
    Args:
        id: Job posting ID
        standardized_role: Standardized job role title
        seniority: Seniority level (Junior, Mid, Senior, Lead, Unknown)
        skills: JSON-serialized list of skills
        frameworks_tools: JSON-serialized list of frameworks/tools
        is_english: Boolean indicating if job posting is in English
        finnish_language_required: Boolean indicating if Finnish language is required
    
    Returns:
        True if successful, False otherwise
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO structured_insights
            (id, standardized_role, seniority, skills, frameworks_tools, is_english, finnish_language_required, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (id, standardized_role, seniority, skills, frameworks_tools, is_english, finnish_language_required, datetime.now()))
        
        # Update extraction status in raw_postings
        cursor.execute("""
            UPDATE raw_postings
            SET extraction_status = 'done'
            WHERE id = ?
        """, (id,))
        
        conn.commit()
        logger.info(f"Inserted structured insight for: {id}")
        return True
        
    except sqlite3.Error as e:
        logger.error(f"Error inserting structured insight: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def insert_failed_extraction(
    id: str,
    raw_output: str,
    error_message: str
) -> bool:
    """
    Insert a failed extraction record into the database.
    
    Args:
        id: Job posting ID
        raw_output: The malformed LLM output
        error_message: Error message describing the failure
    
    Returns:
        True if successful, False otherwise
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO failed_extractions
            (id, raw_output, error_message, failed_at)
            VALUES (?, ?, ?, ?)
        """, (id, raw_output, error_message, datetime.now()))
        
        # Update extraction status in raw_postings
        cursor.execute("""
            UPDATE raw_postings
            SET extraction_status = 'failed'
            WHERE id = ?
        """, (id,))
        
        conn.commit()
        logger.error(f"Recorded failed extraction for: {id} - {error_message}")
        return True
        
    except sqlite3.Error as e:
        logger.error(f"Error inserting failed extraction: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def update_extraction_status(id: str, status: str) -> bool:
    """
    Update extraction_status for a record in raw_postings.
    
    Args:
        id: Job posting ID
        status: New extraction status (pending, done, failed)
    
    Returns:
        True if successful, False otherwise
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE raw_postings
            SET extraction_status = ?
            WHERE id = ?
        """, (status, id))
        
        conn.commit()
        logger.info(f"Updated extraction_status to '{status}' for: {id}")
        return True
        
    except sqlite3.Error as e:
        logger.error(f"Error updating extraction_status: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
