"""Start light_server for benchmarking.

Requires light-server to be installed in the Python environment:
    uv pip install -e .    # or: pip install light-server
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from light_server.config import Config, GrpcConfig, MetricsConfig, ModelRepositoryConfig, ServerConfig
from light_server.core.server import LightServer


def main() -> int:
    parser = argparse.ArgumentParser(description="Run light_server benchmark target")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workers", type=int, default=1, help="Inference workers per device")
    parser.add_argument("--http-workers", type=int, default=1, help="HTTP worker processes")
    parser.add_argument(
        "--model-repo",
        default=None,
        help="Path to model repository directory (default: <script_dir>/models)",
    )
    parser.add_argument(
        "--duration", type=float, default=30.0, help="Expected benchmark duration (for timeout)"
    )
    args = parser.parse_args()

    if args.model_repo:
        model_repo = Path(args.model_repo).resolve()
    else:
        model_repo = Path(__file__).resolve().parent.parent / "models"

    if not model_repo.exists():
        print(f"ERROR: Model repository not found: {model_repo}", file=sys.stderr)
        return 1

    # Auto-detect model name from first subdirectory
    model_names = [d.name for d in model_repo.iterdir() if d.is_dir()]
    if not model_names:
        print(f"ERROR: No models found in {model_repo}", file=sys.stderr)
        return 1

    config = Config(
        server=ServerConfig(
            host="127.0.0.1",
            http_port=args.port,
            log_level="info",
            timeout=args.duration + 10.0,
            workers_per_device=args.workers,
            http_workers=args.http_workers,
        ),
        grpc=GrpcConfig(enabled=False),
        metrics=MetricsConfig(enabled=False),
        model_repository=ModelRepositoryConfig(
            path=str(model_repo),
            control_mode="explicit",
        ),
        load_models=model_names,
    )

    server = LightServer(config)

    def _sigint_handler(signum, frame):
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint_handler)

    try:
        server.run()
    except KeyboardInterrupt:
        print("\nShutting down light_server...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
