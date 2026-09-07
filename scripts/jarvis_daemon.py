"""macOS launchd supervisor for the JARVIS runtime.

This supervisor keeps one JARVIS process alive and restarts it after a
crash, while applying a bounded backoff. It does not bypass permissions and
never runs arbitrary commands from configuration.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "logs"
logger = logging.getLogger("jarvis.daemon")


def _configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_DIR / "daemon.log", encoding="utf-8"),
        ],
    )


def check_database() -> bool:
    """Run a cheap SQLite integrity check before starting the worker."""
    path = ROOT / "data" / "jarvis.db"
    if not path.exists():
        return True
    try:
        with sqlite3.connect(path, timeout=5) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
        return bool(result and result[0] == "ok")
    except sqlite3.Error:
        logger.exception("SQLite health check failed")
        return False


def build_command() -> list[str]:
    """Start the runtime with browser HUD and native voice."""
    return [sys.executable, str(ROOT / "main.py"), "--browser", "--native-voice"]


def run_supervisor(*, once: bool = False, max_restarts: int = 0) -> int:
    """Supervise JARVIS until interrupted; return the last exit code."""
    stop_requested = False

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    restarts = 0
    delay = 2.0
    while not stop_requested:
        if not check_database():
            logger.error("Database health check failed; retrying after backoff")
            if once:
                return 2
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
            continue

        logger.info("Starting JARVIS worker: %s", build_command())
        try:
            process = subprocess.Popen(build_command(), cwd=str(ROOT))
            while process.poll() is None and not stop_requested:
                time.sleep(1.0)
            if stop_requested and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            exit_code = process.returncode or 0
        except OSError:
            logger.exception("Could not start JARVIS worker")
            exit_code = 1

        logger.warning("JARVIS worker exited with code %s", exit_code)
        if once or stop_requested:
            return exit_code
        restarts += 1
        if max_restarts and restarts > max_restarts:
            logger.error("Restart limit reached: %s", max_restarts)
            return exit_code
        time.sleep(delay)
        delay = min(delay * 2, 60.0)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS launchd supervisor")
    parser.add_argument("--once", action="store_true", help="Start once; do not restart")
    parser.add_argument("--max-restarts", type=int, default=0)
    args = parser.parse_args()
    _configure_logging()
    return run_supervisor(once=args.once, max_restarts=max(0, args.max_restarts))


if __name__ == "__main__":
    raise SystemExit(main())
