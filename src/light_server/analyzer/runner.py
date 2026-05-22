"""Analysis runner: orchestrate model loading, benchmarking, and reporting."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from light_server.analyzer.benchmark import BenchmarkEngine, BenchmarkResult
from light_server.analyzer.config_space import (
    AnalysisConfig,
    ConfigurationSpace,
    ModelRunConfig,
)
from light_server.analyzer.pareto import RunResult, find_pareto_frontier
from light_server.analyzer.report import AnalysisReport, ReportGenerator
from light_server.config import Config, ModelConfig, ModelRepositoryConfig, ServerConfig
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry
from litserve.transport.factory import TransportConfig, create_transport_from_config

logger = logging.getLogger(__name__)


class AnalysisRunner:
    """Run automatic configuration search for a model."""

    def __init__(self, repo_path: Path | str) -> None:
        self.repo_path = Path(repo_path)

    async def run(
        self,
        model_name: str,
        analysis_cfg: AnalysisConfig | None = None,
        output_dir: Path | str | None = None,
    ) -> AnalysisReport:
        """Run full analysis for a model and return the report."""
        if analysis_cfg is None:
            analysis_cfg = self._load_analysis_config(model_name)

        space = ConfigurationSpace(analysis_cfg)
        configs = space.iterate()
        logger.info(
            f"Analyzing {model_name}: {space.total_combinations} configurations"
        )

        results: list[RunResult] = []
        for cfg in configs:
            result = await self._benchmark_config(model_name, cfg, analysis_cfg)
            results.append(result)

        pareto = find_pareto_frontier(results, analysis_cfg.objectives)

        report = AnalysisReport(
            model=model_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_combinations=space.total_combinations,
            all_results=results,
            pareto_frontier=pareto,
        )

        if output_dir:
            self._save_report(report, Path(output_dir))

        return report

    def _load_analysis_config(self, model_name: str) -> AnalysisConfig:
        """Read analysis section from model_repo/{name}/model_config.yaml."""
        import yaml

        config_path = self.repo_path / model_name / "model_config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if "analysis" in data:
                return AnalysisConfig.from_dict(data["analysis"])

        # Default fallback
        return AnalysisConfig(
            batch_sizes=[1, 2, 4],
            workers_per_device=[1, 2],
            concurrency_levels=[1, 4, 8],
            duration_per_config=15.0,
        )

    async def _benchmark_config(
        self,
        model_name: str,
        run_cfg: ModelRunConfig,
        analysis_cfg: AnalysisConfig,
    ) -> RunResult:
        """Load model with a specific config, benchmark it, then unload."""
        manager = mp.Manager()
        registry = ModelRegistry(manager)

        transport_config = TransportConfig(transport_type="mp", num_consumers=1)
        transport_config.manager = manager
        transport = create_transport_from_config(transport_config)

        mm = ModelManager(
            repo_path=self.repo_path,
            registry=registry,
            transport=transport,
        )

        # Build ModelConfig override
        override = ModelConfig(
            name=model_name,
            max_batch_size=run_cfg.batch_size,
            workers_per_device=run_cfg.workers_per_device,
        )

        loaded = mm.load(model_name, version="1", config_override=override)
        if not loaded:
            logger.error(f"Failed to load {model_name} with config {run_cfg}")
            return RunResult(
                config=run_cfg,
                metrics=BenchmarkResult(failed_requests=1),
            )

        response_buffer: dict[str, Any] = {}
        consumer_task = asyncio.create_task(
            self._response_consumer(transport, response_buffer)
        )

        try:
            # Warmup: send real requests and wait for responses
            target = self._make_internal_target(
                mm, model_name, transport, response_buffer
            )
            for _ in range(analysis_cfg.warmup_requests):
                try:
                    await target(analysis_cfg.payload or {"input": 1.0})
                except Exception:
                    pass

            engine = BenchmarkEngine()
            metrics = await engine.run(
                target=target,
                payload=analysis_cfg.payload or {"input": 1.0},
                mode="fixed",
                concurrency=run_cfg.concurrency,
                duration=analysis_cfg.duration_per_config,
                warmup_requests=0,
            )
        finally:
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass
            mm.unload(model_name, version="1")
            manager.shutdown()

        return RunResult(config=run_cfg, metrics=metrics)

    @staticmethod
    async def _response_consumer(transport: Any, response_buffer: dict[str, Any]) -> None:
        """Consume responses from transport and signal waiting requests."""
        from litserve.utils import LitAPIStatus, ResponseBufferItem

        while True:
            try:
                result = await transport.areceive(consumer_id=0)
                if result is None:
                    continue
                uid, (response_data, status, _response_type, _worker_id) = result
                item = response_buffer.get(uid)
                if item is not None:
                    item.response = (response_data, status)
                    item.event.set()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    @staticmethod
    def _make_internal_target(
        mm: ModelManager,
        model_name: str,
        transport: Any,
        response_buffer: dict[str, Any],
    ) -> Any:
        """Create an async target that calls ModelManager.infer directly."""
        from litserve.utils import ResponseBufferItem

        async def target(payload: dict[str, Any]) -> dict[str, Any]:
            uid = mm.infer(model_name, payload)
            event = asyncio.Event()
            response_buffer[uid] = ResponseBufferItem(event=event)
            try:
                await asyncio.wait_for(event.wait(), timeout=30.0)
                item = response_buffer.pop(uid)
                response_data, status = item.response
                if status == LitAPIStatus.ERROR:
                    raise RuntimeError("Inference error")
                return response_data
            except asyncio.TimeoutError:
                response_buffer.pop(uid, None)
                raise TimeoutError("Inference timeout")

        return target

    def _save_report(self, report: AnalysisReport, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        base = output_dir / f"{report.model}_analysis"

        # JSON report
        json_path = base.with_suffix(".json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(ReportGenerator.to_json(report))
        logger.info(f"Saved JSON report: {json_path}")

        # Markdown report
        md_path = base.with_suffix(".md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(ReportGenerator.to_markdown(report))
        logger.info(f"Saved Markdown report: {md_path}")

        # Console summary
        print(ReportGenerator.to_console(report))
