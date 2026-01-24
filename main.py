"""
Orchestrator for running a single bot: manager_bot, applicant_bot, or consultant_bot.
Which bot runs depends on ACTIVE_BOT environment variable.
"""

import os
import sys
import subprocess
import signal
import time
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables first, before setting up logging
load_dotenv()

USERS_DATA_DIR = os.getenv("USERS_DATA_DIR", "./users_data")
logs_dir = Path(USERS_DATA_DIR) / "logs" / "orchestrator_logs"
logs_dir.mkdir(parents=True, exist_ok=True)
print(f"Logs directory: {logs_dir}")
print(f"Users data directory: {USERS_DATA_DIR}")

log_filename = logs_dir / f"orchestrator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

file_handler = logging.handlers.RotatingFileHandler(
    log_filename,
    maxBytes=20 * 1024 * 1024,
    backupCount=20,
    encoding='utf-8'
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        file_handler,
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("hrvibe_orchestrator")
logger.info(f"Orchestrator logging configured. Logs written to: {log_filename}")


def start_bot_process(name: str, cwd: str) -> subprocess.Popen:
    logger.info("Starting %s bot in %s", name, cwd)

    if not os.path.isdir(cwd):
        raise FileNotFoundError(f"Directory {cwd} does not exist")

    main_py_path = os.path.join(cwd, "main.py")
    if not os.path.isfile(main_py_path):
        raise FileNotFoundError(f"main.py not found in {cwd}")

    cmd = [sys.executable, "main.py"]

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    logger.info("%s bot started with PID %s", name, proc.pid)
    return proc


def shutdown(procs: list, reason: str):
    logger.info("Shutting down child processes (reason: %s)...", reason)

    for p in procs:
        if p.poll() is None:
            try:
                logger.debug("Terminating process PID %s", p.pid)
                p.terminate()
            except Exception as e:
                logger.warning("Error terminating process PID %s: %s", p.pid, e)

    deadline = time.time() + 30
    for p in procs:
        if p.poll() is None:
            while p.poll() is None and time.time() < deadline:
                time.sleep(0.5)
            if p.poll() is None:
                logger.warning("Process PID %s did not exit in time, killing...", p.pid)
                try:
                    p.kill()
                except Exception as e:
                    logger.warning("Error killing process PID %s: %s", p.pid, e)
            else:
                logger.info("Process PID %s exited with code %s", p.pid, p.poll())

    logger.info("Shutdown completed")


def main():
    # Environment variables are already loaded at module level
    project_root = os.path.dirname(os.path.abspath(__file__))

    logger.info("Orchestrator starting...")
    logger.info("Project root: %s", project_root)

    # Get which bot to run from environment variable
    active_bot_raw = os.getenv("ACTIVE_BOT", "").strip()
    # Remove trailing % characters (common shell artifact) and other non-alphanumeric chars except underscore
    active_bot = active_bot_raw.rstrip('%').strip().lower()
    
    if not active_bot:
        logger.error("ACTIVE_BOT environment variable is not set. Please set it to 'manager_bot', 'applicant_bot', or 'consultant_bot' in .env file")
        sys.exit(1)
    
    valid_bots = ["manager_bot", "applicant_bot", "consultant_bot"]
    if active_bot not in valid_bots:
        logger.error("ACTIVE_BOT must be one of: %s, got: %s (raw value: '%s')", ", ".join(valid_bots), active_bot, active_bot_raw)
        sys.exit(1)
    
    logger.info("ACTIVE_BOT = %s", active_bot)

    # Determine bot directory based on ACTIVE_BOT value
    bot_cwd = os.path.join(project_root, active_bot)
    
    # Проверка USERS_DATA_DIR
    users_data_dir = Path(os.getenv("USERS_DATA_DIR", "./users_data"))
    try:
        users_data_dir.mkdir(parents=True, exist_ok=True)
        logger.info("USERS_DATA_DIR = %s (created/verified)", users_data_dir)
    except Exception as e:
        logger.error("Failed to create USERS_DATA_DIR %s: %s", users_data_dir, e)
        sys.exit(1)

    bot_proc = None
    procs = []

    try:
        # Start the active bot
        bot_proc = start_bot_process(active_bot, bot_cwd)
        logger.info("%s started successfully", active_bot)
        
        procs.append(bot_proc)

        shutdown_requested = False

        def handle_sigterm(signum, frame):
            nonlocal shutdown_requested
            if not shutdown_requested:
                shutdown_requested = True
                shutdown(procs, "SIGTERM")
                sys.exit(0)

        def handle_sigint(signum, frame):
            nonlocal shutdown_requested
            if not shutdown_requested:
                shutdown_requested = True
                shutdown(procs, "SIGINT")
                sys.exit(0)

        signal.signal(signal.SIGTERM, handle_sigterm)
        signal.signal(signal.SIGINT, handle_sigint)

        logger.info("Monitoring bot process...")
        while True:
            bot_code = bot_proc.poll() if bot_proc else None

            if bot_code is not None:
                logger.error("Bot exited with code: %s", bot_code)
                break

            time.sleep(2)

    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt")
        shutdown(procs, "KeyboardInterrupt")
        sys.exit(0)

    except Exception as e:
        logger.error("Orchestrator error: %s", e, exc_info=True)
        shutdown(procs, "exception")
        sys.exit(1)

    finally:
        if procs:
            shutdown(procs, "main-exit")

    logger.info("Orchestrator exiting")
    sys.exit(1)


if __name__ == "__main__":
    main()
