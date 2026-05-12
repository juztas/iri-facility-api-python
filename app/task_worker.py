#!/usr/bin/env python3
"""Local task worker for queued filesystem and interactive work."""
from __future__ import annotations

import os
import time

from app.apilogger import get_stream_logger
from app.routers.task.facility_adapter import drain_local_task_queue_once

logger = get_stream_logger(__name__)


def main() -> int:
    once = os.environ.get("IRI_TASK_WORKER_ONCE", "false").lower() in {"1", "true", "yes", "on"}
    sleep_seconds = float(os.environ.get("IRI_TASK_WORKER_POLL_SECONDS", "1"))
    processed = 0

    while True:
        did_work = drain_local_task_queue_once()
        if did_work:
            processed += 1
            continue
        if once:
            logger.info(f"Worker exiting after one pass; processed {processed} task(s)")
            return 0
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
