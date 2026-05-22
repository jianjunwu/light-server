"""Tests for queue-based multiprocess logging."""

import json
import logging
import multiprocessing as mp
import tempfile
from pathlib import Path

from light_server.logging.consumer import LogConsumer
from light_server.logging.queue_handler import MPQueueHandler, setup_worker_logging


def test_mp_queue_handler():
    queue = mp.Queue()
    handler = MPQueueHandler(queue)
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0, msg="hello", args=(), exc_info=None
    )
    handler.emit(record)
    got = queue.get(timeout=1)
    assert got.getMessage() == "hello"


def test_log_consumer_writes_info_and_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue = mp.Queue()
        info_path = str(Path(tmpdir) / "info.log")
        error_path = str(Path(tmpdir) / "error.log")

        consumer = LogConsumer(
            queue=queue,
            level="INFO",
            fmt="json",
            info_output=info_path,
            error_output=error_path,
            rotate_by="none",
        )
        consumer.start()

        # Emit one info record
        info_record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0, msg="info_msg", args=(), exc_info=None
        )
        queue.put(info_record)

        # Emit one error record
        error_record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0, msg="error_msg", args=(), exc_info=None
        )
        queue.put(error_record)

        # Give consumer time to flush
        import time
        time.sleep(0.5)
        consumer.stop()

        with open(info_path) as f:
            info_lines = [l.strip() for l in f if l.strip()]
        with open(error_path) as f:
            error_lines = [l.strip() for l in f if l.strip()]

        # info.log should have both records
        assert len(info_lines) == 2
        # error.log should only have the error record
        assert len(error_lines) == 1

        info_data = [json.loads(l) for l in info_lines]
        assert any(r["message"] == "info_msg" for r in info_data)
        assert any(r["message"] == "error_msg" for r in info_data)

        error_data = [json.loads(l) for l in error_lines]
        assert error_data[0]["message"] == "error_msg"


def test_log_consumer_size_rotation():
    with tempfile.TemporaryDirectory() as tmpdir:
        queue = mp.Queue()
        info_path = str(Path(tmpdir) / "info.log")

        consumer = LogConsumer(
            queue=queue,
            level="INFO",
            fmt="text",
            info_output=info_path,
            rotate_by="size",
            max_size=1,  # 1 MB
            backup_count=2,
        )
        consumer.start()

        # Write a small record
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0, msg="x", args=(), exc_info=None
        )
        queue.put(record)

        import time
        time.sleep(0.3)
        consumer.stop()

        # File should exist and contain the record
        with open(info_path) as f:
            content = f.read()
        assert "x" in content


def test_setup_worker_logging():
    queue = mp.Queue()
    setup_worker_logging(queue, level="INFO")
    logging.getLogger("worker_test").info("from_worker")
    record = queue.get(timeout=1)
    assert record.getMessage() == "from_worker"
    assert record.name == "worker_test"
