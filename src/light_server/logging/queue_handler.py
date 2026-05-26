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


def setup_worker_logging(queue: mp.Queue, level: str = "INFO", fmt: str = "json") -> None:
    """Configure logging in worker processes to use the queue handler."""
    root = logging.getLogger()
    root.handlers = []
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear any pre-existing handlers on non-root loggers (e.g. uvicorn)
    # so that all logs propagate to the root queue handler.
    for logger_name in list(logging.root.manager.loggerDict.keys()):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = True

    handler = MPQueueHandler(queue)
    # NOTE: Do NOT set formatter here. QueueHandler.prepare() flattens
    # the message; the consumer (LogConsumer in main process) owns formatting.
    root.addHandler(handler)
