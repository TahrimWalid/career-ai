"""
Central logging utility for the Duunitori pipeline.
Dual output:
  stdout   → INFO+  (clean summaries; captured by nohup as nohup.out)
  output.log → DEBUG+ (raw verbose log for post-run inspection)
"""
import logging
import sys
from pathlib import Path

def get_logger(name: str = "duunitori_pipeline") -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )

    # Stdout: INFO and above — clean summarised output (→ nohup.out)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # output.log: DEBUG and above — full raw log
    file_handler = logging.FileHandler(Path("output.log"), mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# Export the logger instance for easy import across modules
logger = get_logger()
