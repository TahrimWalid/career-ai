"""
Analytics module for market insights extraction using SQLite aggregates and JSON functions.
Generates reports on skills demand, frameworks, seniority distribution, geographic patterns,
and data quality metrics including duplicate detection and language requirements.
"""
import hashlib
import sqlite3
from database import get_connection
from logger import logger


def print_header(title: str) -> None:
    """Print a formatted section header"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def top_skills(limit: int = 10) -> None:
    """
    Get and print the top most in-demand skills using json_each() aggregation.
    
    Args:
        limit: Number of top skills to display
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        print_header("TOP 10 MOST IN-DEMAND SKILLS")
        
        query = f"""
        SELECT
            value as skill,
            COUNT(*) as demand_count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM structured_insights WHERE skills IS NOT NULL), 2) as percentage
        FROM structured_insights, json_each(structured_insights.skills)
        WHERE skills IS NOT NULL AND skills != '[]'
          AND value NOT IN ('Finnish', 'English', 'Swedish', 'Norwegian', 'Danish',
                            'German', 'French', 'Spanish', 'Russian')
        GROUP BY value
        ORDER BY demand_count DESC
        LIMIT ?
        """
        
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        
        if not rows:
            print("No skill data available.\n")
            return
        
        print(f"{'Rank':<6} {'Skill':<40} {'Count':<10} {'Percentage':<12}")
        print("-" * 70)
        
        for idx, (skill, count, percentage) in enumerate(rows, 1):
            print(f"{idx:<6} {skill:<40} {count:<10} {percentage:.2f}%")
        
        print()
    
    except Exception as e:
        logger.error(f"Error fetching top skills: {e}")
    finally:
        conn.close()


def top_frameworks_tools(limit: int = 10) -> None:
    """
    Get and print the top most in-demand frameworks and tools using json_each() aggregation.
    
    Args:
        limit: Number of top frameworks to display
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        print_header("TOP 10 MOST IN-DEMAND FRAMEWORKS & TOOLS")
        
        query = f"""
        SELECT 
            value as framework_tool,
            COUNT(*) as demand_count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM structured_insights WHERE frameworks_tools IS NOT NULL), 2) as percentage
        FROM structured_insights, json_each(structured_insights.frameworks_tools)
        WHERE frameworks_tools IS NOT NULL AND frameworks_tools != '[]'
        GROUP BY value
        ORDER BY demand_count DESC
        LIMIT ?
        """
        
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        
        if not rows:
            print("No frameworks/tools data available.\n")
            return
        
        print(f"{'Rank':<6} {'Framework/Tool':<40} {'Count':<10} {'Percentage':<12}")
        print("-" * 70)
        
        for idx, (tool, count, percentage) in enumerate(rows, 1):
            print(f"{idx:<6} {tool:<40} {count:<10} {percentage:.2f}%")
        
        print()
    
    except Exception as e:
        logger.error(f"Error fetching top frameworks: {e}")
    finally:
        conn.close()


def seniority_distribution() -> None:
    """
    Display market demand across structural seniority tiers (extracted records only).
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Get total counts
        cursor.execute("SELECT COUNT(*) FROM raw_postings")
        total_jobs = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM structured_insights")
        extracted_jobs = cursor.fetchone()[0]
        
        print_header("MARKET DEMAND BY SENIORITY TIER")
        print(f"Note: Showing {extracted_jobs} extracted jobs out of {total_jobs} total fetched\n")
        
        query = """
        SELECT 
            seniority,
            COUNT(*) as job_count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM structured_insights), 2) as percentage
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
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print("No seniority data available.\n")
            return
        
        print(f"{'Seniority Level':<20} {'Job Count':<15} {'Percentage':<12}")
        print("-" * 70)
        
        for seniority, count, percentage in rows:
            print(f"{seniority:<20} {count:<15} {percentage:.2f}%")
        
        print()
    
    except Exception as e:
        logger.error(f"Error fetching seniority distribution: {e}")
    finally:
        conn.close()


def geographic_distribution() -> None:
    """
    Display job postings by geographic location (city/region).
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        print_header("GEOGRAPHIC DISTRIBUTION OF JOB POSTINGS")
        
        # Get hydrated jobs with locations (not using extraction_status which is never updated)
        query = """
        SELECT 
            location,
            COUNT(*) as job_count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM raw_postings WHERE raw_html IS NOT NULL AND location IS NOT NULL AND location NOT IN ('', 'Pending', 'Unknown')), 2) as percentage
        FROM raw_postings
        WHERE raw_html IS NOT NULL AND location IS NOT NULL AND location NOT IN ('', 'Pending', 'Unknown')
        GROUP BY location
        ORDER BY job_count DESC
        LIMIT 15
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print("No location data available.\n")
            return
        
        valid_locations = sum(count for _, count, _ in rows)
        print(f"Found jobs in {len(rows)} locations with location data\n")
        print(f"{'Location':<30} {'Job Count':<15} {'Percentage':<12}")
        print("-" * 70)
        
        for location, count, percentage in rows:
            print(f"{location:<30} {count:<15} {percentage:.2f}%")
        
        print()
    
    except Exception as e:
        logger.error(f"Error in geographic distribution: {e}")
    finally:
        conn.close()


def extraction_status_summary() -> None:
    """
    Display summary of extraction status across all postings.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        print_header("EXTRACTION STATUS SUMMARY")
        
        query = """
        SELECT 
            extraction_status,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM raw_postings), 2) as percentage
        FROM raw_postings
        GROUP BY extraction_status
        ORDER BY count DESC
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print("No extraction status data available.\n")
            return
        
        print(f"{'Status':<20} {'Count':<10} {'Percentage':<12}")
        print("-" * 70)
        
        for status, count, percentage in rows:
            print(f"{status:<20} {count:<10} {percentage:.2f}%")
        
        print()
    
    except Exception as e:
        logger.error(f"Error fetching extraction status: {e}")
    finally:
        conn.close()


def skill_seniority_correlation() -> None:
    """
    Display which skills are most associated with specific seniority levels.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        print_header("SKILLS BY SENIORITY LEVEL (Top 5 per tier)")
        
        seniorities = ["Lead", "Senior", "Mid", "Junior"]
        
        for seniority in seniorities:
            print(f"\n  {seniority} Level:")
            print(f"  {'-' * 60}")
            
            query = """
            SELECT 
                value as skill,
                COUNT(*) as count
            FROM structured_insights, json_each(structured_insights.skills)
            WHERE seniority = ? AND skills IS NOT NULL AND skills != '[]'
            GROUP BY value
            ORDER BY count DESC
            LIMIT 5
            """
            
            cursor.execute(query, (seniority,))
            rows = cursor.fetchall()
            
            if not rows:
                print(f"  No skill data for {seniority} positions\n")
                continue
            
            for idx, (skill, count) in enumerate(rows, 1):
                print(f"    {idx}. {skill:<35} ({count} mentions)")
            print()
    
    except Exception as e:
        logger.error(f"Error fetching skill-seniority correlation: {e}")
    finally:
        conn.close()


def scan_duplicates() -> dict:
    """
    Scan for duplicate job postings by title hash similarity.
    
    Returns:
        Dictionary with duplicate statistics
    """
    logger.info("Scanning for duplicate job postings...")
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Get all hydrated jobs with titles
        cursor.execute("""
            SELECT id, title FROM raw_postings
            WHERE raw_html IS NOT NULL AND raw_html != ''
            ORDER BY title ASC
        """)
        
        records = cursor.fetchall()
        title_hashes = {}
        duplicates = []
        
        for record_id, title in records:
            if not title or title == "Unknown":
                continue
            
            # Calculate MD5 hash of title for duplicate detection
            title_hash = hashlib.md5(title.lower().strip().encode()).hexdigest()
            
            if title_hash in title_hashes:
                duplicates.append({
                    'id': record_id,
                    'title': title,
                    'duplicate_of': title_hashes[title_hash]['id']
                })
            else:
                title_hashes[title_hash] = {'id': record_id, 'title': title}
        
        logger.info(f"Found {len(duplicates)} potential duplicates out of {len(records)} hydrated jobs")
        return {
            'total_hydrated': len(records),
            'unique_titles': len(title_hashes),
            'duplicate_count': len(duplicates)
        }
    
    except Exception as e:
        logger.error(f"Error scanning duplicates: {e}")
        return {}
    finally:
        conn.close()


def analyze_company_extraction_quality() -> dict:
    """
    Analyze company extraction quality and identify missing/unknown companies.
    
    Returns:
        Dictionary with company extraction statistics
    """
    logger.info("Analyzing company extraction quality...")
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM raw_postings
            WHERE raw_html IS NOT NULL AND raw_html != ''
        """)
        total_hydrated = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM raw_postings
            WHERE company = 'Unknown' AND raw_html IS NOT NULL AND raw_html != ''
        """)
        unknown_count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(DISTINCT company) FROM raw_postings
            WHERE raw_html IS NOT NULL AND raw_html != ''
        """)
        unique_companies = cursor.fetchone()[0]
        
        unknown_pct = 100 * unknown_count / total_hydrated if total_hydrated > 0 else 0
        logger.info(f"Company extraction: {unknown_count}/{total_hydrated} unknown ({unknown_pct:.1f}%)")
        
        return {
            'total_hydrated': total_hydrated,
            'unknown_count': unknown_count,
            'unknown_percentage': unknown_pct,
            'unique_companies': unique_companies
        }
    
    except Exception as e:
        logger.error(f"Error analyzing company extraction: {e}")
        return {}
    finally:
        conn.close()


def analyze_location_extraction_quality() -> dict:
    """
    Analyze location extraction quality.
    
    Returns:
        Dictionary with location statistics
    """
    logger.info("Analyzing location extraction quality...")
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM raw_postings
            WHERE raw_html IS NOT NULL AND raw_html != ''
        """)
        total_hydrated = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM raw_postings
            WHERE location = 'Unknown' AND raw_html IS NOT NULL AND raw_html != ''
        """)
        unknown_count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(DISTINCT location) FROM raw_postings
            WHERE raw_html IS NOT NULL AND raw_html != ''
        """)
        unique_locations = cursor.fetchone()[0]
        
        unknown_pct = 100 * unknown_count / total_hydrated if total_hydrated > 0 else 0
        logger.info(f"Location extraction: {unknown_count}/{total_hydrated} unknown ({unknown_pct:.1f}%)")
        
        return {
            'total_hydrated': total_hydrated,
            'unknown_count': unknown_count,
            'unknown_percentage': unknown_pct,
            'unique_locations': unique_locations
        }
    
    except Exception as e:
        logger.error(f"Error analyzing location extraction: {e}")
        return {}
    finally:
        conn.close()


def analyze_finnish_language_distribution() -> dict:
    """
    Analyze distribution of Finnish language requirements across extracted jobs.
    
    Returns:
        Dictionary with language requirement statistics
    """
    logger.info("Analyzing Finnish language requirements...")
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN finnish_language_required = 1 THEN 1 ELSE 0 END) as requires_finnish,
                SUM(CASE WHEN finnish_language_required = 0 THEN 1 ELSE 0 END) as no_finnish,
                SUM(CASE WHEN finnish_language_required IS NULL THEN 1 ELSE 0 END) as unknown
            FROM structured_insights
        """)
        
        result = cursor.fetchone()
        total_extracted = result[0] or 0
        requires_finnish = result[1] or 0
        no_finnish = result[2] or 0
        unknown = result[3] or 0
        
        finnish_pct = 100 * requires_finnish / total_extracted if total_extracted > 0 else 0
        logger.info(f"Language analysis: {requires_finnish}/{total_extracted} require Finnish ({finnish_pct:.1f}%)")
        
        return {
            'total_extracted': total_extracted,
            'requires_finnish': requires_finnish,
            'no_finnish_required': no_finnish,
            'unknown': unknown,
            'finnish_percentage': finnish_pct
        }
    
    except Exception as e:
        logger.error(f"Error analyzing language requirements: {e}")
        return {}
    finally:
        conn.close()


def data_quality_report() -> None:
    """
    Display comprehensive data quality and integrity report.
    """
    print_header("DATA QUALITY & INTEGRITY REPORT")
    
    print("\nHYDRATION & EXTRACTION STATUS:")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN raw_html IS NOT NULL AND raw_html != '' THEN 1 ELSE 0 END) as hydrated
        FROM raw_postings
    """)
    total, hydrated = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM structured_insights")
    extracted = cursor.fetchone()[0]
    conn.close()

    print(f"  Total jobs:  {total}")
    print(f"  Hydrated:   {hydrated} ({100*hydrated/total if total else 0:.1f}%)")
    print(f"  Extracted:  {extracted} ({100*extracted/total if total else 0:.1f}%)")

    print("\nCOMPANY EXTRACTION QUALITY:")
    company_stats = analyze_company_extraction_quality()
    print(f"  Unknown companies: {company_stats.get('unknown_count', 0)}/{company_stats.get('total_hydrated', 0)} ({company_stats.get('unknown_percentage', 0):.1f}%)")
    print(f"  Unique companies found: {company_stats.get('unique_companies', 0)}")

    print("\nLOCATION EXTRACTION QUALITY:")
    location_stats = analyze_location_extraction_quality()
    print(f"  Unknown locations: {location_stats.get('unknown_count', 0)}/{location_stats.get('total_hydrated', 0)} ({location_stats.get('unknown_percentage', 0):.1f}%)")
    print(f"  Unique locations found: {location_stats.get('unique_locations', 0)}")

    print("\nDUPLICATE DETECTION (by title hash):")
    dup_stats = scan_duplicates()
    print(f"  Potential duplicates: {dup_stats.get('duplicate_count', 0)}/{dup_stats.get('total_hydrated', 0)}")

    print("\nFINNISH LANGUAGE REQUIREMENTS:")
    lang_stats = analyze_finnish_language_distribution()
    print(f"  Jobs extracted: {lang_stats.get('total_extracted', 0)}")
    print(f"  Require Finnish: {lang_stats.get('requires_finnish', 0)} ({lang_stats.get('finnish_percentage', 0):.1f}%)")
    print(f"  No Finnish required: {lang_stats.get('no_finnish_required', 0)}")
    print(f"  Unknown: {lang_stats.get('unknown', 0)}")
    
    print()


def skill_cooccurrence(min_count: int = 5, limit: int = 20) -> None:
    """
    Show skill pairs that appear together in the same job posting.
    This is the most actionable signal for deciding what skill combinations to build.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        print_header("TOP SKILL CO-OCCURRENCES (pairs that appear together)")

        cursor.execute("SELECT COUNT(*) FROM structured_insights")
        total = cursor.fetchone()[0]
        if not total:
            print("No extraction data yet.\n")
            return

        cursor.execute("""
            SELECT s1.value, s2.value, COUNT(*) as n
            FROM structured_insights,
                 json_each(structured_insights.skills) s1,
                 json_each(structured_insights.skills) s2
            WHERE s1.value < s2.value
              AND skills IS NOT NULL AND skills != '[]'
            GROUP BY s1.value, s2.value
            HAVING n >= ?
            ORDER BY n DESC
            LIMIT ?
        """, (min_count, limit))
        rows = cursor.fetchall()

        if not rows:
            print(f"No pairs appear together >= {min_count} times yet.\n")
            return

        print(f"{'Skill Pair':<50} {'Jobs':>6}  {'% of all jobs':>13}")
        print("-" * 72)
        for skill_a, skill_b, count in rows:
            pair = f"{skill_a} + {skill_b}"
            print(f"{pair:<50} {count:>6}  {100*count/total:>12.1f}%")
        print()
    except Exception as e:
        logger.error(f"Error in skill co-occurrence: {e}")
    finally:
        conn.close()


def experience_distribution() -> None:
    """Distribution of years of experience required across all extracted jobs."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        print_header("YEARS OF EXPERIENCE REQUIRED")

        cursor.execute("""
            SELECT years_experience_required, COUNT(*) as n,
                   ROUND(COUNT(*) * 100.0 /
                       (SELECT COUNT(*) FROM structured_insights
                        WHERE years_experience_required IS NOT NULL), 1) as pct
            FROM structured_insights
            WHERE years_experience_required IS NOT NULL
            GROUP BY years_experience_required
            ORDER BY CASE years_experience_required
                WHEN '0-2'          THEN 1
                WHEN '2-5'          THEN 2
                WHEN '5-10'         THEN 3
                WHEN '10+'          THEN 4
                WHEN 'Not specified' THEN 5
                ELSE 6
            END
        """)
        rows = cursor.fetchall()

        if not rows:
            print("No experience data yet — re-run extraction after schema update.\n")
            return

        print(f"{'Experience bracket':<20} {'Jobs':>8}  {'%':>6}")
        print("-" * 38)
        for exp, count, pct in rows:
            print(f"{exp:<20} {count:>8}  {pct:>5.1f}%")
        print()
    except Exception as e:
        logger.error(f"Error in experience distribution: {e}")
    finally:
        conn.close()


def remote_work_distribution() -> None:
    """How many jobs offer remote, hybrid, or on-site work."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        print_header("REMOTE WORK AVAILABILITY")

        cursor.execute("""
            SELECT remote_work_available, COUNT(*) as n,
                   ROUND(COUNT(*) * 100.0 /
                       (SELECT COUNT(*) FROM structured_insights
                        WHERE remote_work_available IS NOT NULL), 1) as pct
            FROM structured_insights
            WHERE remote_work_available IS NOT NULL
            GROUP BY remote_work_available
            ORDER BY n DESC
        """)
        rows = cursor.fetchall()

        if not rows:
            print("No remote work data yet — re-run extraction after schema update.\n")
            return

        print(f"{'Work arrangement':<20} {'Jobs':>8}  {'%':>6}")
        print("-" * 38)
        for arrangement, count, pct in rows:
            print(f"{arrangement:<20} {count:>8}  {pct:>5.1f}%")
        print()
    except Exception as e:
        logger.error(f"Error in remote work distribution: {e}")
    finally:
        conn.close()


def analytics_pipeline() -> None:
    """
    Run the complete analytics pipeline and print all reports to stdout.
    """
    logger.info("Starting analytics pipeline")
    
    try:
        # First show data quality report
        data_quality_report()
        
        # Market analysis
        top_skills()
        top_frameworks_tools()
        skill_cooccurrence()
        seniority_distribution()
        experience_distribution()
        remote_work_distribution()
        geographic_distribution()
        extraction_status_summary()
        skill_seniority_correlation()
        
        try:
            from generate_report import main as generate_html_report
            generate_html_report()
        except Exception as e:
            logger.error(f"HTML report generation failed: {e}")

        print("\n" + "="*70)
        print("  ANALYTICS COMPLETE")
        print("="*70 + "\n")
        logger.info("Analytics pipeline completed successfully")
    
    except Exception as e:
        logger.error(f"Analytics pipeline error: {e}")


if __name__ == "__main__":
    analytics_pipeline()
