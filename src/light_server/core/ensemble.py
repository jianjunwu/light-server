"""Ensemble DAG parser and async executor for model pipeline orchestration."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from light_server.core.exceptions import EnsembleError, InferenceTimeoutError, ModelNotReadyError
from litserve.utils import LitAPIStatus, ResponseBufferItem

if TYPE_CHECKING:
    from light_server.http.state import HTTPState

logger = logging.getLogger(__name__)

_REF_RE = re.compile(r"^\$(\w+)(?:\.(\w+))?$")


@dataclass
class EnsembleStep:
    """A single step in an ensemble pipeline."""

    name: str
    model: str
    version: str
    inputs: dict[str, str] = field(default_factory=dict)


@dataclass
class EnsembleConfig:
    """Parsed ensemble configuration."""

    steps: list[EnsembleStep]


class EnsembleParserError(ValueError):
    """Raised when ensemble configuration is invalid."""


class EnsembleParser:
    """Parse ensemble config from a dict and validate DAG structure."""

    @staticmethod
    def parse(config: dict[str, Any]) -> EnsembleConfig:
        """Parse ensemble block from a version config.yaml dict."""
        ensemble_block = config.get("ensemble")
        if ensemble_block is None:
            raise EnsembleParserError("Missing 'ensemble' key in config")

        raw_steps = ensemble_block.get("steps", [])
        if not raw_steps:
            raise EnsembleParserError("Ensemble has no steps")

        steps = []
        for i, raw in enumerate(raw_steps):
            name = raw.get("name")
            if not name:
                raise EnsembleParserError(f"Step {i}: missing 'name'")
            model = raw.get("model")
            if not model:
                raise EnsembleParserError(f"Step '{name}': missing 'model'")
            version = str(raw.get("version", "1"))
            inputs = raw.get("inputs", {})
            if not isinstance(inputs, dict):
                raise EnsembleParserError(f"Step '{name}': 'inputs' must be a dict")
            steps.append(EnsembleStep(name=name, model=model, version=version, inputs=inputs))

        # Validate unique step names
        names = [s.name for s in steps]
        if len(names) != len(set(names)):
            raise EnsembleParserError("Duplicate step names in ensemble")

        # Validate DAG (no cycles, all references resolve)
        EnsembleParser._validate_dag(steps)

        return EnsembleConfig(steps=steps)

    @staticmethod
    def _validate_dag(steps: list[EnsembleStep]) -> None:
        """Check for cycles and unresolved references."""
        step_names = {s.name for s in steps}
        dependencies: dict[str, set[str]] = {s.name: set() for s in steps}

        for step in steps:
            for ref in step.inputs.values():
                match = _REF_RE.match(ref)
                if not match:
                    raise EnsembleParserError(
                        f"Step '{step.name}': invalid reference '{ref}'"
                    )
                source = match.group(1)
                if source == "request":
                    continue
                if source not in step_names:
                    raise EnsembleParserError(
                        f"Step '{step.name}': references unknown step '{source}'"
                    )
                dependencies[step.name].add(source)

        # Cycle detection (Kahn)
        in_degree = {s.name: len(dependencies[s.name]) for s in steps}

        queue = [n for n, d in in_degree.items() if d == 0]
        visited = 0
        while queue:
            node = queue.pop(0)
            visited += 1
            for step in steps:
                if node in dependencies[step.name]:
                    in_degree[step.name] -= 1
                    if in_degree[step.name] == 0:
                        queue.append(step.name)

        if visited != len(steps):
            raise EnsembleParserError("Cycle detected in ensemble DAG")

    @staticmethod
    def topological_layers(steps: list[EnsembleStep]) -> list[list[EnsembleStep]]:
        """Return steps grouped into layers where each layer has no inter-dependencies."""
        dependencies: dict[str, set[str]] = {s.name: set() for s in steps}
        for step in steps:
            for ref in step.inputs.values():
                match = _REF_RE.match(ref)
                if match:
                    source = match.group(1)
                    if source != "request":
                        dependencies[step.name].add(source)

        step_map = {s.name: s for s in steps}
        in_degree = {s.name: len(dependencies[s.name]) for s in steps}

        layers: list[list[EnsembleStep]] = []
        remaining = {s.name for s in steps}

        while remaining:
            layer = [step_map[n] for n in remaining if in_degree[n] == 0]
            if not layer:
                raise EnsembleParserError("Cycle detected in ensemble DAG")
            layers.append(layer)
            for step in layer:
                remaining.remove(step.name)
                for other in remaining:
                    if step.name in dependencies[other]:
                        in_degree[other] -= 1

        return layers


class EnsembleExecutor:
    """Async executor that runs ensemble steps in topological order."""

    async def execute(
        self,
        state: HTTPState,
        ensemble_config: EnsembleConfig,
        request_payload: dict[str, Any],
        ensemble_name: str = "unknown",
    ) -> dict[str, Any]:
        """Execute all steps and return the final step's output."""
        layers = EnsembleParser.topological_layers(ensemble_config.steps)
        context: dict[str, Any] = {"request": request_payload}

        for layer in layers:
            # Execute independent steps in parallel
            coros = [
                self._execute_step(state, step, context, ensemble_name)
                for step in layer
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            for step, result in zip(layer, results):
                if isinstance(result, Exception):
                    raise EnsembleError(
                        f"Ensemble step '{step.name}' failed: {result}"
                    ) from result
                context[step.name] = result

        # Return the last step's output
        last_step = ensemble_config.steps[-1]
        return context[last_step.name]

    async def _execute_step(
        self,
        state: HTTPState,
        step: EnsembleStep,
        context: dict[str, Any],
        ensemble_name: str,
    ) -> dict[str, Any]:
        """Run a single step: build payload, infer, await response."""
        from light_server.core.model_manager import submit_infer

        start = time.time()
        try:
            # Resolve input references
            payload: dict[str, Any] = {}
            for key, ref in step.inputs.items():
                payload[key] = self._resolve_ref(ref, context)

            # Ensure sub-model is ready
            if not state.registry.is_ready(step.model, step.version):
                # Try auto-load
                loaded = await state.load_model(step.model, step.version)
                if loaded:
                    # Brief wait for worker startup (best-effort)
                    await asyncio.sleep(1.5)

            if not state.registry.is_ready(step.model, step.version):
                raise ModelNotReadyError(
                    f"Sub-model {step.model} v{step.version} is not ready"
                )

            # Submit inference
            uid = submit_infer(
                state.registry,
                state.shm_buffer,
                state.system_metrics,
                step.model,
                payload,
                version=step.version,
                response_queue_id=state.response_queue_id,
            )

            # Wait for response via the same response_buffer mechanism
            event = asyncio.Event()
            state.response_buffer[uid] = ResponseBufferItem(event=event)

            try:
                timeout = state.config.server.timeout
                await asyncio.wait_for(event.wait(), timeout=timeout)

                response_item = state.response_buffer.pop(uid)
                response_data, status = response_item.response

                if status == LitAPIStatus.ERROR:
                    raise EnsembleError(
                        f"Step '{step.name}' inference error"
                    )

                return response_data

            except asyncio.CancelledError:
                state.response_buffer.pop(uid, None)
                raise
            except asyncio.TimeoutError:
                state.response_buffer.pop(uid, None)
                raise InferenceTimeoutError(f"Step '{step.name}' timed out")
        finally:
            latency = time.time() - start
            metrics = state.system_metrics
            if metrics is not None:
                metrics.record_ensemble_step_latency(
                    ensemble=ensemble_name, step=step.name, model=step.model, latency=latency
                )

    @staticmethod
    def _resolve_ref(ref: str, context: dict[str, Any]) -> Any:
        """Resolve $request.field or $step_name.field from context."""
        match = _REF_RE.match(ref)
        if not match:
            raise EnsembleParserError(f"Invalid reference: {ref}")

        source = match.group(1)
        field = match.group(2)

        if source not in context:
            raise EnsembleParserError(f"Reference source not found: {source}")

        source_data = context[source]
        if field is None:
            return source_data
        if isinstance(source_data, dict) and field in source_data:
            return source_data[field]
        raise EnsembleParserError(
            f"Cannot resolve '{ref}' from {source_data}"
        )
