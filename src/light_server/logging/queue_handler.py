"""QueueHandler for sending log records from worker processes to main process."""

from __future__ import annotations

import logging
import multiprocessing as mp
from typing import Any


class MPQueueHandler(logging.Handler):
    """Sends log records to a multiprocessing queue for centralized processing."""

    def __init__(self, queue: mp.Queue) -> None:
        super().__init__()
        self.queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put(record)
        except Exception:
            self.handleError(record)


def setup_worker_logging(queue: mp.Queue, level: str = "INFO") -> None:
    """Configure logging in worker processes to use the queue handler."""
    root = logging.getLogger()
    root.handlers = []
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = MPQueueHandler(queue)
    formatter = logging.Formatter(
        "%(asctime)s - %(processName)s[%(process)d] - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
