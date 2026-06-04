"""
Main CLI orchestrator for the Duunitori resilient production pipeline.
Provides decoupled execution of scraping, extraction, and analytics phases.

Usage:
    python main.py --scrape          # Run web scraper only
    python main.py --extract         # Run LLM extraction only
    python main.py --analytics       # Run analytics reports only
    python main.py --all             # Run all phases sequentially (default)
"""
import argparse
import sys
import time
from datetime import datetime, timedelta

from database import init_database, get_connection
from logger import logger

# Import pipeline functions
from scraper import scrape_pipeline, generate_hydration_summary
from extractor import extraction_pipeline
from analytics import analytics_pipeline


def validate_and_initialize() -> None:
    """
    Initialize database and validate setup before executing pipeline phases.
    """
    logger.info("Initializing Duunitori pipeline...")
    try:
        init_database()
        logger.info("Database initialization successful")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        sys.exit(1)


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        minutes = (seconds % 3600) / 60
        return f"{hours:.1f}h {minutes:.0f}m"


def run_scraper(start_time: float) -> float:
    """Execute the web scraper phase and return phase duration."""
    logger.info("=" * 70)
    logger.info("PHASE 1: WEB SCRAPER")
    logger.info("=" * 70)
    phase_start = time.time()
    try:
        scrape_pipeline()
        phase_duration = time.time() - phase_start
        logger.info("Scraper phase completed successfully")
        logger.info(f"⏱️  Scraper duration: {format_duration(phase_duration)}")
        return phase_duration
    except Exception as e:
        logger.error(f"Scraper phase failed: {e}")
        raise


def run_extractor(start_time: float) -> float:
    """Execute the LLM extraction phase and return phase duration."""
    import shutil
    from pathlib import Path
    from datetime import datetime as dt
    
    logger.info("=" * 70)
    logger.info("PHASE 2: LLM EXTRACTION")
    logger.info("=" * 70)
    
    # Create backup BEFORE extraction to prevent data loss
    db_file = Path("duunitori_pipeline.db")
    if db_file.exists():
        backup_file = Path(f"duunitori_pipeline_backup_{dt.now().strftime('%Y%m%d_%H%M%S')}.db")
        shutil.copy(str(db_file), str(backup_file))
        logger.info(f"✓ Created pre-extraction backup: {backup_file}")
    
    phase_start = time.time()
    try:
        extraction_pipeline()
        phase_duration = time.time() - phase_start
        logger.info("Extraction phase completed successfully")
        logger.info(f"⏱️  Extraction duration: {format_duration(phase_duration)}")
        return phase_duration
    except Exception as e:
        logger.error(f"Extraction phase failed: {e}")
        raise


def run_analytics(start_time: float) -> float:
    """Execute the analytics phase and return phase duration."""
    logger.info("=" * 70)
    logger.info("PHASE 3: ANALYTICS & REPORTING")
    logger.info("=" * 70)
    phase_start = time.time()
    try:
        analytics_pipeline()
        phase_duration = time.time() - phase_start
        logger.info("Analytics phase completed successfully")
        logger.info(f"⏱️  Analytics duration: {format_duration(phase_duration)}")
        return phase_duration
    except Exception as e:
        logger.error(f"Analytics phase failed: {e}")
        raise


def run_summary_report() -> None:
    """Generate and display hydration and market summary report."""
    logger.info("=" * 70)
    logger.info("PIPELINE SUMMARY REPORT")
    logger.info("=" * 70)
    try:
        generate_hydration_summary()
    except Exception as e:
        logger.error(f"Summary report failed: {e}")


def main() -> None:
    """
    Main entry point with CLI argument parsing.
    """
    import shutil
    from pathlib import Path
    
    parser = argparse.ArgumentParser(
        description="Duunitori Resilient Production Pipeline v4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --scrape              Run web scraper only
  python main.py --extract             Run LLM extraction only
  python main.py --analytics           Run analytics reports only
  python main.py --all                 Run all phases sequentially
  python main.py                       Run all phases (default)
        """
    )
    
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Run web scraper phase only"
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Run LLM extraction phase only"
    )
    parser.add_argument(
        "--analytics",
        action="store_true",
        help="Run analytics phase only"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all phases sequentially (default behavior)"
    )
    parser.add_argument(
        "--reset-extraction",
        action="store_true",
        help="Wipe structured_insights and reset all records to 'pending' for re-extraction (use after schema changes)"
    )

    args = parser.parse_args()

    # Handle reset before anything else
    if args.reset_extraction:
        validate_and_initialize()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM structured_insights")
        count = cursor.fetchone()[0]
        cursor.execute("DELETE FROM structured_insights")
        cursor.execute("DELETE FROM failed_extractions")
        cursor.execute("UPDATE raw_postings SET extraction_status = 'pending' WHERE extraction_status != 'pending'")
        conn.commit()
        conn.close()
        logger.info(f"Reset complete: {count} extraction records cleared. Run --extract to re-process.")
        print(f"\n✓ Reset {count} extraction records. Run: python main.py --extract\n")
        return

    # Determine which phases to run
    run_all_phases = not any([args.scrape, args.extract, args.analytics]) or args.all
    
    # AUTO-BACKUP: Create backup BEFORE any pipeline operations
    db_file = Path("duunitori_pipeline.db")
    if db_file.exists():
        backup_file = Path(f"duunitori_pipeline_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        shutil.copy(str(db_file), str(backup_file))
        logger.info(f"✓ Created pre-pipeline backup: {backup_file}")
    
    logger.info(f"Pipeline started at {datetime.now()}")
    pipeline_start = time.time()
    phase_timings = {}
    
    try:
        # Always initialize database
        validate_and_initialize()
        
        if args.scrape or run_all_phases:
            phase_timings['scraper'] = run_scraper(pipeline_start)
            # Generate summary after scraping
            if args.scrape or (run_all_phases and not args.extract and not args.analytics):
                run_summary_report()
        
        if args.extract or run_all_phases:
            phase_timings['extractor'] = run_extractor(pipeline_start)
        
        if args.analytics or run_all_phases:
            phase_timings['analytics'] = run_analytics(pipeline_start)
        
        # Calculate and log total duration
        total_duration = time.time() - pipeline_start
        logger.info("\n" + "=" * 70)
        logger.info("TOTAL PIPELINE EXECUTION TIME")
        logger.info("=" * 70)
        logger.info(f"⏱️  Total duration: {format_duration(total_duration)}")
        logger.info(f"Pipeline completed at {datetime.now()}")
        
        # Show phase breakdown
        if phase_timings:
            logger.info("\nPhase Breakdown:")
            for phase, duration in phase_timings.items():
                pct = 100 * duration / total_duration
                logger.info(f"  - {phase.upper()}: {format_duration(duration)} ({pct:.1f}%)")
        
        logger.info("=" * 70)
        print("\n✓ Pipeline execution completed successfully!\n")
    
    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Pipeline failed with error: {e}", exc_info=True)
        print(f"\n✗ Pipeline failed: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
