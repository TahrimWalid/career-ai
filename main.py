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
from datetime import datetime

from database import init_database
from logger import logger

# Import pipeline functions
from scraper import scrape_pipeline
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


def run_scraper() -> None:
    """Execute the web scraper phase."""
    logger.info("=" * 70)
    logger.info("PHASE 1: WEB SCRAPER")
    logger.info("=" * 70)
    try:
        scrape_pipeline()
        logger.info("Scraper phase completed successfully")
    except Exception as e:
        logger.error(f"Scraper phase failed: {e}")
        raise


def run_extractor() -> None:
    """Execute the LLM extraction phase."""
    logger.info("=" * 70)
    logger.info("PHASE 2: LLM EXTRACTION")
    logger.info("=" * 70)
    try:
        extraction_pipeline()
        logger.info("Extraction phase completed successfully")
    except Exception as e:
        logger.error(f"Extraction phase failed: {e}")
        raise


def run_analytics() -> None:
    """Execute the analytics phase."""
    logger.info("=" * 70)
    logger.info("PHASE 3: ANALYTICS & REPORTING")
    logger.info("=" * 70)
    try:
        analytics_pipeline()
        logger.info("Analytics phase completed successfully")
    except Exception as e:
        logger.error(f"Analytics phase failed: {e}")
        raise


def main() -> None:
    """
    Main entry point with CLI argument parsing.
    """
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
    
    args = parser.parse_args()
    
    # Determine which phases to run
    run_all_phases = not any([args.scrape, args.extract, args.analytics]) or args.all
    
    logger.info(f"Pipeline started at {datetime.now()}")
    
    try:
        # Always initialize database
        validate_and_initialize()
        
        if args.scrape or run_all_phases:
            run_scraper()
        
        if args.extract or run_all_phases:
            run_extractor()
        
        if args.analytics or run_all_phases:
            run_analytics()
        
        logger.info(f"Pipeline completed successfully at {datetime.now()}")
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
