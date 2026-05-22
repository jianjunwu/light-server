"""Benchmark report storage with M-day retention."""

from __future__ import annotations

import json
import shutil
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from light_server.analyzer.benchmark import BenchmarkResult


@dataclass
class ReportMeta:
    """Metadata for a stored benchmark report."""

    id: str
    created_at: str
    model: str
    version: str
    mode: str
    concurrency: int
    duration: float


class BenchmarkReportStore:
    """Store benchmark reports on disk with M-day retention."""

    def __init__(self, cache_dir: Path | None = None, retention_days: int = 30) -> None:
        self._cache_dir = cache_dir or Path.home() / ".light_server" / "reports"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days

    def save(
        self,
        result: BenchmarkResult,
        model: str,
        version: str,
        mode: str,
        concurrency: int,
        duration: float,
    ) -> str:
        """Save a benchmark result and return report id."""
        now = datetime.now(timezone.utc)
        report_id = now.strftime("%Y%m%d_%H%M%S_%f")
        meta = ReportMeta(
            id=report_id,
            created_at=now.isoformat(),
            model=model,
            version=version,
            mode=mode,
            concurrency=concurrency,
            duration=duration,
        )
        data = {
            "meta": asdict(meta),
            "result": {
                "total_requests": result.total_requests,
                "successful_requests": result.successful_requests,
                "failed_requests": result.failed_requests,
                "throughput": result.throughput,
                "duration_seconds": result.duration_seconds,
                "latency_ms": asdict(result.latency_ms),
                "errors": result.errors,
            },
        }
        path = self._cache_dir / f"{report_id}_{model}_{version}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self._purge_expired()
        return report_id

    def list(self, model: str | None = None) -> list[dict[str, Any]]:
        """List all reports, optionally filtered by model name."""
        reports: list[dict[str, Any]] = []
        for path in sorted(self._cache_dir.glob("*.json"), reverse=True):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if model is None or data.get("meta", {}).get("model") == model:
                    reports.append(data)
            except Exception:
                continue
        return reports

    def get(self, report_id: str) -> dict[str, Any] | None:
        """Get a single report by id."""
        for path in self._cache_dir.glob(f"{report_id}_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                continue
        return None

    def delete(self, report_id: str) -> bool:
        """Delete a report by id."""
        for path in self._cache_dir.glob(f"{report_id}_*.json"):
            try:
                path.unlink()
                return True
            except Exception:
                continue
        return False

    def cleanup(self) -> int:
        """Manually trigger expired report cleanup."""
        return self._purge_expired()

    def _purge_expired(self) -> int:
        """Remove reports older than retention_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        removed = 0
        for path in self._cache_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                created = datetime.fromisoformat(data["meta"]["created_at"])
                if created < cutoff:
                    path.unlink()
                    removed += 1
            except Exception:
                continue
        return removed
