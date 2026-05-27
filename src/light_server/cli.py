"""Command-line interface for Light Server."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import sys
from pathlib import Path

from light_server.config import load_config, load_orchestration


def _serve_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("module", nargs="?", help="Python module:Class (e.g., my_model:MyAPI)")
    parser.add_argument("--config", "-c", help="Path to YAML configuration file")
    parser.add_argument("--port", type=int, default=None, help="HTTP server port")
    parser.add_argument("--host", default=None, help="Bind address")
    parser.add_argument("--accelerator", default=None, help="Hardware accelerator")
    parser.add_argument("--devices", default=None, help="Number of devices")
    parser.add_argument("--workers-per-device", type=int, default=None, help="Workers per device")
    parser.add_argument("--timeout", type=float, default=None, help="Request timeout")
    parser.add_argument("--log-level", default=None, help="Logging level")
    parser.add_argument("--log-dir", help="Log directory (creates info.log and error.log)")
    parser.add_argument("--log-info", help="Info log file path")
    parser.add_argument("--log-error", help="Error log file path")
    parser.add_argument("--log-format", default=None, choices=["json", "text"], help="Log format")
    parser.add_argument("--log-rotate-by", default=None, choices=["none", "size", "time"], help="Rotation strategy")
    parser.add_argument("--log-max-size", type=int, default=None, help="Max log file size in MB (for size rotation)")
    parser.add_argument("--log-when", default=None, help="Rotation interval (for time rotation: H/D/midnight)")
    parser.add_argument("--log-backup-count", type=int, default=None, help="Number of backup log files to keep")
    parser.add_argument("--model-repo", help="Model repository path (directory containing models or .lma files)")
    parser.add_argument("--grpc-port", type=int, default=None, help="gRPC port")
    parser.add_argument("--metrics-port", type=int, default=None, help="Metrics port")
    parser.add_argument("--http-workers", type=int, default=None, help="Number of HTTP worker processes (default: auto)")
    parser.add_argument("--no-grpc", action="store_true", default=None, help="Disable gRPC")
    parser.add_argument("--no-metrics", action="store_true", default=None, help="Disable metrics")


def _benchmark_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Server base URL")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument("--version", default=None, help="Model version (default: active)")
    parser.add_argument("--concurrency", type=int, default=8, help="Number of concurrent requests")
    parser.add_argument("--duration", type=float, default=30.0, help="Benchmark duration in seconds")
    parser.add_argument("--mode", default="fixed", choices=["fixed", "ramp"], help="Load mode")
    parser.add_argument("--max-concurrency", type=int, default=64, help="Max concurrency for ramp mode")
    parser.add_argument("--step-duration", type=float, default=10.0, help="Seconds per ramp step")
    parser.add_argument("--payload", default='{"input": 1.0}', help="Request payload (JSON string)")
    parser.add_argument("--output", help="Output file path for JSON results")


def _analyze_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model-repo", default="./model_repo", help="Model repository path")
    parser.add_argument("--model", required=True, help="Model name to analyze")
    parser.add_argument("--output-dir", default="./reports", help="Directory to save reports")


def _pack_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("model_dir", help="Path to model directory (e.g., model_repo/test_model)")
    parser.add_argument("--version", "-v", required=True, help="Model version (semver)")
    parser.add_argument("--output", "-o", default="./artifacts", help="Output directory")
    parser.add_argument("--build-id", help="Custom build ID (default: auto-generated)")
    parser.add_argument("--sign-key", help="Path to Ed25519 private key PEM for signing")
    parser.add_argument("--signer", default="", help="Signer identity string")
    parser.add_argument("--ignore", action="append", help="Additional ignore patterns (can repeat)")


def _unpack_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("artifact", help="Path to .lma artifact file")
    parser.add_argument("--to", dest="target_dir", default=".", help="Target directory for extraction")
    parser.add_argument("--verify-key", help="Path to Ed25519 public key PEM for signature verification")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, do not extract")


def _init_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_name", nargs="?", help="Project directory name")
    parser.add_argument("--template", "-t", default="empty", choices=["empty", "llm", "cv-classify", "cv-detect", "nlp"], help="Project template")
    parser.add_argument("--model-name", "-m", default="my_model", help="Model name")
    parser.add_argument("--grpc", action=argparse.BooleanOptionalAction, default=True, help="Enable or disable gRPC (default: true)")
    parser.add_argument("--metrics", action=argparse.BooleanOptionalAction, default=True, help="Enable or disable metrics (default: true)")
    parser.add_argument("--webui", action=argparse.BooleanOptionalAction, default=True, help="Enable or disable Web UI (default: true)")
    parser.add_argument("--batch", action="store_true", help="Enable dynamic batching")
    parser.add_argument("--stream", action="store_true", help="Enable streaming responses")
    parser.add_argument("--output-dir", "-o", default=".", help="Output directory for the project")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="light-server", description="Light Server - Triton-style deployment on LitServe")
    _version = importlib.metadata.version("light-server")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {_version}")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start the inference server")
    _serve_args(serve_parser)

    # config-check
    check_parser = subparsers.add_parser("config-check", help="Validate configuration file")
    check_parser.add_argument("config", help="Path to YAML configuration file")

    # benchmark
    benchmark_parser = subparsers.add_parser("benchmark", help="Run performance benchmark against a running server")
    _benchmark_args(benchmark_parser)

    # analyze
    analyze_parser = subparsers.add_parser("analyze", help="Run Model Analyzer to find optimal configuration")
    _analyze_args(analyze_parser)

    # pack
    pack_parser = subparsers.add_parser("pack", help="Pack a model directory into a .lma artifact")
    _pack_args(pack_parser)

    # unpack
    unpack_parser = subparsers.add_parser("unpack", help="Unpack a .lma artifact")
    _unpack_args(unpack_parser)

    # init
    init_parser = subparsers.add_parser("init", help="Initialize a new light-server project")
    _init_args(init_parser)

    args = parser.parse_args(argv)

    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "config-check":
        return _cmd_config_check(args)
    if args.command == "benchmark":
        return _cmd_benchmark(args)
    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "pack":
        return _cmd_pack(args)
    if args.command == "unpack":
        return _cmd_unpack(args)
    if args.command == "init":
        return _cmd_init(args)

    parser.print_help()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from light_server.core.server import LightServer

    if args.config:
        config = load_config(args.config)
        # Load orchestration from model_repo/orchestration.yaml
        repo_path = Path(config.model_repository.path)
        if not repo_path.is_absolute():
            repo_path = Path(args.config).parent / repo_path
        orch_path = repo_path / "orchestration.yaml"
        if orch_path.exists():
            config.orchestration = load_orchestration(orch_path)
    else:
        from light_server.config import Config, GrpcConfig, LoggingConfig, MetricsConfig, ModelRepositoryConfig, ServerConfig, OrchestrationConfig

        log_info = args.log_info
        log_error = args.log_error
        if args.log_dir and not (log_info or log_error):
            log_dir = Path(args.log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            log_info = str(log_dir / "info.log")
            log_error = str(log_dir / "error.log")

        model_repo_path = args.model_repo or "./model_repo"

        config = Config(
            server=ServerConfig(
                http_port=args.port or 8000,
                host=args.host or "0.0.0.0",
                timeout=args.timeout or 30.0,
                log_level=args.log_level or "info",
                http_workers=args.http_workers,
            ),
            grpc=GrpcConfig(enabled=not (args.no_grpc or False), max_workers=10),
            metrics=MetricsConfig(enabled=not (args.no_metrics or False)),
            logging=LoggingConfig(
                level=args.log_level or "info",
                format=args.log_format or "text",
                info_output=log_info,
                error_output=log_error,
                rotate_by=args.log_rotate_by or "none",
                max_size=args.log_max_size or 100,
                when=args.log_when or "midnight",
                backup_count=args.log_backup_count or 7,
            ),
            model_repository=ModelRepositoryConfig(
                path=model_repo_path,
            ),
        )

        if args.module:
            # Single module mode: parse module:Class
            config.orchestration.load_models = ["__cli__"]

    # CLI overrides take precedence over config file values
    if args.port is not None:
        config.server.http_port = args.port
    if args.host is not None:
        config.server.host = args.host
    if args.http_workers is not None:
        config.server.http_workers = args.http_workers
    if args.timeout is not None:
        config.server.timeout = args.timeout
    if args.log_level is not None:
        config.server.log_level = args.log_level
        config.logging.level = args.log_level
    if args.grpc_port is not None:
        config.server.grpc_port = args.grpc_port
    if args.metrics_port is not None:
        config.server.metrics_port = args.metrics_port
    if args.no_grpc:
        config.grpc.enabled = False
    if args.no_metrics:
        config.metrics.enabled = False
    if args.model_repo is not None:
        config.model_repository.path = args.model_repo
    if args.log_format is not None:
        config.logging.format = args.log_format
    if args.log_info is not None:
        config.logging.info_output = args.log_info
    if args.log_error is not None:
        config.logging.error_output = args.log_error
    if args.log_dir is not None:
        if not (args.log_info or args.log_error):
            log_dir = Path(args.log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            config.logging.info_output = str(log_dir / "info.log")
            config.logging.error_output = str(log_dir / "error.log")
    if args.log_rotate_by is not None:
        config.logging.rotate_by = args.log_rotate_by
    if args.log_max_size is not None:
        config.logging.max_size = args.log_max_size
    if args.log_when is not None:
        config.logging.when = args.log_when
    if args.log_backup_count is not None:
        config.logging.backup_count = args.log_backup_count

    server = LightServer(config)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    return 0


def _cmd_config_check(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        repo_path = Path(config.model_repository.path)
        if not repo_path.is_absolute():
            repo_path = Path(args.config).parent / repo_path
        orch_path = repo_path / "orchestration.yaml"
        if orch_path.exists():
            config.orchestration = load_orchestration(orch_path)
        print(f"Configuration OK: {args.config}")
        print(f"  HTTP port: {config.server.http_port}")
        print(f"  gRPC port: {config.server.grpc_port}")
        print(f"  Metrics port: {config.server.metrics_port}")
        print(f"  Model repo: {config.model_repository.path}")
        print(f"  Load models: {config.orchestration.load_models}")
        return 0
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1


def _cmd_benchmark(args: argparse.Namespace) -> int:
    from light_server.analyzer.benchmark import BenchmarkEngine, HttpBenchmarkTarget

    async def run() -> None:
        payload = json.loads(args.payload)
        target = HttpBenchmarkTarget(
            base_url=args.url,
            model_name=args.model,
            version=args.version,
        )
        engine = BenchmarkEngine()
        result = await engine.run(
            target=target,
            payload=payload,
            mode=args.mode,  # type: ignore[arg-type]
            concurrency=args.concurrency,
            duration=args.duration,
            max_concurrency=args.max_concurrency,
            step_duration=args.step_duration,
        )
        await target.close()

        print(f"\nBenchmark Results ({args.model}):")
        print(f"  Mode:            {args.mode}")
        print(f"  Duration:        {result.duration_seconds}s")
        print(f"  Total requests:  {result.total_requests}")
        print(f"  Success:         {result.successful_requests}")
        print(f"  Failed:          {result.failed_requests}")
        print(f"  Throughput:      {result.throughput} req/s")
        print(f"  Latency (ms):")
        print(f"    mean: {result.latency_ms.mean}")
        print(f"    p50:  {result.latency_ms.p50}")
        print(f"    p90:  {result.latency_ms.p90}")
        print(f"    p99:  {result.latency_ms.p99}")
        print(f"    p99.9:{result.latency_ms.p99_9}")
        if result.errors:
            print(f"  Sample errors:   {result.errors[:3]}")

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "model": args.model,
                    "version": args.version,
                    "mode": args.mode,
                    "duration": result.duration_seconds,
                    "throughput": result.throughput,
                    "latency_ms": {
                        "mean": result.latency_ms.mean,
                        "p50": result.latency_ms.p50,
                        "p90": result.latency_ms.p90,
                        "p99": result.latency_ms.p99,
                        "p99_9": result.latency_ms.p99_9,
                        "min": result.latency_ms.min,
                        "max": result.latency_ms.max,
                    },
                    "total_requests": result.total_requests,
                    "successful_requests": result.successful_requests,
                    "failed_requests": result.failed_requests,
                    "errors": result.errors,
                }, indent=2))
            print(f"\nResults saved to {args.output}")

    try:
        asyncio.run(run())
    except Exception as e:
        print(f"Benchmark failed: {e}", file=sys.stderr)
        return 1
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    from light_server.analyzer.runner import AnalysisRunner

    async def run() -> int:
        runner = AnalysisRunner(repo_path=args.model_repo)
        report = await runner.run(
            model_name=args.model,
            output_dir=args.output_dir,
        )
        print(f"\nAnalysis complete. Pareto optimal configurations: {len(report.pareto_frontier)}")
        return 0

    try:
        return asyncio.run(run())
    except Exception as e:
        print(f"Analysis failed: {e}", file=sys.stderr)
        return 1


def _cmd_pack(args: argparse.Namespace) -> int:
    from light_server.artifact.packer import ModelPacker

    model_dir = Path(args.model_dir)
    if not model_dir.exists():
        print(f"Model directory not found: {model_dir}", file=sys.stderr)
        return 1

    packer = ModelPacker(
        model_dir=model_dir,
        version=args.version,
        build_id=args.build_id,
        ignore_patterns=args.ignore,
    )
    artifact_path = packer.pack(Path(args.output))

    if args.sign_key:
        private_key_pem = Path(args.sign_key).read_bytes()
        packer.sign(private_key_pem, signer=args.signer)
        print(f"Signed artifact: {artifact_path}")
    else:
        print(f"Packed artifact: {artifact_path}")

    return 0


def _cmd_unpack(args: argparse.Namespace) -> int:
    from light_server.artifact.unpacker import ModelUnpacker

    artifact_path = Path(args.artifact)
    if not artifact_path.exists():
        print(f"Artifact not found: {artifact_path}", file=sys.stderr)
        return 1

    public_key_pem: bytes | None = None
    if args.verify_key:
        public_key_pem = Path(args.verify_key).read_bytes()

    unpacker = ModelUnpacker(artifact_path)
    try:
        manifest = unpacker.validate(public_key_pem=public_key_pem)
    except Exception as e:
        print(f"Validation failed: {e}", file=sys.stderr)
        return 1

    print(f"Artifact: {manifest.name} v{manifest.version} ({manifest.build_id})")
    print(f"  Files: {len(manifest.files)}")

    if args.dry_run:
        print("Dry run: validation passed, not extracting.")
        return 0

    target_dir = Path(args.target_dir)
    model_dir = unpacker.unpack(target_dir)
    print(f"Extracted to: {model_dir}")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    from light_server.init import ProjectGenerator, run_wizard

    if args.project_name:
        # Non-interactive mode
        options = {
            "model_name": args.model_name,
            "grpc": args.grpc,
            "metrics": args.metrics,
            "webui": args.webui,
            "batch": args.batch,
            "stream": args.stream,
        }
        generator = ProjectGenerator(
            project_name=args.project_name,
            template=args.template,
            output_dir=args.output_dir,
            options=options,
        )
        try:
            root = generator.generate()
        except FileExistsError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Created project at: {root}")
        print(f"\nNext steps:")
        print(f"  cd {root.name}")
        print(f"  light-server serve --config server.yaml")
        print(f"  # In another terminal:")
        print(f"  python test_request.py")
        return 0

    # Interactive mode
    run_wizard(output_dir=args.output_dir)
    return 0
