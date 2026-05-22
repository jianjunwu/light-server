"""Command-line interface for Light Server."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from light_server.config import load_config


def _serve_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("module", nargs="?", help="Python module:Class (e.g., my_model:MyAPI)")
    parser.add_argument("--config", "-c", help="Path to YAML configuration file")
    parser.add_argument("--port", type=int, default=8000, help="HTTP server port")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--accelerator", default="auto", help="Hardware accelerator")
    parser.add_argument("--devices", default="auto", help="Number of devices")
    parser.add_argument("--workers-per-device", type=int, default=1, help="Workers per device")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout")
    parser.add_argument("--log-level", default="info", help="Logging level")
    parser.add_argument("--model-repo", help="Model repository path")
    parser.add_argument("--grpc-port", type=int, default=8001, help="gRPC port")
    parser.add_argument("--metrics-port", type=int, default=8002, help="Metrics port")
    parser.add_argument("--no-grpc", action="store_true", help="Disable gRPC")
    parser.add_argument("--no-metrics", action="store_true", help="Disable metrics")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="light-server", description="Light Server - Triton-style deployment on LitServe")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start the inference server")
    _serve_args(serve_parser)

    # config-check
    check_parser = subparsers.add_parser("config-check", help="Validate configuration file")
    check_parser.add_argument("config", help="Path to YAML configuration file")

    args = parser.parse_args(argv)

    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "config-check":
        return _cmd_config_check(args)

    parser.print_help()
    return 1


def _cmd_serve(args: argparse.Namespace) -> int:
    from light_server.core.server import LightServer

    if args.config:
        config = load_config(args.config)
    else:
        from light_server.config import Config, GrpcConfig, MetricsConfig, ModelRepositoryConfig, ServerConfig
        config = Config(
            server=ServerConfig(
                http_port=args.port,
                host=args.host,
                accelerator=args.accelerator,
                devices=args.devices,
                workers_per_device=args.workers_per_device,
                timeout=args.timeout,
                log_level=args.log_level,
            ),
            grpc=GrpcConfig(enabled=not args.no_grpc, max_workers=10),
            metrics=MetricsConfig(enabled=not args.no_metrics),
            model_repository=ModelRepositoryConfig(
                path=args.model_repo or "./model_repo",
                control_mode="none",
            ),
        )

        if args.module:
            # Single module mode: parse module:Class
            config.load_models = ["__cli__"]
            from light_server.config import ModelConfig
            config.models = [ModelConfig(name="__cli__", source=args.module)]

    server = LightServer(config)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    return 0


def _cmd_config_check(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        print(f"Configuration OK: {args.config}")
        print(f"  HTTP port: {config.server.http_port}")
        print(f"  gRPC port: {config.server.grpc_port}")
        print(f"  Metrics port: {config.server.metrics_port}")
        print(f"  Model repo: {config.model_repository.path}")
        print(f"  Load models: {config.load_models}")
        return 0
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1
