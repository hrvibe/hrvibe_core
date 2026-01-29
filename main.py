"""
Orchestrator: starts both manager_bot and applicant_bot as separate processes.
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

# Both bots run by the orchestrator
BOT_NAMES = ("manager_bot", "applicant_bot")


def start_bot_process(name: str, cwd: str) -> subprocess.Popen:
    """Start one bot process. Sets HRVIBE_BOT in env so logging_service knows which bot it is."""
    logger.info("Starting %s in %s", name, cwd)

    if not os.path.isdir(cwd):
        raise FileNotFoundError(f"Directory {cwd} does not exist")

    main_py_path = os.path.join(cwd, "main.py")
    if not os.path.isfile(main_py_path):
        raise FileNotFoundError(f"main.py not found in {cwd}")

    env = os.environ.copy()
    env["HRVIBE_BOT"] = name

    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=cwd,
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    logger.info("%s started with PID %s", name, proc.pid)
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
    project_root = os.path.dirname(os.path.abspath(__file__))

    logger.info("Orchestrator starting (both bots)...")
    logger.info("Project root: %s", project_root)

    users_data_dir = Path(os.getenv("USERS_DATA_DIR", "./users_data"))
    try:
        users_data_dir.mkdir(parents=True, exist_ok=True)
        logger.info("USERS_DATA_DIR = %s (created/verified)", users_data_dir)
    except Exception as e:
        logger.error("Failed to create USERS_DATA_DIR %s: %s", users_data_dir, e)
        sys.exit(1)

    procs = []
    try:
        for bot_name in BOT_NAMES:
            bot_cwd = os.path.join(project_root, bot_name)
            proc = start_bot_process(bot_name, bot_cwd)
            procs.append(proc)

        logger.info("Both bots started. Monitoring...")

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

        exit_code = 0
        while True:
            for i, proc in enumerate(procs):
                code = proc.poll()
                if code is not None:
                    name = BOT_NAMES[i]
                    logger.error("%s exited with code: %s", name, code)
                    exit_code = code
                    break
            else:
                time.sleep(2)
                continue
            break

        shutdown(procs, "bot-exit")
        logger.info("Orchestrator exiting")
        sys.exit(exit_code)

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
