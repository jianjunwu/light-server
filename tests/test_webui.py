"""Tests for Web UI components: store, metrics aggregator, and routes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from light_server.analyzer.benchmark import BenchmarkResult, LatencyDistribution
from light_server.config import Config, ServerConfig, WebUIConfig
from light_server.observability.collector import SystemMetrics
from light_server.webui.metrics_agg import MetricsAggregator
from light_server.webui.routes import create_ui_routes
from light_server.webui.store import BenchmarkReportStore


# ---------------------------------------------------------------------------
# BenchmarkReportStore tests
# ---------------------------------------------------------------------------

def test_store_save_and_list(tmp_path: Path):
    store = BenchmarkReportStore(cache_dir=tmp_path, retention_days=30)
    result = BenchmarkResult(
        total_requests=100,
        successful_requests=95,
        failed_requests=5,
        throughput=10.5,
        latency_ms=LatencyDistribution(p50=10, p90=20, p99=30, p99_9=40, mean=15, min=5, max=50),
        duration_seconds=10.0,
    )
    rid = store.save(result, model="m1", version="1", mode="fixed", concurrency=8, duration=10.0)
    assert rid

    reports = store.list()
    assert len(reports) == 1
    assert reports[0]["meta"]["model"] == "m1"
    assert reports[0]["result"]["throughput"] == 10.5


def test_store_get_and_delete(tmp_path: Path):
    store = BenchmarkReportStore(cache_dir=tmp_path)
    result = BenchmarkResult(total_requests=10, successful_requests=10, throughput=1.0)
    rid = store.save(result, model="m2", version="1", mode="fixed", concurrency=1, duration=1.0)

    report = store.get(rid)
    assert report is not None
    assert report["meta"]["model"] == "m2"

    assert store.delete(rid) is True
    assert store.get(rid) is None


def test_store_retention_purge(tmp_path: Path):
    store = BenchmarkReportStore(cache_dir=tmp_path, retention_days=1)
    result = BenchmarkResult(total_requests=1, successful_requests=1, throughput=1.0)
    rid = store.save(result, model="old", version="1", mode="fixed", concurrency=1, duration=1.0)
    assert store.get(rid) is not None

    # Manually age the report by changing its created_at to 2 days ago
    for path in tmp_path.glob("*.json"):
        import json
        data = json.loads(path.read_text())
        from datetime import datetime, timezone, timedelta
        data["meta"]["created_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        path.write_text(json.dumps(data))

    # Save another report to trigger purge
    rid2 = store.save(result, model="new", version="1", mode="fixed", concurrency=1, duration=1.0)
    # First report should be purged (created_at older than 1 day)
    assert store.get(rid) is None
    assert store.get(rid2) is not None


def test_store_cleanup_manual(tmp_path: Path):
    store = BenchmarkReportStore(cache_dir=tmp_path, retention_days=1)
    result = BenchmarkResult(total_requests=1, successful_requests=1, throughput=1.0)
    store.save(result, model="x", version="1", mode="fixed", concurrency=1, duration=1.0)
    # Manually age the report by changing created_at
    for path in tmp_path.glob("*.json"):
        data = json.loads(path.read_text())
        from datetime import datetime, timezone, timedelta
        data["meta"]["created_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        path.write_text(json.dumps(data))
    removed = store.cleanup()
    assert removed >= 1


# ---------------------------------------------------------------------------
# MetricsAggregator tests
# ---------------------------------------------------------------------------

def test_metrics_aggregator_empty():
    registry = MagicMock()
    sm = SystemMetrics(registry)
    agg = MetricsAggregator(sm)
    data = agg.get_model_metrics("model1", "1")
    assert data is not None
    assert data["qps"] == 0.0
    assert data["p50_ms"] == 0.0


def test_metrics_aggregator_with_requests():
    registry = MagicMock()
    sm = SystemMetrics(registry)
    agg = MetricsAggregator(sm)

    # Simulate some requests
    for i in range(10):
        sm.record_request_start("model1", "1", f"req-{i}")
        sm.record_request_end("model1", "1", "2xx", f"req-{i}")

    data = agg.get_model_metrics("model1", "1")
    assert data["qps"] >= 0.0
    assert data["p50_ms"] >= 0.0
    assert data["avg_ms"] >= 0.0


# ---------------------------------------------------------------------------
# UI Routes tests
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_state(tmp_path: Path):
    """Create a minimal HTTPState for route testing."""
    from light_server.http.state import HTTPState

    config = Config(
        server=ServerConfig(http_port=18000),
        webui=WebUIConfig(enabled=True, report_retention_days=7),
    )
    registry = MagicMock()
    registry.list_loaded.return_value = []
    registry.list_versions.return_value = []
    registry.get_active_version.return_value = None
    registry.is_ready.return_value = False

    transport = MagicMock()

    state = HTTPState(
        registry=registry,
        transport=transport,
        config=config,
        response_queue_id=0,
        repo_path=tmp_path,
    )
    state._system_metrics = MagicMock()
    state.list_repository = MagicMock(return_value=[])

    async def _return_true(*args, **kwargs):
        return True

    async def _return_none(*args, **kwargs):
        return None

    state.load_model = _return_true
    state.unload_model = _return_none
    state.activate_model = _return_true
    return state


@pytest.fixture
def mock_dist(tmp_path: Path):
    """Create a temporary dist directory for SPA fallback testing."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>SPA</body></html>")
    (dist_dir / "assets").mkdir()
    (dist_dir / "assets" / "app.js").write_text("console.log('app')")
    return dist_dir


def test_ui_dashboard_page(mock_state, mock_dist):
    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_ui_repository_page(mock_state, mock_dist):
    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)
    resp = client.get("/ui/repository")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_ui_benchmarks_page(mock_state, mock_dist):
    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)
    resp = client.get("/ui/benchmarks")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_ui_config_page(mock_state, mock_dist):
    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)
    resp = client.get("/ui/config")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_ui_api_config_get(mock_state, mock_dist):
    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)
    resp = client.get("/ui/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "server" in data
    assert "webui" in data


def test_ui_api_reports_empty(mock_state, mock_dist):
    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)
    resp = client.get("/ui/api/reports")
    assert resp.status_code == 200
    data = resp.json()
    assert data["reports"] == []


def test_ui_static_files(mock_state, mock_dist):
    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)
    resp = client.get("/ui/static/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_ui_api_metrics_summary(mock_state, mock_dist):
    mock_state.list_repository.return_value = [
        {"name": "test_model", "version": "1", "type": "litapi"},
    ]
    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)
    resp = client.get("/ui/api/metrics/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "models" in data
    assert any(m["name"] == "test_model" for m in data["models"])


def test_ui_api_model_load_unload(mock_state, mock_dist):
    from unittest.mock import AsyncMock

    mock_state.load_model = AsyncMock(return_value=True)
    mock_state.unload_model = AsyncMock(return_value=True)

    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)

    resp = client.post("/ui/api/models/test_model/load")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True

    resp = client.post("/ui/api/models/test_model/unload")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_ui_artifact_upload_invalid_extension(mock_state, mock_dist):
    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)
    resp = client.post(
        "/ui/api/artifacts/upload",
        files={"file": ("bad.txt", b"not an lma", "text/plain")},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "detail" in data


def test_ui_config_save(mock_state, mock_dist, tmp_path: Path):
    config_path = tmp_path / "test_config.yaml"
    config_path.write_text("server:\n  http_port: 8000\n")
    mock_state._config_path = str(config_path)

    app = FastAPI()
    create_ui_routes(app, mock_state, dist_dir=mock_dist)
    client = TestClient(app)

    payload = {
        "server": {
            "http_port": 9000,
            "grpc_port": 8001,
            "metrics_port": 8002,
            "host": "127.0.0.1",
            "accelerator": "cpu",
            "devices": 1,
            "workers_per_device": 2,
            "timeout": 60.0,
            "log_level": "debug",
        },
        "grpc": {"enabled": True, "max_workers": 5},
        "metrics": {"enabled": True},
        "logging": {
            "format": "text",
            "rotate_by": "size",
            "max_size": 200,
            "when": "midnight",
            "backup_count": 14,
        },
        "model_repository": {
            "path": "./models",
            "control_mode": "poll",
            "poll_interval": 10,
        },
        "webui": {"enabled": True, "report_retention_days": 60},
        "load_models": [],
    }

    resp = client.post("/ui/api/config", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True

    # Verify file was written
    saved = config_path.read_text()
    assert "9000" in saved
    assert "127.0.0.1" in saved
