"""HTTP worker process entry point for multi-process mode."""

from __future__ import annotations

import logging
import socket
from typing import Any

import uvicorn

from light_server.http.app import create_app
from light_server.http.state import HTTPState

logger = logging.getLogger(__name__)


def http_worker_main(
    state: HTTPState,
    sock: socket.socket,
    shutdown_event: Any | None = None,
) -> None:
    """Run a single HTTP worker process.

    This function is the ``target`` passed to ``mp.Process``.
    It reconstructs the FastAPI app in the child process, starts a
    per-process response consumer, and runs uvicorn on the shared
    socket (via file descriptor).

    Args:
        state: Picklable HTTP state (registry, transport, config, …).
        sock: Pre-bound socket shared from the main process.
        shutdown_event: Optional ``mp.Event`` or ``threading.Event``
            that signals the worker to exit gracefully.
    """
    # Initialise per-process resources (metrics, SHM buffer, hook cache)
    state.init_worker_locals()

    app = create_app(state)

    uvconfig = uvicorn.Config(
        app=app,
        fd=sock.fileno(),
        log_level=state.config.server.log_level,
        workers=1,
        log_config=None,
    )
    server = uvicorn.Server(uvconfig)

    logger.info(
        f"HTTP worker {state.response_queue_id} starting on fd {sock.fileno()}"
    )
    try:
        server.run()
    except Exception as exc:
        logger.exception(f"HTTP worker {state.response_queue_id} error: {exc}")
    finally:
        logger.info(f"HTTP worker {state.response_queue_id} exited")
