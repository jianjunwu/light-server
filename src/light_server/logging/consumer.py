"""Log consumer thread that reads from queue and writes to files/stdout."""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class LogConsumer:
    """Consumes log records from a multiprocessing queue."""

    def __init__(
        self,
        queue: mp.Queue,
        level: str = "INFO",
        fmt: str = "json",
        output: str | None = None,
    ) -> None:
        self.queue = queue
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.fmt = fmt
        self.output = Path(output) if output else None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="log-consumer")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        handlers: list[Any] = []
        if self.output:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(self.output / "light-server.log")
            handlers.append(file_handler)
        else:
            handlers.append(logging.StreamHandler(sys.stdout))

        while not self._stop_event.is_set():
            try:
                record = self.queue.get(timeout=0.1)
            except Exception:
                continue

            if record.levelno < self.level:
                continue

            msg = self._format(record)
            for h in handlers:
                try:
                    h.stream.write(msg + "\n")
                    h.stream.flush()
                except Exception:
                    pass

    def _format(self, record: logging.LogRecord) -> str:
        if self.fmt == "json":
            return json.dumps({
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "process": record.process,
                "processName": record.processName,
            }, ensure_ascii=False)
        return f"{datetime.fromtimestamp(record.created).isoformat()} - {record.processName}[{record.process}] - {record.name} - {record.levelname} - {record.getMessage()}"
