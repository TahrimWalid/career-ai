"""
Central logging utility for the Duunitori pipeline.
Streams logs simultaneously to stdout and pipeline.log.
"""
import logging
import sys
from pathlib import Path

def get_logger(name: str = "duunitori_pipeline") -> logging.Logger:
    """
    Initialize and return a configured logger with dual handlers (stdout + file).
    
    Args:
        name: Logger name, defaults to "duunitori_pipeline"
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers if logger is already configured
    if logger.hasHandlers():
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    # Formatting string with exact timestamps as per specification
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    
    # Stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)
    
    # File handler
    log_file = Path("pipeline.log")
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


# Export the logger instance for easy import across modules
logger = get_logger()
