"""Log consumer thread that reads from queue and writes to files with rotation."""

from __future__ import annotations

import json
import logging
import logging.handlers
import multiprocessing as mp
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "process": record.process,
                "processName": record.processName,
            },
            ensure_ascii=False,
        )


class LogConsumer:
    """Consumes log records from a multiprocessing queue and writes to rotated files."""

    def __init__(
        self,
        queue: mp.Queue,
        level: str = "INFO",
        fmt: str = "json",
        info_output: str | None = None,
        error_output: str | None = None,
        rotate_by: str = "none",
        max_size: int = 100,
        when: str = "midnight",
        backup_count: int = 7,
    ) -> None:
        self.queue = queue
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.fmt = fmt
        self.info_output = info_output
        self.error_output = error_output
        self.rotate_by = rotate_by
        self.max_size = max_size
        self.when = when
        self.backup_count = backup_count
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="log-consumer")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _build_handler(self, path: str, level: int) -> logging.Handler:
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        if self.rotate_by == "size":
            handler: logging.Handler = logging.handlers.RotatingFileHandler(
                path,
                maxBytes=self.max_size * 1024 * 1024,
                backupCount=self.backup_count,
            )
        elif self.rotate_by == "time":
            handler = logging.handlers.TimedRotatingFileHandler(
                path,
                when=self.when,
                backupCount=self.backup_count,
            )
        else:
            handler = logging.FileHandler(path)

        handler.setLevel(level)

        if self.fmt == "json":
            formatter: logging.Formatter = _JSONFormatter()
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(processName)s[%(process)d] - %(name)s - %(levelname)s - %(message)s"
            )
        handler.setFormatter(formatter)
        return handler

    def _run(self) -> None:
        handlers: list[tuple[str, logging.Handler]] = []
        if self.info_output:
            handlers.append(("info", self._build_handler(self.info_output, logging.INFO)))
        if self.error_output:
            handlers.append(("error", self._build_handler(self.error_output, logging.ERROR)))

        if not handlers:
            # No file outputs configured — log to console
            handler = logging.StreamHandler()
            handler.setLevel(self.level)
            if self.fmt == "json":
                handler.setFormatter(_JSONFormatter())
            else:
                handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s - %(processName)s[%(process)d] - %(name)s - %(levelname)s - %(message)s"
                    )
                )
            handlers.append(("console", handler))

        while not self._stop_event.is_set():
            try:
                record = self.queue.get(timeout=0.1)
            except Exception:
                continue

            for _name, handler in handlers:
                if record.levelno >= handler.level:
                    handler.emit(record)

        # Flush and close all handlers on shutdown
        for _name, handler in handlers:
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
