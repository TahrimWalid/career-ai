"""
Analytics module for market insights extraction using SQLite aggregates and JSON functions.
Generates reports on skills demand, frameworks, seniority distribution, and geographic patterns.
"""
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
            json_extract(value, '$') as skill,
            COUNT(*) as demand_count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM structured_insights WHERE skills IS NOT NULL), 2) as percentage
        FROM structured_insights, json_each(structured_insights.skills)
        WHERE skills IS NOT NULL AND skills != '[]'
        GROUP BY json_extract(value, '$')
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
            json_extract(value, '$') as framework_tool,
            COUNT(*) as demand_count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM structured_insights WHERE frameworks_tools IS NOT NULL), 2) as percentage
        FROM structured_insights, json_each(structured_insights.frameworks_tools)
        WHERE frameworks_tools IS NOT NULL AND frameworks_tools != '[]'
        GROUP BY json_extract(value, '$')
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
    Display market demand across structural seniority tiers.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        print_header("MARKET DEMAND BY SENIORITY TIER")
        
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
    Display market demand across geographic regions based on location field.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        print_header("GEOGRAPHIC DISTRIBUTION OF JOB POSTINGS")
        
        query = """
        SELECT 
            COALESCE(raw_postings.location, 'Unknown') as location,
            COUNT(*) as job_count,
            COUNT(CASE WHEN structured_insights.id IS NOT NULL THEN 1 END) as extracted_count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM raw_postings), 2) as percentage
        FROM raw_postings
        LEFT JOIN structured_insights ON raw_postings.id = structured_insights.id
        GROUP BY raw_postings.location
        ORDER BY job_count DESC
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print("No geographic data available.\n")
            return
        
        print(f"{'Location':<30} {'Total':<10} {'Extracted':<12} {'Percentage':<12}")
        print("-" * 70)
        
        for location, total, extracted, percentage in rows:
            print(f"{location:<30} {total:<10} {extracted:<12} {percentage:.2f}%")
        
        print()
    
    except Exception as e:
        logger.error(f"Error fetching geographic distribution: {e}")
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
                json_extract(value, '$') as skill,
                COUNT(*) as count
            FROM structured_insights, json_each(structured_insights.skills)
            WHERE seniority = ? AND skills IS NOT NULL AND skills != '[]'
            GROUP BY json_extract(value, '$')
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


def analytics_pipeline() -> None:
    """
    Run the complete analytics pipeline and print all reports to stdout.
    """
    logger.info("Starting analytics pipeline")
    
    try:
        top_skills()
        top_frameworks_tools()
        seniority_distribution()
        geographic_distribution()
        extraction_status_summary()
        skill_seniority_correlation()
        
        print("\n" + "="*70)
        print("  ANALYTICS COMPLETE")
        print("="*70 + "\n")
        logger.info("Analytics pipeline completed successfully")
    
    except Exception as e:
        logger.error(f"Analytics pipeline error: {e}")


if __name__ == "__main__":
    analytics_pipeline()
