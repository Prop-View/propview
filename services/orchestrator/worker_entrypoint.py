"""PID 1 wrapper that drains active calls before stopping the worker."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker_entrypoint")

METRICS_PORT = int(os.environ.get("METRICS_PORT", "9090"))
DRAIN_TIMEOUT_SECONDS = int(os.environ.get("WORKER_DRAIN_TIMEOUT_SECONDS", "540"))
HEALTH_URL = f"http://127.0.0.1:{METRICS_PORT}"


def _post_drain() -> bool:
    request = Request(f"{HEALTH_URL}/drain", method="POST")
    try:
        with urlopen(request, timeout=5):
            return True
    except (URLError, TimeoutError, OSError):
        logger.exception("Could not request worker drain; child will still receive shutdown")
        return False


def _wait_for_drain() -> bool:
    deadline = time.monotonic() + DRAIN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{HEALTH_URL}/drained", timeout=5) as response:
                status = json.loads(response.read())
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            logger.exception("Could not read active-call drain status")
            return False
        if status["drained"]:
            return True
        time.sleep(2)
    return False


def main() -> int:
    child = subprocess.Popen([sys.executable, "worker.py", *(sys.argv[1:] or ["start"])])
    handled = False

    def shutdown(signum, _frame) -> None:
        nonlocal handled
        if handled:
            return
        handled = True
        logger.info("Shutdown requested; stopping new calls and waiting for active calls")
        _post_drain()
        if not _wait_for_drain():
            logger.error("Call drain timed out or status was unavailable; stopping worker anyway")
        if child.poll() is None:
            child.send_signal(signum)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
