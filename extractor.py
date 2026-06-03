"""
LLM extraction pipeline using Ollama (qwen2.5:7b) for structured job insight extraction.
Features: HTML cleaning, Pydantic validation, fault tolerance, transaction-based writes.
"""
from bs4 import BeautifulSoup
from pydantic import BaseModel, ValidationError, field_validator
from typing import Literal, Optional
import json
import re

try:
    from ollama import Client
except ImportError:
    Client = None

from database import (
    init_database,
    get_connection,
    get_pending_extractions,
    insert_structured_insight,
    insert_failed_extraction
)
from logger import logger


# Pydantic schema for structured insights
class StructuredInsight(BaseModel):
    """Schema for job posting insights extracted by LLM"""
    standardized_role: str
    seniority: Literal["Junior", "Mid", "Senior", "Lead", "Unknown"]
    skills: list[str]
    frameworks_tools: list[str]
    is_english: bool
    finnish_language_required: bool
    
    @field_validator("standardized_role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if not v or not isinstance(v, str) or len(v.strip()) == 0:
            raise ValueError("standardized_role cannot be empty")
        return v.strip()
    
    @field_validator("skills", "frameworks_tools")
    @classmethod
    def validate_lists(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("Must be a list")
        return [item.strip() for item in v if item.strip()]


def clean_html(raw_html: str) -> str:
    """
    Clean HTML content: remove scripts, styles, and extract pure text.
    
    Args:
        raw_html: Raw HTML string
    
    Returns:
        Clean, human-readable text
    """
    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text
        text = soup.get_text(separator=" ", strip=True)
        
        # Clean up whitespace
        text = re.sub(r"\s+", " ", text)
        
        return text
    
    except Exception as e:
        logger.error(f"HTML cleaning error: {e}")
        return raw_html


def extract_with_ollama(job_description: str) -> Optional[str]:
    """
    Call Ollama API with qwen2.5:7b model to extract structured insights.
    
    Args:
        job_description: Clean job description text
    
    Returns:
        JSON string response from LLM or None if failed
    """
    if Client is None:
        logger.error("Ollama client not available. Install ollama package.")
        return None
    
    try:
        client = Client(host="http://localhost:11434")
        
        # Truncate job description to first 2000 chars for efficiency
        truncated_desc = job_description[:2000]
        
        system_prompt = """Extract skills, tools, and language requirements from job postings. Return ONLY valid JSON.
Skills: Languages, protocols, platforms (Python, Java, SQL, AWS).
Tools: Frameworks, libraries, runtimes (Docker, React, Kubernetes, Node.js).
Finnish Language: Set to TRUE ONLY if the job posting EXPLICITLY states that Finnish language skills are required (look for phrases like "suomen kielen taito", "suomea vaaditaan", "Finnish language required"). Ignore HTML metadata like "Julkaistu" (published). Most postings are bilingual - set to FALSE unless explicitly required.
SENIORITY: Choose EXACTLY ONE level that best fits the job. If multiple apply, pick the median/most common one.

EXAMPLE:
Input: "We need a Python developer with AWS and Docker experience."
Output: {"standardized_role": "Software Developer", "seniority": "Mid", "skills": ["Python", "AWS"], "frameworks_tools": ["Docker"], "is_english": true, "finnish_language_required": false}"""
        
        user_message = f"""Extract from this job posting:

{truncated_desc}

Return ONLY this JSON (list all mentioned skills and tools; seniority must be EXACTLY ONE of: Junior, Mid, Senior, Lead, Unknown; set finnish_language_required to true if the posting explicitly requires Finnish language fluency):
{{"standardized_role": "string", "seniority": "Mid", "skills": ["skill1", "skill2"], "frameworks_tools": ["tool1", "tool2"], "is_english": true, "finnish_language_required": false}}"""
        
        response = client.generate(
            model="qwen2.5:3b",
            prompt=user_message,
            system=system_prompt,
            stream=False,
            format="json"
        )
        
        json_output = response.get("response", "").strip()
        logger.debug(f"LLM response: {json_output[:200]}...")
        
        return json_output
    
    except Exception as e:
        logger.error(f"Ollama API error: {e}")
        return None


def detect_explicit_finnish_requirement(html: str) -> bool:
    """
    Detect if job posting EXPLICITLY requires Finnish language.
    Look for specific patterns like "suomen kielen taito" or "suomea vaaditaan".
    
    Args:
        html: Raw job posting HTML
    
    Returns:
        True if explicit Finnish language requirement found, False otherwise
    """
    # Explicit Finnish language requirement patterns
    explicit_patterns = [
        r'suomen\s+kiel', # "suomen kielen" (Finnish language)
        r'suomea\s+(vaaditaan|required|osattava|hallittava)', # "suomea vaaditaan" (Finnish required)
        r'suomen\s+kielen\s+(taito|osaaminen|vaatimus)', # "suomen kielen taito/osaaminen" (Finnish language skill/requirement)
        r'fluent.*suomi', # "fluent in Finnish"
        r'suomi.*fluent',
    ]
    
    html_lower = html.lower()
    
    for pattern in explicit_patterns:
        if re.search(pattern, html_lower):
            return True
    
    # If LLM said True but no explicit pattern found, override to False
    return False


def parse_llm_output(raw_output: str, original_html: str = None) -> Optional[StructuredInsight]:
    """
    Parse and validate LLM JSON output using Pydantic.
    Apply post-processing to fix Finnish language detection.
    
    Args:
        raw_output: JSON string from LLM
        original_html: Original job posting HTML for verification
    
    Returns:
        StructuredInsight object or None if validation fails
    """
    try:
        # Try to extract JSON from the response
        json_match = re.search(r"\{.*\}", raw_output, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in response")
        
        json_str = json_match.group(0)
        data = json.loads(json_str)
        
        # CRITICAL FIX: Override LLM's Finnish detection with explicit keyword matching
        # The LLM was picking up website UI text (e.g., "Julkaistu" = "Published")
        # instead of actual job requirements
        if original_html and data.get('finnish_language_required'):
            actual_requirement = detect_explicit_finnish_requirement(original_html)
            data['finnish_language_required'] = actual_requirement
            if not actual_requirement:
                logger.debug(f"Overriding LLM's Finnish requirement detection to FALSE (no explicit pattern found)")
        
        # Validate with Pydantic
        insight = StructuredInsight(**data)
        return insight
    
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error: {e}")
        return None
    except ValidationError as e:
        logger.warning(f"Pydantic validation error: {e}")
        return None
    except Exception as e:
        logger.warning(f"Parse error: {e}")
        return None


def extraction_pipeline(batch_size: int = None) -> None:
    """
    Main extraction pipeline: process ALL pending postings with LLM.
    
    Args:
        batch_size: Number of pending records to process per run (None = process all)
    """
    logger.info("Starting extraction pipeline")
    init_database()
    
    # Verify database has hydrated jobs BEFORE starting extraction
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check total hydrated jobs
    cursor.execute("SELECT COUNT(*) FROM raw_postings WHERE extraction_status IN ('pending', 'done')")
    total_hydrated = cursor.fetchone()[0]
    
    # Get count of pending records
    cursor.execute("SELECT COUNT(*) FROM raw_postings WHERE extraction_status = 'pending'")
    pending_count = cursor.fetchone()[0]
    
    conn.close()
    
    # SAFETY: Warn if no data exists
    if total_hydrated == 0:
        logger.error("⚠️  CRITICAL: Database has 0 hydrated jobs. Cannot run extraction.")
        logger.error("   Run 'python main.py --scrape' first to hydrate jobs.")
        raise RuntimeError("Extraction requires hydrated job data. Database is empty.")
    
    if pending_count == 0:
        logger.warning("⚠️  No pending extractions found. All jobs already processed or no jobs hydrated.")
        logger.warning(f"   Total hydrated: {total_hydrated} | Pending: {pending_count}")
        return
    
    # Set batch size if not specified
    if batch_size is None:
        batch_size = pending_count
        logger.info(f"Processing ALL pending records: {batch_size} total")
    
    pending_records = get_pending_extractions(limit=batch_size)
    logger.info(f"Found {len(pending_records)} pending extractions")
    
    processed = 0
    successful = 0
    failed = 0
    skipped = 0
    
    for record in pending_records:
        try:
            job_id = record["id"]
            
            # SMART CHECK: Skip if already extracted
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM structured_insights WHERE id = ?", (job_id,))
            if cursor.fetchone()[0] > 0:
                logger.info(f"Skipping already-extracted: {job_id}")
                skipped += 1
                processed += 1
                conn.close()
                continue
            conn.close()
            
            logger.info(f"Processing: {job_id}")
            
            # Clean HTML
            clean_text = clean_html(record["raw_html"])
            
            # Call LLM
            llm_output = extract_with_ollama(clean_text)
            
            if not llm_output:
                insert_failed_extraction(
                    id=job_id,
                    raw_output="",
                    error_message="LLM API call failed"
                )
                failed += 1
                processed += 1
                continue
            
            # Parse and validate (pass original HTML for Finnish detection verification)
            insight = parse_llm_output(llm_output, original_html=record["raw_html"])
            
            if not insight:
                insert_failed_extraction(
                    id=job_id,
                    raw_output=llm_output,
                    error_message="Pydantic validation failed"
                )
                failed += 1
                processed += 1
                continue
            
            # Insert structured insight
            skills_json = json.dumps(insight.skills)
            frameworks_json = json.dumps(insight.frameworks_tools)
            
            success = insert_structured_insight(
                id=job_id,
                standardized_role=insight.standardized_role,
                seniority=insight.seniority,
                skills=skills_json,
                frameworks_tools=frameworks_json,
                is_english=insight.is_english,
                finnish_language_required=insight.finnish_language_required
            )
            
            if success:
                successful += 1
            else:
                failed += 1
            
            processed += 1
        
        except Exception as e:
            logger.error(f"Unexpected error processing {record.get('id')}: {e}")
            failed += 1
            processed += 1
    
    logger.info(f"Extraction complete. Processed: {processed}, Successful: {successful}, Failed: {failed}, Skipped: {skipped}")


if __name__ == "__main__":
    extraction_pipeline()
