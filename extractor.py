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
        
        system_prompt = """Analyze this Finnish/English job posting. Categorize the overarching job profile into a clean standardized title. Explicitly distinguish between 'skills' and 'frameworks_tools':

skills: Only languages, core technologies, protocols, and major cloud platforms (e.g., Python, AWS, Java, Azure, SQL, CCNA).

frameworks_tools: Only libraries, frameworks, runtime environments, and infrastructure tooling (e.g., Terraform, Docker, React, Kubernetes, Django, Node.js).

Output strictly valid JSON conforming to the requested schema. Do not append any conversational introductory or concluding text."""
        
        user_message = f"""Extract insights from this job posting:

{job_description}

Return ONLY valid JSON with these fields:
{{
  "standardized_role": "string",
  "seniority": "Junior|Mid|Senior|Lead|Unknown",
  "skills": ["list", "of", "skills"],
  "frameworks_tools": ["list", "of", "tools"],
  "is_english": boolean
}}"""
        
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


def parse_llm_output(raw_output: str) -> Optional[StructuredInsight]:
    """
    Parse and validate LLM JSON output using Pydantic.
    
    Args:
        raw_output: JSON string from LLM
    
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


def extraction_pipeline(batch_size: int = 50) -> None:
    """
    Main extraction pipeline: process pending postings with LLM.
    
    Args:
        batch_size: Number of pending records to process per run
    """
    logger.info("Starting extraction pipeline")
    init_database()
    
    pending_records = get_pending_extractions(limit=batch_size)
    logger.info(f"Found {len(pending_records)} pending extractions")
    
    processed = 0
    successful = 0
    failed = 0
    
    for record in pending_records:
        try:
            job_id = record["id"]
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
            
            # Parse and validate
            insight = parse_llm_output(llm_output)
            
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
                is_english=insight.is_english
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
    
    logger.info(f"Extraction complete. Processed: {processed}, Successful: {successful}, Failed: {failed}")


if __name__ == "__main__":
    extraction_pipeline()
