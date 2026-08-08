"""Background keepalive thread for Neon's pooled connection.

Neon scales its underlying compute to zero after ~5 minutes idle. A `SELECT 1`
every 4 minutes (inside pool_recycle=300s) keeps the compute warm for the
duration of a demo, so no request pays a multi-second cold-start penalty.
Runs on a plain thread (not asyncio) so it can't be starved by the event loop,
and is a no-op-safe failure: a keepalive tick that errors just logs and retries
next interval rather than crashing the app.
"""

import logging
import threading
import time

from sqlalchemy import text

from app.db.session import engine

logger = logging.getLogger("sanjeevani.keepalive")

INTERVAL_SECONDS = 240


class KeepaliveThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="db-keepalive")
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.wait(INTERVAL_SECONDS):
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                logger.debug("keepalive SELECT 1 ok")
            except Exception:
                logger.warning("keepalive SELECT 1 failed", exc_info=True)

    def stop(self) -> None:
        self._stop_event.set()


_thread: KeepaliveThread | None = None


def start() -> None:
    global _thread
    if _thread is not None:
        return
    _thread = KeepaliveThread()
    _thread.start()


def stop() -> None:
    global _thread
    if _thread is not None:
        _thread.stop()
        _thread = None
