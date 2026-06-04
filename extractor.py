"""
LLM extraction pipeline using Ollama (qwen2.5:3b) for structured job insight extraction.
Features: role taxonomy enforcement, content-based deduplication, Pydantic validation,
          fault tolerance, transaction-based writes.
"""
import hashlib
import json
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, ValidationError, field_validator

try:
    from ollama import Client
except ImportError:
    Client = None

from database import (
    init_database,
    get_connection,
    get_pending_extractions,
    insert_structured_insight,
    insert_failed_extraction,
)
from logger import logger


# Canonical role taxonomy — enforced via prompt and validator
ROLE_TAXONOMY = [
    "Software Developer",
    "Frontend Developer",
    "Backend Developer",
    "Full Stack Developer",
    "Mobile Developer",
    "Data Engineer",
    "Data Scientist / ML Engineer",
    "DevOps / Cloud Engineer",
    "QA / Test Engineer",
    "Security Engineer",
    "Network / Systems Engineer",
    "IT Consultant / Business Analyst",
    "Solution Architect",
    "IT Support / Helpdesk",
    "Other",
]

# Common aliases the LLM might produce → canonical taxonomy entry
_ROLE_ALIASES = {
    "software engineer":              "Software Developer",
    "software developer":             "Software Developer",
    "python developer":               "Software Developer",
    "java developer":                 "Software Developer",
    "backend engineer":               "Backend Developer",
    "frontend engineer":              "Frontend Developer",
    "full stack engineer":            "Full Stack Developer",
    "fullstack developer":            "Full Stack Developer",
    "fullstack engineer":             "Full Stack Developer",
    "data scientist":                 "Data Scientist / ML Engineer",
    "ml engineer":                    "Data Scientist / ML Engineer",
    "machine learning engineer":      "Data Scientist / ML Engineer",
    "devops engineer":                "DevOps / Cloud Engineer",
    "cloud engineer":                 "DevOps / Cloud Engineer",
    "site reliability engineer":      "DevOps / Cloud Engineer",
    "sre":                            "DevOps / Cloud Engineer",
    "platform engineer":              "DevOps / Cloud Engineer",
    "infrastructure engineer":        "DevOps / Cloud Engineer",
    "test engineer":                  "QA / Test Engineer",
    "qa engineer":                    "QA / Test Engineer",
    "quality assurance engineer":     "QA / Test Engineer",
    "security analyst":               "Security Engineer",
    "cybersecurity engineer":         "Security Engineer",
    "network engineer":               "Network / Systems Engineer",
    "systems engineer":               "Network / Systems Engineer",
    "systems administrator":          "Network / Systems Engineer",
    "business analyst":               "IT Consultant / Business Analyst",
    "it consultant":                  "IT Consultant / Business Analyst",
    "enterprise architect":           "Solution Architect",
    "technical architect":            "Solution Architect",
    "it support":                     "IT Support / Helpdesk",
    "helpdesk":                       "IT Support / Helpdesk",
}

_VALID_ROLES = set(ROLE_TAXONOMY)
_VALID_EXPERIENCE = {"0-2", "2-5", "5-10", "10+", "Not specified"}
_VALID_REMOTE = {"Remote", "Hybrid", "On-site", "Not specified"}


class StructuredInsight(BaseModel):
    standardized_role: str
    seniority: str
    skills: list[str]
    frameworks_tools: list[str]
    is_english: bool
    finnish_language_required: bool
    years_experience_required: str
    remote_work_available: str

    @field_validator("standardized_role")
    @classmethod
    def normalize_role(cls, v: str) -> str:
        if v in _VALID_ROLES:
            return v
        mapped = _ROLE_ALIASES.get(v.lower().strip())
        return mapped if mapped else "Other"

    @field_validator("seniority")
    @classmethod
    def validate_seniority(cls, v: str) -> str:
        valid = {"Junior", "Mid", "Senior", "Lead", "Unknown"}
        return v if v in valid else "Unknown"

    @field_validator("years_experience_required")
    @classmethod
    def validate_experience(cls, v: str) -> str:
        return v if v in _VALID_EXPERIENCE else "Not specified"

    @field_validator("remote_work_available")
    @classmethod
    def validate_remote(cls, v: str) -> str:
        return v if v in _VALID_REMOTE else "Not specified"

    @field_validator("skills", "frameworks_tools")
    @classmethod
    def clean_lists(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("Must be a list")
        return [item.strip() for item in v if item.strip()]


def clean_html(raw_html: str) -> str:
    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return re.sub(r"\s+", " ", text)
    except Exception as e:
        logger.error(f"HTML cleaning error: {e}")
        return raw_html


def extract_with_ollama(job_description: str) -> Optional[str]:
    if Client is None:
        logger.error("Ollama client not available. Install ollama package.")
        return None

    try:
        client = Client(host="http://localhost:11434")
        truncated = job_description[:2000]

        role_list = "\n".join(f'  "{r}"' for r in ROLE_TAXONOMY)

        system_prompt = f"""Extract structured data from IT job postings. Return ONLY valid JSON.

ROLE — choose the single best match from this exact list:
{role_list}

SENIORITY — "Junior" (0-2 yrs implied), "Mid" (2-5 yrs), "Senior" (5+ yrs), "Lead" (team lead/principal), "Unknown"
EXPERIENCE — years explicitly stated in posting: "0-2", "2-5", "5-10", "10+", or "Not specified"
REMOTE — work arrangement: "Remote", "Hybrid", "On-site", or "Not specified"
SKILLS — languages, protocols, platforms (Python, Java, SQL, AWS, Azure, Linux)
TOOLS — frameworks, libraries, runtimes (Docker, React, Kubernetes, Node.js, Terraform)
FINNISH — true ONLY if posting explicitly requires Finnish fluency (e.g. "suomen kielen taito", "Finnish required", "äidinkielenä suomi")"""

        user_message = f"""Extract from this job posting:

{truncated}

Return ONLY this JSON (no other text):
{{"standardized_role": "Software Developer", "seniority": "Mid", "skills": ["Python", "AWS"], "frameworks_tools": ["Docker"], "is_english": true, "finnish_language_required": false, "years_experience_required": "2-5", "remote_work_available": "Hybrid"}}"""

        response = client.generate(
            model="qwen2.5:3b",
            prompt=user_message,
            system=system_prompt,
            stream=False,
            format="json",
        )

        json_output = response.get("response", "").strip()
        logger.debug(f"LLM response: {json_output[:200]}...")
        return json_output

    except Exception as e:
        logger.error(f"Ollama API error: {e}")
        return None


def parse_llm_output(raw_output: str) -> Optional[StructuredInsight]:
    try:
        json_match = re.search(r"\{.*\}", raw_output, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in response")
        data = json.loads(json_match.group(0))
        return StructuredInsight(**data)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error: {e}")
        return None
    except ValidationError as e:
        logger.warning(f"Pydantic validation error: {e}")
        return None
    except Exception as e:
        logger.warning(f"Parse error: {e}")
        return None


def _copy_existing_extraction(job_id: str, source_id: str) -> bool:
    """Copy a structured_insight row from source_id to job_id (content dedup)."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO structured_insights
                (id, standardized_role, seniority, skills, frameworks_tools, is_english,
                 finnish_language_required, years_experience_required, remote_work_available, extracted_at)
            SELECT ?, standardized_role, seniority, skills, frameworks_tools, is_english,
                   finnish_language_required, years_experience_required, remote_work_available, ?
            FROM structured_insights WHERE id = ?
        """, (job_id, datetime.now(), source_id))
        cursor.execute("UPDATE raw_postings SET extraction_status = 'done' WHERE id = ?", (job_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error copying extraction: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def extraction_pipeline(batch_size: int = None) -> None:
    """
    Main extraction pipeline. Processes all pending postings.
    Skips records whose content hash already has an extraction result (dedup).
    """
    logger.info("Starting extraction pipeline")
    init_database()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM raw_postings WHERE extraction_status IN ('pending', 'done')")
    total_hydrated = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM raw_postings WHERE extraction_status = 'pending'")
    pending_count = cursor.fetchone()[0]
    conn.close()

    if total_hydrated == 0:
        logger.error("Database has 0 hydrated jobs. Run --scrape first.")
        raise RuntimeError("Extraction requires hydrated job data. Database is empty.")

    if pending_count == 0:
        logger.warning(f"No pending extractions. Total hydrated: {total_hydrated}")
        return

    if batch_size is None:
        batch_size = pending_count
        logger.info(f"Processing all {batch_size} pending records")

    pending_records = get_pending_extractions(limit=batch_size)
    logger.info(f"Fetched {len(pending_records)} pending records")

    processed = successful = failed = skipped = deduped = 0

    for record in pending_records:
        try:
            job_id = record["id"]

            # Skip if already extracted (idempotency)
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM structured_insights WHERE id = ?", (job_id,))
            already_done = cursor.fetchone()[0] > 0
            conn.close()
            if already_done:
                skipped += 1
                processed += 1
                continue

            # Content-based deduplication: if another record with the same raw_html
            # was already extracted, copy its result instead of calling the LLM again.
            raw_html = record.get("raw_html") or ""
            content_hash = record.get("content_hash") or hashlib.md5(raw_html.encode()).hexdigest()

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT si.id
                FROM structured_insights si
                JOIN raw_postings rp ON si.id = rp.id
                WHERE rp.content_hash = ? AND rp.id != ?
                LIMIT 1
            """, (content_hash, job_id))
            existing = cursor.fetchone()
            conn.close()

            if existing:
                source_id = existing[0]
                if _copy_existing_extraction(job_id, source_id):
                    logger.info(f"Deduped {job_id} → copied from {source_id}")
                    deduped += 1
                    successful += 1
                else:
                    failed += 1
                processed += 1
                continue

            logger.info(f"Extracting: {job_id}")
            clean_text = clean_html(raw_html)
            llm_output = extract_with_ollama(clean_text)

            if not llm_output:
                insert_failed_extraction(job_id, "", "LLM API call failed")
                failed += 1
                processed += 1
                continue

            insight = parse_llm_output(llm_output)
            if not insight:
                insert_failed_extraction(job_id, llm_output, "Pydantic validation failed")
                failed += 1
                processed += 1
                continue

            success = insert_structured_insight(
                id=job_id,
                standardized_role=insight.standardized_role,
                seniority=insight.seniority,
                skills=json.dumps(insight.skills),
                frameworks_tools=json.dumps(insight.frameworks_tools),
                is_english=insight.is_english,
                finnish_language_required=insight.finnish_language_required,
                years_experience_required=insight.years_experience_required,
                remote_work_available=insight.remote_work_available,
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

    logger.info(
        f"Extraction complete — processed: {processed}, "
        f"successful: {successful} (deduped: {deduped}), "
        f"failed: {failed}, skipped: {skipped}"
    )


if __name__ == "__main__":
    extraction_pipeline()
