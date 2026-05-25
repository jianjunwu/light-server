"""QueueHandler for sending log records from worker processes to main process."""

from __future__ import annotations

import logging
import logging.handlers
import multiprocessing as mp


class MPQueueHandler(logging.handlers.QueueHandler):
    """Sends log records to a multiprocessing queue for centralized processing.

    Inherits from stdlib QueueHandler which automatically sanitizes
    exc_info/args/msg before putting the record across process boundaries.
    """


def setup_worker_logging(queue: mp.Queue, level: str = "INFO") -> None:
    """Configure logging in worker processes to use the queue handler."""
    root = logging.getLogger()
    root.handlers = []
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = MPQueueHandler(queue)
    # NOTE: Do NOT set formatter here. QueueHandler.prepare() flattens
    # the message; the consumer (LogConsumer in main process) owns formatting.
    root.addHandler(handler)
