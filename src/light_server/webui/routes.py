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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from light_server.analyzer.benchmark import BenchmarkEngine, HttpBenchmarkTarget
from light_server.config import (
    Config,
    GrpcConfig,
    LoggingConfig,
    MetricsConfig,
    ModelRepositoryConfig,
    ServerConfig,
    WebUIConfig,
)
from light_server.webui.metrics_agg import MetricsAggregator
from light_server.webui.store import BenchmarkReportStore

logger = logging.getLogger(__name__)

# In-memory job store for benchmark progress
_job_store: dict[str, dict[str, Any]] = {}
_benchmark_running = False

def _get_templates() -> Jinja2Templates:
    tpl_dir = Path(__file__).parent / "templates"
    return Jinja2Templates(directory=str(tpl_dir))


def create_ui_routes(app: FastAPI, state: Any) -> None:
    """Register Web UI routes and static files on the FastAPI app."""
    static_dir = Path(__file__).parent / "static"
    app.mount("/ui/static", StaticFiles(directory=str(static_dir)), name="ui_static")

    tpl = _get_templates()
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
    # Page: Dashboard
    # ------------------------------------------------------------------
    @app.get("/ui/", response_class=HTMLResponse)
    async def page_dashboard(request: Request) -> HTMLResponse:
        is_htmx = request.headers.get("HX-Request") == "true"
        models = _build_dashboard_models()
        if is_htmx:
            return tpl.TemplateResponse(request, "dashboard_cards.html", {
            "models": models
        })
        return tpl.TemplateResponse(request, "dashboard.html", {
            "active_page": "dashboard",
            "models": models
        })

    # ------------------------------------------------------------------
    # Page: Model Detail
    # ------------------------------------------------------------------
    @app.get("/ui/models/{model_name}", response_class=HTMLResponse)
    async def page_model_detail(request: Request, model_name: str) -> HTMLResponse:
        is_htmx = request.headers.get("HX-Request") == "true"
        versions = state.registry.list_versions(model_name)
        active = state.registry.get_active_version(model_name)
        # Also include available versions from repo
        available = state.list_repository()
        seen_versions = {v["version"] for v in versions}
        for a in available:
            if a["name"] == model_name and a["version"] not in seen_versions:
                versions.append({
                    "version": a["version"],
                    "status": "NOT_LOADED",
                    "model_type": a.get("type", "litapi"),
                    "workers": 0,
                })
        metrics = metrics_agg.get_model_metrics(model_name, active or "1") or {}
        if is_htmx:
            return tpl.TemplateResponse(request, "model_detail.html", {
            "model_name": model_name,
                "versions": versions,
                "active_version": active,
                "metrics": metrics
        })
        return tpl.TemplateResponse(request, "model_detail.html", {
            "active_page": "dashboard",
            "model_name": model_name,
            "versions": versions,
            "active_version": active,
            "metrics": metrics
        })

    # ------------------------------------------------------------------
    # Page: Repository
    # ------------------------------------------------------------------
    @app.get("/ui/repository", response_class=HTMLResponse)
    async def page_repository(request: Request) -> HTMLResponse:
        is_htmx = request.headers.get("HX-Request") == "true"
        repo_models = state.list_repository()
        if is_htmx:
            return tpl.TemplateResponse(request, "repository.html", {
            "repo_models": repo_models
        })
        return tpl.TemplateResponse(request, "repository.html", {
            "active_page": "repository",
            "repo_models": repo_models
        })

    # ------------------------------------------------------------------
    # Page: Benchmarks
    # ------------------------------------------------------------------
    @app.get("/ui/benchmarks", response_class=HTMLResponse)
    async def page_benchmarks(request: Request) -> HTMLResponse:
        reports = report_store.list()
        return tpl.TemplateResponse(request, "benchmark_list.html", {
            "active_page": "benchmarks",
            "reports": reports
        })

    @app.get("/ui/benchmarks/new", response_class=HTMLResponse)
    async def page_benchmark_new(request: Request) -> HTMLResponse:
        models = state.registry.list_loaded()
        return tpl.TemplateResponse(request, "benchmark_form.html", {
            "active_page": "benchmarks",
            "models": models
        })

    @app.get("/ui/benchmarks/{report_id}", response_class=HTMLResponse)
    async def page_benchmark_detail(request: Request, report_id: str) -> HTMLResponse:
        report = report_store.get(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found")
        return tpl.TemplateResponse(request, "benchmark_detail.html", {
            "active_page": "benchmarks",
            "report": report
        })

    # ------------------------------------------------------------------
    # Page: Config
    # ------------------------------------------------------------------
    @app.get("/ui/config", response_class=HTMLResponse)
    async def page_config(request: Request, saved: bool = False, error: str = "") -> HTMLResponse:
        return tpl.TemplateResponse(request, "config_edit.html", {
            "active_page": "config",
            "cfg": state.config,
            "saved": saved,
            "error": error
        })

    # ------------------------------------------------------------------
    # API: Metrics
    # ------------------------------------------------------------------
    @app.get("/ui/api/metrics/summary")
    async def api_metrics_summary(request: Request) -> HTMLResponse:
        models = _build_dashboard_models()
        return tpl.TemplateResponse(request, "dashboard_cards.html", {
            "models": models
        })

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
    ) -> HTMLResponse:
        if not file.filename or not file.filename.endswith(".lma"):
            return HTMLResponse(content="<span style='color:#991b1b;'>Invalid file. Must be .lma</span>", status_code=400)
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
                return HTMLResponse(
                    content="<span style='color:#991b1b;'>Invalid filename</span>",
                    status_code=400,
                )
            dest = Path(state.config.model_repository.path) / safe_name
            shutil.copy2(tmp_path, dest)
            return HTMLResponse(
                content=f"<span style='color:#166534;'>Uploaded {manifest.name} v{manifest.version}</span>"
            )
        except Exception as e:
            return HTMLResponse(content=f"<span style='color:#991b1b;'>Upload failed: {e}</span>", status_code=400)
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
    ) -> HTMLResponse:
        success = await state.load_model(model_name, version=version)
        if not success:
            return HTMLResponse(content=f"<span style='color:#991b1b;'>Failed to load {model_name}</span>", status_code=400)
        models = _build_dashboard_models()
        return tpl.TemplateResponse(request, "dashboard_cards.html", {
            "models": models
        })

    @app.post("/ui/api/models/{model_name}/unload")
    async def api_unload_model(
        request: Request,
        model_name: str,
        version: str | None = Query(None),
    ) -> HTMLResponse:
        await state.unload_model(model_name, version=version)
        models = _build_dashboard_models()
        return tpl.TemplateResponse(request, "dashboard_cards.html", {
            "models": models
        })

    @app.post("/ui/api/models/{model_name}/versions/{version}/activate")
    async def api_activate_version(
        request: Request,
        model_name: str,
        version: str,
    ) -> HTMLResponse:
        success = await state.activate_model(model_name, version)
        if not success:
            return HTMLResponse(content=f"<span style='color:#991b1b;'>Failed to activate {model_name} v{version}</span>", status_code=400)
        return RedirectResponse(url=f"/ui/models/{model_name}", status_code=302)

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
    ) -> HTMLResponse:
        global _benchmark_running
        if _benchmark_running:
            return HTMLResponse(
                content="<span style='color:#991b1b;'>Another benchmark is already running.</span>",
                status_code=429,
            )
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

        return HTMLResponse(
            content=f"""
            <div hx-get="/ui/api/benchmarks/{job_id}/status"
                 hx-trigger="every 2s"
                 hx-swap="innerHTML">
              <p>Benchmark started...</p>
              <div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>
            </div>
            """
        )

    @app.get("/ui/api/benchmarks/{job_id}/status")
    async def api_benchmark_status(job_id: str) -> HTMLResponse:
        job = _job_store.get(job_id, {"status": "unknown", "progress": 0})
        status = job.get("status", "unknown")
        progress = job.get("progress", 0)
        if status == "completed":
            report_id = job.get("report_id", "")
            return HTMLResponse(
                content=f"""
                <p style="color:#166534;">Benchmark completed!</p>
                <a href="/ui/benchmarks/{report_id}" role="button">View Report</a>
                """
            )
        if status == "failed":
            error = job.get("error", "Unknown error")
            return HTMLResponse(
                content=f"""<p style="color:#991b1b;">Benchmark failed: {error}</p>
                <div class="progress-bar"><div class="progress-fill" style="width:100%"></div></div>
                """
            )
        return HTMLResponse(
            content=f"""
            <p>Running... {progress}%</p>
            <div class="progress-bar"><div class="progress-fill" style="width:{progress}%"></div></div>
            """
        )

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
    async def api_save_config(
        request: Request,
        http_port: int = Form(8000),
        grpc_port: int = Form(8001),
        metrics_port: int = Form(8002),
        host: str = Form("0.0.0.0"),
        accelerator: str = Form("auto"),
        devices: str = Form("auto"),
        workers_per_device: int = Form(1),
        timeout: float = Form(30.0),
        log_level: str = Form("info"),
        grpc_enabled: bool = Form(False),
        grpc_max_workers: int = Form(10),
        metrics_enabled: bool = Form(False),
        log_format: str = Form("json"),
        log_rotate_by: str = Form("none"),
        log_max_size: int = Form(100),
        log_when: str = Form("midnight"),
        log_backup_count: int = Form(7),
        repo_path: str = Form("./model_repo"),
        control_mode: str = Form("explicit"),
        poll_interval: int = Form(5),
        webui_enabled: bool = Form(False),
        report_retention_days: int = Form(30),
        load_models: list[str] = Form(default_factory=list),
    ) -> HTMLResponse:
        try:
            new_cfg = Config(
                server=ServerConfig(
                    http_port=http_port,
                    grpc_port=grpc_port,
                    metrics_port=metrics_port,
                    host=host,
                    accelerator=accelerator,
                    devices=devices,
                    workers_per_device=workers_per_device,
                    timeout=timeout,
                    log_level=log_level,
                ),
                grpc=GrpcConfig(
                    enabled=grpc_enabled,
                    max_workers=grpc_max_workers,
                ),
                metrics=MetricsConfig(
                    enabled=metrics_enabled,
                ),
                logging=LoggingConfig(
                    format=log_format,
                    rotate_by=log_rotate_by,
                    max_size=log_max_size,
                    when=log_when,
                    backup_count=log_backup_count,
                ),
                model_repository=ModelRepositoryConfig(
                    path=repo_path,
                    control_mode=control_mode,
                    poll_interval=poll_interval,
                ),
                webui=WebUIConfig(
                    enabled=webui_enabled,
                    report_retention_days=report_retention_days,
                ),
                load_models=load_models,
            )
            # Write back to the original config file if known
            config_path = getattr(state, "_config_path", None)
            if config_path is None:
                config_path = Path("server.yaml")
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(_config_to_dict(new_cfg), f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            return RedirectResponse(url="/ui/config?saved=1", status_code=302)
        except Exception as e:
            logger.exception("Config save failed")
            return RedirectResponse(url=f"/ui/config?error={str(e)}", status_code=302)


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
