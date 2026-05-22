"""Generate project files from templates."""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import Any


class ProjectGenerator:
    """Generates a light-server project scaffold."""

    TEMPLATES = ["empty", "llm", "cv-classify", "cv-detect", "nlp"]

    def __init__(
        self,
        project_name: str,
        template: str = "empty",
        output_dir: str = ".",
        options: dict[str, Any] | None = None,
    ) -> None:
        if template not in self.TEMPLATES:
            raise ValueError(f"Unknown template '{template}'. Choose from: {', '.join(self.TEMPLATES)}")
        self.project_name = project_name
        self.template = template
        self.output_dir = Path(output_dir)
        self.options = options or {}

    def generate(self) -> Path:
        """Generate all project files and return the project root path."""
        root = self.output_dir / self.project_name
        if root.exists():
            raise FileExistsError(f"Directory already exists: {root}")

        model_name = self.options.get("model_name", "my_model")

        # Create directories
        (root / "model_repo" / model_name / "1").mkdir(parents=True)
        (root / ".github" / "workflows").mkdir(parents=True)

        # Generate files
        self._write(root / "server.yaml", self._render_server_yaml())
        self._write(root / "Dockerfile", self._render_dockerfile())
        self._write(root / "docker-compose.yml", self._render_docker_compose())
        self._write(root / "Makefile", self._render_makefile())
        self._write(root / "test_request.py", self._render_test_request(model_name))
        self._write(root / "README.md", self._render_readme(model_name))
        self._write(root / ".github" / "workflows" / "ci.yml", self._render_ci_yml())

        # Model files
        self._write(root / "model_repo" / model_name / "1" / "model.py", self._render_model_py())
        self._write(root / "model_repo" / model_name / "1" / "config.yaml", self._render_config_yaml())

        return root

    def _write(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def _load_template(self, name: str) -> str:
        """Load a template file from the package."""
        import importlib

        pkg = "light_server.init.templates"
        try:
            ref = importlib.resources.files(pkg) / name
            return ref.read_text(encoding="utf-8")
        except (FileNotFoundError, AttributeError):
            # Fallback for older Python
            mod = importlib.import_module(pkg)
            base = Path(mod.__file__).parent
            return (base / name).read_text(encoding="utf-8")

    def _render_server_yaml(self) -> str:
        grpc_enabled = self.options.get("grpc", True)
        metrics_enabled = self.options.get("metrics", True)
        webui_enabled = self.options.get("webui", True)
        batch = self.options.get("batch", False)
        stream = self.options.get("stream", False)
        model_name = self.options.get("model_name", "my_model")

        lines = [
            "server:",
            "  host: 0.0.0.0",
            "  http_port: 8000",
            "  grpc_port: 8001",
            "  metrics_port: 8002",
            "  log_level: info",
            "",
            f"grpc:\n  enabled: {str(grpc_enabled).lower()}",
            "",
            f"metrics:\n  enabled: {str(metrics_enabled).lower()}",
            "",
            "model_repository:",
            "  path: ./model_repo",
            "  control_mode: explicit",
            "",
            "load_models:",
            f"  - {model_name}",
        ]

        if batch or stream:
            lines.extend([
                "",
                "models:",
                f"  - name: {model_name}",
            ])
            if batch:
                lines.extend([
                    "    max_batch_size: 4",
                    "    batch_timeout: 0.01",
                ])
            if stream:
                lines.append("    stream: true")

        if webui_enabled:
            lines.extend([
                "",
                "webui:",
                "  enabled: true",
            ])

        return "\n".join(lines) + "\n"

    def _render_model_py(self) -> str:
        template_file = f"{self.template.replace('-', '_')}_model.py"
        return self._load_template(template_file)

    def _render_config_yaml(self) -> str:
        batch = self.options.get("batch", False)
        stream = self.options.get("stream", False)
        lines = []
        if batch:
            lines.extend([
                "max_batch_size: 4",
                "batch_timeout: 0.01",
            ])
        if stream:
            lines.append("stream: true")
        if not lines:
            lines.append("# Add model-specific config here")
            lines.append("# max_batch_size: 4")
            lines.append("# batch_timeout: 0.01")
        return "\n".join(lines) + "\n"

    def _render_dockerfile(self) -> str:
        return '''FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy model repository and server config
COPY model_repo ./model_repo
COPY server.yaml .

EXPOSE 8000 8001 8002

CMD ["light-server", "serve", "--config", "server.yaml"]
'''

    def _render_docker_compose(self) -> str:
        return '''version: "3.8"

services:
  server:
    build: .
    ports:
      - "8000:8000"
      - "8001:8001"
      - "8002:8002"
    volumes:
      - ./model_repo:/app/model_repo
    environment:
      - PYTHONUNBUFFERED=1
'''

    def _render_makefile(self) -> str:
        return '''.PHONY: serve test benchmark clean

serve:
	light-server serve --config server.yaml

test:
	python test_request.py

benchmark:
	light-server benchmark --model my_model --duration 30

clean:
	rm -rf __pycache__ .pytest_cache *.log
'''

    def _render_test_request(self, model_name: str) -> str:
        return f'''"""Test script for the {model_name} model."""

import requests

URL = "http://127.0.0.1:8000/v2/models/{model_name}/infer"


def test_infer():
    payload = {{
        "input": "hello world",
    }}
    resp = requests.post(URL, json=payload)
    print(f"Status: {{resp.status_code}}")
    print(f"Response: {{resp.json()}}")


def test_health():
    resp = requests.get(f"http://127.0.0.1:8000/v2/models/{model_name}/ready")
    print(f"Ready: {{resp.status_code}}")


if __name__ == "__main__":
    test_health()
    test_infer()
'''

    def _render_readme(self, model_name: str) -> str:
        proj = self.project_name
        tmpl = self.template
        return f"""# {proj}

Light Server project generated with `light-server init`.

## Quick Start

```bash
# Start the server
make serve
# or
light-server serve --config server.yaml

# In another terminal, run the test
make test
# or
python test_request.py
```

## Project Structure

```
{proj}/
├── server.yaml              # Server configuration
├── Dockerfile               # Container image
├── docker-compose.yml       # Local orchestration
├── Makefile                 # Common commands
├── test_request.py          # Quick test script
├── model_repo/
│   └── {model_name}/
│       └── 1/
│           ├── model.py     # LitAPI implementation
│           └── config.yaml  # Model config
└── .github/
    └── workflows/
        └── ci.yml           # GitHub Actions CI
```

## Model

- Template: `{tmpl}`
- Name: `{model_name}`

## Commands

| Command | Description |
|---------|-------------|
| `make serve` | Start the server |
| `make test` | Send a test request |
| `make benchmark` | Run benchmark |
| `make clean` | Clean caches |
"""

    def _render_ci_yml(self) -> str:
        return '''name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: |
          pip install light-server
      - name: Validate config
        run: light-server config-check server.yaml
'''
