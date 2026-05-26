"""Web UI routes for Light Server."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from light_server.analyzer.benchmark import BenchmarkEngine, HttpBenchmarkTarget
from light_server.config import Config, load_config
from light_server.webui.metrics_agg import MetricsAggregator
from light_server.webui.store import BenchmarkReportStore

logger = logging.getLogger(__name__)

# In-memory job store for benchmark progress
_job_store: dict[str, dict[str, Any]] = {}
_benchmark_running = False


def create_ui_routes(app: FastAPI, state: Any, dist_dir: Path | None = None) -> None:
    """Register Web UI routes and static files on the FastAPI app."""
    if dist_dir is None:
        dist_dir = Path(__file__).parent / "static" / "dist"
    app.mount("/ui/static", StaticFiles(directory=str(dist_dir)), name="ui_static")

    report_store = BenchmarkReportStore(
        retention_days=state.config.webui.report_retention_days
    )
    metrics_agg = MetricsAggregator(state.system_metrics)

    # ------------------------------------------------------------------
    # Helper: build dashboard model list
    # ------------------------------------------------------------------
    def _build_dashboard_models() -> list[dict[str, Any]]:
        loaded = {e["name"]: e for e in state.registry.list_loaded()}
        available = state.list_repository()
        models: list[dict[str, Any]] = []
        seen = set()
        for m in available:
            name = m["name"]
            if name in seen:
                continue
            seen.add(name)
            entry = loaded.get(name, {})
            status = entry.get("status", "NOT_LOADED")
            version = entry.get("version", m.get("version", "1"))
            model_type = entry.get("model_type", "litapi")
            active = state.registry.get_active_version(name)
            config = entry.get("config", {})
            stream = config.get("stream", False)
            bidirectional = config.get("bidirectional", False)
            workers = 0
            if status == "READY":
                try:
                    workers = int(state.system_metrics.active_workers.labels(model=name, version=version)._value.get())
                except Exception:
                    pass
            # Get metrics for active version
            qps = p99_ms = queue_depth = 0
            if status == "READY" and active:
                metrics = metrics_agg.get_model_metrics(name, active)
                if metrics:
                    qps = metrics.get("qps", 0)
                    p99_ms = metrics.get("p99_ms", 0)
                    queue_depth = metrics.get("queue_depth", 0)
            models.append({
                "name": name,
                "status": status,
                "version": version,
                "model_type": model_type,
                "active_version": active,
                "workers": workers,
                "qps": qps,
                "p99_ms": p99_ms,
                "queue_depth": queue_depth,
                "stream": stream,
                "bidirectional": bidirectional,
            })
        return models

    # ------------------------------------------------------------------
    # API: Metrics
    # ------------------------------------------------------------------
    @app.get("/ui/api/metrics/summary")
    async def api_metrics_summary() -> JSONResponse:
        models = _build_dashboard_models()
        return JSONResponse({"models": models})

    @app.get("/ui/api/metrics/{model}/{version}")
    async def api_model_metrics(model: str, version: str) -> JSONResponse:
        data = metrics_agg.get_model_metrics(model, version) or {}
        return JSONResponse(data)

    # ------------------------------------------------------------------
    # API: Repository / Artifact Upload
    # ------------------------------------------------------------------
    @app.post("/ui/api/artifacts/upload")
    async def api_upload_artifact(
        request: Request,
        file: UploadFile,
        verify_signature: bool = Form(False),
    ) -> JSONResponse:
        if not file.filename or not file.filename.endswith(".lma"):
            raise HTTPException(status_code=400, detail="Invalid file. Must be .lma")
        import tempfile
        import shutil
        from light_server.artifact.unpacker import ModelUnpacker

        with tempfile.NamedTemporaryFile(delete=False, suffix=".lma") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            unpacker = ModelUnpacker(tmp_path)
            public_key: bytes | None = None
            if verify_signature:
                # TODO: read verify_key from config if provided
                pass
            manifest = unpacker.validate(public_key_pem=public_key)

            # Security: sanitize filename to prevent path traversal
            safe_name = Path(file.filename).name
            if ".." in safe_name or "/" in safe_name or "\\" in safe_name or not safe_name.endswith(".lma"):
                raise HTTPException(status_code=400, detail="Invalid filename")
            dest = Path(state.config.model_repository.path) / safe_name
            shutil.copy2(tmp_path, dest)
            return JSONResponse({
                "success": True,
                "name": manifest.name,
                "version": manifest.version,
            })
        except Exception as e:
            logger.exception("Artifact upload failed")
            raise HTTPException(status_code=400, detail=f"Upload failed: {e}")
        finally:
            tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # API: Model Load / Unload / Activate
    # ------------------------------------------------------------------
    @app.post("/ui/api/models/{model_name}/load")
    async def api_load_model(
        request: Request,
        model_name: str,
        version: str = Query("1"),
    ) -> JSONResponse:
        success = await state.load_model(model_name, version=version)
        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to load {model_name}")
        models = _build_dashboard_models()
        return JSONResponse({"success": True, "models": models})

    @app.post("/ui/api/models/{model_name}/unload")
    async def api_unload_model(
        request: Request,
        model_name: str,
        version: str | None = Query(None),
    ) -> JSONResponse:
        await state.unload_model(model_name, version=version)
        models = _build_dashboard_models()
        return JSONResponse({"success": True, "models": models})

    @app.post("/ui/api/models/{model_name}/versions/{version}/activate")
    async def api_activate_version(
        request: Request,
        model_name: str,
        version: str,
    ) -> JSONResponse:
        success = await state.activate_model(model_name, version)
        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to activate {model_name} v{version}")
        return JSONResponse({"success": True})

    # ------------------------------------------------------------------
    # API: Benchmarks
    # ------------------------------------------------------------------
    @app.post("/ui/api/benchmarks")
    async def api_create_benchmark(
        request: Request,
        model: str = Form(),
        version: str = Form("1"),
        mode: str = Form("fixed"),
        concurrency: int = Form(8),
        duration: float = Form(30.0),
        payload: str = Form('{"input": 1.0}'),
        protocol: str = Form("http"),
    ) -> JSONResponse:
        global _benchmark_running
        if _benchmark_running:
            raise HTTPException(status_code=429, detail="Another benchmark is already running.")
        _benchmark_running = True
        job_id = f"bm_{asyncio.get_event_loop().time()}"
        _job_store[job_id] = {"status": "queued", "progress": 0}

        asyncio.create_task(
            _run_benchmark_job(
                job_id=job_id,
                model=model,
                version=version,
                mode=mode,
                concurrency=concurrency,
                duration=duration,
                payload=payload,
                protocol=protocol,
                server=state,
                store=report_store,
            )
        )

        return JSONResponse({"job_id": job_id})

    @app.get("/ui/api/benchmarks/{job_id}/status")
    async def api_benchmark_status(job_id: str) -> JSONResponse:
        job = _job_store.get(job_id, {"status": "unknown", "progress": 0})
        status = job.get("status", "unknown")
        progress = job.get("progress", 0)
        result: dict[str, Any] = {"status": status, "progress": progress}
        if status == "completed":
            result["report_id"] = job.get("report_id", "")
        if status == "failed":
            result["error"] = job.get("error", "Unknown error")
        return JSONResponse(result)

    # ------------------------------------------------------------------
    # API: Reports
    # ------------------------------------------------------------------
    @app.get("/ui/api/reports")
    async def api_list_reports(model: str | None = Query(None)) -> JSONResponse:
        return JSONResponse({"reports": report_store.list(model)})

    @app.get("/ui/api/reports/{report_id}")
    async def api_get_report(report_id: str) -> JSONResponse:
        report = report_store.get(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found")
        return JSONResponse(report)

    @app.delete("/ui/api/reports/{report_id}")
    async def api_delete_report(report_id: str) -> JSONResponse:
        success = report_store.delete(report_id)
        return JSONResponse({"success": success})

    @app.post("/ui/api/reports/cleanup")
    async def api_cleanup_reports() -> JSONResponse:
        removed = report_store.cleanup()
        return JSONResponse({"removed": removed})

    # ------------------------------------------------------------------
    # API: Config
    # ------------------------------------------------------------------
    @app.get("/ui/api/config")
    async def api_get_config() -> JSONResponse:
        return JSONResponse(_config_to_dict(state.config))

    @app.post("/ui/api/config")
    async def api_save_config(payload: Config) -> JSONResponse:
        try:
            config_path = getattr(state, "_config_path", None)
            if config_path is None:
                config_path = Path("server.yaml")
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(_config_to_dict(payload), f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            return JSONResponse({"success": True})
        except Exception as e:
            logger.exception("Config save failed")
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # SPA fallback: all /ui/* routes serve index.html
    # ------------------------------------------------------------------
    @app.get("/ui/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        index = dist_dir / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="UI not built")
        return FileResponse(str(index))


# ------------------------------------------------------------------
# Benchmark runner (background task)
# ------------------------------------------------------------------
async def _run_benchmark_job(
    job_id: str,
    model: str,
    version: str,
    mode: str,
    concurrency: int,
    duration: float,
    payload: str,
    protocol: str,
    state: Any,
    store: BenchmarkReportStore,
) -> None:
    global _benchmark_running
    target = None
    try:
        _job_store[job_id] = {"status": "running", "progress": 5}
        port = state.config.server.http_port
        parsed_payload = json.loads(payload) if payload else {"input": 1.0}

        if protocol == "websocket":
            from light_server.analyzer.benchmark import StreamingBenchmarkEngine, WebSocketStreamingTarget
            target = WebSocketStreamingTarget(
                base_url=f"http://127.0.0.1:{port}",
                model_name=model,
                version=version if version != "1" else None,
            )
            engine = StreamingBenchmarkEngine()
            result = await engine.run(
                target=target,
                payload=parsed_payload,
                mode=mode,  # type: ignore[arg-type]
                concurrency=concurrency,
                duration=duration,
            )
        else:
            target = HttpBenchmarkTarget(
                base_url=f"http://127.0.0.1:{port}",
                model_name=model,
                version=version if version != "1" else None,
            )
            _job_store[job_id]["progress"] = 10
            engine = BenchmarkEngine()
            result = await engine.run(
                target=target,
                payload=parsed_payload,
                mode=mode,  # type: ignore[arg-type]
                concurrency=concurrency,
                duration=duration,
            )

        _job_store[job_id]["progress"] = 90
        report_id = store.save(
            result=result,
            model=model,
            version=version,
            mode=mode,
            concurrency=concurrency,
            duration=duration,
        )
        _job_store[job_id] = {
            "status": "completed",
            "progress": 100,
            "report_id": report_id,
        }
    except Exception as e:
        logger.exception(f"Benchmark job {job_id} failed")
        _job_store[job_id] = {"status": "failed", "error": str(e)}
    finally:
        _benchmark_running = False
        if target is not None:
            try:
                await target.close()
            except Exception:
                pass


# ------------------------------------------------------------------
# Config serialization helper
# ------------------------------------------------------------------
def _config_to_dict(cfg: Config) -> dict[str, Any]:
    """Convert Config dataclass to a plain dict for YAML serialization."""
    return asdict(cfg)
