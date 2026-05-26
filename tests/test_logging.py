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


def test_setup_worker_logging_clears_existing_handlers():
    """Existing logger handlers (e.g. uvicorn) should be cleared so logs propagate to root queue handler."""
    queue = mp.Queue()
    # Simulate uvicorn or another library adding its own handler
    uvicorn_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger.handlers = [logging.StreamHandler()]
    uvicorn_logger.propagate = False

    setup_worker_logging(queue, level="INFO")

    # Handler removed and propagate restored
    assert uvicorn_logger.handlers == []
    assert uvicorn_logger.propagate is True

    # Log should now reach the queue via root
    uvicorn_logger.info("uvicorn_msg")
    record = queue.get(timeout=1)
    assert record.getMessage() == "uvicorn_msg"


def test_log_consumer_always_outputs_to_console_with_files():
    """When file outputs are configured, LogConsumer should still output to console."""
    queue = mp.Queue()
    with tempfile.TemporaryDirectory() as tmpdir:
        info_path = str(Path(tmpdir) / "info.log")
        consumer = LogConsumer(
            queue=queue,
            level="INFO",
            fmt="text",
            info_output=info_path,
            rotate_by="none",
        )
        consumer.start()
        import time
        time.sleep(0.2)

        handler_names = [name for name, _ in consumer._handlers]
        assert "console" in handler_names
        assert "info" in handler_names
        consumer.stop()


def test_log_consumer_console_uses_json_format_when_configured():
    """Console handler should use JSON formatter when fmt='json'."""
    queue = mp.Queue()
    consumer = LogConsumer(
        queue=queue,
        level="INFO",
        fmt="json",
        info_output=None,
        error_output=None,
        rotate_by="none",
    )
    consumer.start()
    import time
    time.sleep(0.2)

    console_handler = next(h for name, h in consumer._handlers if name == "console")
    from light_server.logging.consumer import _JSONFormatter
    assert isinstance(console_handler.formatter, _JSONFormatter)
    consumer.stop()


def test_log_consumer_console_uses_text_format_when_configured():
    """Console handler should use plain text formatter when fmt='text'."""
    queue = mp.Queue()
    consumer = LogConsumer(
        queue=queue,
        level="INFO",
        fmt="text",
        info_output=None,
        error_output=None,
        rotate_by="none",
    )
    consumer.start()
    import time
    time.sleep(0.2)

    console_handler = next(h for name, h in consumer._handlers if name == "console")
    assert isinstance(console_handler.formatter, logging.Formatter)
    # Should NOT be JSON formatter
    from light_server.logging.consumer import _JSONFormatter
    assert not isinstance(console_handler.formatter, _JSONFormatter)
    consumer.stop()


def test_log_consumer_emits_to_console(capfd):
    """Records sent to queue should appear on console when consumer is running."""
    queue = mp.Queue()
    consumer = LogConsumer(
        queue=queue,
        level="INFO",
        fmt="text",
        info_output=None,
        error_output=None,
        rotate_by="none",
    )
    consumer.start()
    import time
    time.sleep(0.2)

    record = logging.LogRecord(
        name="console_test", level=logging.INFO, pathname="", lineno=0, msg="visible_on_console", args=(), exc_info=None
    )
    queue.put(record)
    time.sleep(0.3)
    consumer.stop()

    captured = capfd.readouterr()
    assert "visible_on_console" in captured.err


def test_setup_worker_logging_fallback_without_queue_uses_configured_format():
    """When log_queue is None, worker should still use the configured format (json or text)."""
    import io

    # Test JSON format fallback
    stream = io.StringIO()
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    root.handlers = []
    handler = logging.StreamHandler(stream)
    from light_server.logging.consumer import _JSONFormatter
    handler.setFormatter(_JSONFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    logging.getLogger("test").info("hello_json")
    output = stream.getvalue()
    root.handlers = old_handlers

    # Output should be valid JSON
    parsed = json.loads(output.strip())
    assert parsed["message"] == "hello_json"
