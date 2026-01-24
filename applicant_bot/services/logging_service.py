import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
import os


def setup_logging(max_bytes: int = 20 * 1024 * 1024, backup_count: int = 20):
    """Configure logging to write to both console and file with rotation.
    If exceeds max_bytes, the log file will be rotated and the new log file will be created.
    IF excceded backup_count, the oldest log file will be deleted.
    Args:
        max_bytes: Maximum size of log file before rotation (default: 20MB)
        backup_count: Number of backup files to keep (default: 20)
    """

    # ------------- CREATION OF LOGGING FILE -------------

    data_dir = Path(os.getenv("USERS_DATA_DIR", "./users_data"))
    logs_dir = data_dir / "logs" / "applicant_bot_logs"
    # Create logs directory and all parent directories if they don't exist
    logs_dir.mkdir(parents=True, exist_ok=True)
    # Each application start will create a new log file path with timestamp (to avoid overwriting the same file)
    log_filename = logs_dir / f"applicant_bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    # ------------- CONFIGURATION OF LOGGING -------------

    # Create rotating file handler to prevent log files from growing too large
    file_handler = logging.handlers.RotatingFileHandler(
        log_filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    
    logging.basicConfig(
        # Log all levels: DEBUG < INFO < WARNING < ERROR < CRITICAL
        level=logging.DEBUG,  
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            # Write to file with rotation
            file_handler,
            # Also write to console
            logging.StreamHandler(sys.stdout)  
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured. Logs are written to: {log_filename}")
    logger.info(f"Log rotation: max size {max_bytes / (1024*1024):.1f}MB, keeping {backup_count} backup files")

