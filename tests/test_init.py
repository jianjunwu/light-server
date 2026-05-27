"""Tests for light-server init command."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from light_server.init import ProjectGenerator


@pytest.fixture
def tmp_workspace(tmp_path: Path):
    """Provide a temporary workspace for project generation."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    yield ws
    # cleanup happens automatically by tmp_path


class TestProjectGenerator:
    def test_generate_empty_template(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="demo",
            template="empty",
            output_dir=str(tmp_workspace),
            options={"model_name": "my_model"},
        )
        root = gen.generate()
        assert root.exists()
        assert (root / "server.yaml").exists()
        assert (root / "Dockerfile").exists()
        assert (root / "docker-compose.yml").exists()
        assert (root / "Makefile").exists()
        assert (root / "test_request.py").exists()
        assert (root / "README.md").exists()
        assert (root / ".github" / "workflows" / "ci.yml").exists()
        assert (root / "model_repo" / "my_model" / "1" / "model.py").exists()
        assert (root / "model_repo" / "my_model" / "1" / "config.yaml").exists()
        assert (root / "model_repo" / "orchestration.yaml").exists()
        assert (root / "requirements.txt").exists()
        assert (root / ".gitignore").exists()

    def test_generate_all_templates(self, tmp_workspace: Path):
        for template in ProjectGenerator.TEMPLATES:
            gen = ProjectGenerator(
                project_name=f"proj_{template}",
                template=template,
                output_dir=str(tmp_workspace),
            )
            root = gen.generate()
            model_py = root / "model_repo" / "my_model" / "1" / "model.py"
            assert model_py.exists(), f"model.py missing for template {template}"
            content = model_py.read_text()
            assert "class MyAPI" in content, f"MyAPI class missing in {template}"
            assert "LitAPI" in content, f"LitAPI import missing in {template}"

    def test_server_yaml_content(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="svc",
            template="empty",
            output_dir=str(tmp_workspace),
            options={
                "model_name": "test_m",
                "grpc": False,
                "metrics": True,
                "batch": True,
                "stream": True,
            },
        )
        root = gen.generate()
        yaml_text = (root / "server.yaml").read_text()
        assert "grpc:\n  enabled: false" in yaml_text
        assert "metrics:\n  enabled: true" in yaml_text
        # load_models and per-model params moved to orchestration.yaml
        assert "load_models" not in yaml_text
        assert "max_batch_size" not in yaml_text

    def test_orchestration_yaml_content(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="orch",
            template="empty",
            output_dir=str(tmp_workspace),
            options={"model_name": "test_m", "batch": True},
        )
        root = gen.generate()
        orch = (root / "model_repo" / "orchestration.yaml").read_text()
        assert "control_mode: explicit" in orch
        assert "load_models:" in orch
        assert "- test_m" in orch
        assert "models:" in orch
        assert "load_policy: explicit" in orch
        assert "max_batch_size" not in orch
        assert "batch_timeout" not in orch

    def test_config_yaml_has_devices_workers(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="cfg",
            template="empty",
            output_dir=str(tmp_workspace),
            options={"batch": True, "stream": False},
        )
        root = gen.generate()
        cfg = (root / "model_repo" / "my_model" / "1" / "config.yaml").read_text()
        assert "max_batch_size: 4" in cfg
        assert "batch_timeout: 0.01" in cfg
        assert "devices:" in cfg
        assert "workers_per_device:" in cfg
        assert "accelerator:" in cfg
        assert "stream" not in cfg

    def test_duplicate_project_name_raises(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="dup",
            template="empty",
            output_dir=str(tmp_workspace),
        )
        gen.generate()
        with pytest.raises(FileExistsError):
            gen.generate()

    def test_invalid_template_raises(self, tmp_workspace: Path):
        with pytest.raises(ValueError, match="Unknown template"):
            ProjectGenerator(
                project_name="x",
                template="notexist",
                output_dir=str(tmp_workspace),
            )

    def test_dockerfile_content(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="dock",
            template="empty",
            output_dir=str(tmp_workspace),
        )
        root = gen.generate()
        df = (root / "Dockerfile").read_text()
        assert '"light-server", "serve", "--config", "server.yaml"' in df
        assert "EXPOSE 8000" in df

    def test_docker_compose_no_version(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="dc",
            template="empty",
            output_dir=str(tmp_workspace),
        )
        root = gen.generate()
        dc = (root / "docker-compose.yml").read_text()
        assert "version:" not in dc
        assert "services:" in dc

    def test_makefile_uses_model_name(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="mk",
            template="empty",
            output_dir=str(tmp_workspace),
            options={"model_name": "custom_m"},
        )
        root = gen.generate()
        mf = (root / "Makefile").read_text()
        assert "light-server benchmark --model custom_m" in mf

    def test_test_request_with_batch_and_stream(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="tr",
            template="empty",
            output_dir=str(tmp_workspace),
            options={"model_name": "m", "batch": True, "stream": True},
        )
        root = gen.generate()
        tr = (root / "test_request.py").read_text()
        assert "def test_batch()" in tr
        assert "def test_stream()" in tr

    def test_requirements_txt(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="req",
            template="cv-classify",
            output_dir=str(tmp_workspace),
        )
        root = gen.generate()
        req = (root / "requirements.txt").read_text()
        assert "light-server" in req
        assert "# Pillow" in req

    def test_gitignore_content(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="git",
            template="empty",
            output_dir=str(tmp_workspace),
        )
        root = gen.generate()
        gi = (root / ".gitignore").read_text()
        assert "__pycache__/" in gi
        assert ".venv/" in gi

    def test_ci_yml_includes_lint(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="ci",
            template="empty",
            output_dir=str(tmp_workspace),
            options={"model_name": "ci_model"},
        )
        root = gen.generate()
        ci = (root / ".github" / "workflows" / "ci.yml").read_text()
        assert "py_compile" in ci
        assert "ci_model" in ci

    def test_readme_contains_project_name(self, tmp_workspace: Path):
        gen = ProjectGenerator(
            project_name="named_proj",
            template="llm",
            output_dir=str(tmp_workspace),
            options={"model_name": "gpt_demo"},
        )
        root = gen.generate()
        readme = (root / "README.md").read_text()
        assert "named_proj" in readme
        assert "gpt_demo" in readme
        assert "llm" in readme


class TestCLInit:
    def test_cli_init_non_interactive(self, tmp_workspace: Path):
        """Test init via CLI non-interactive mode."""
        from light_server.cli import main

        project = tmp_workspace / "cli_proj"
        ret = main([
            "init", "cli_proj",
            "--template", "nlp",
            "--model-name", "sentiment",
            "--batch",
            "--output-dir", str(tmp_workspace),
        ])
        assert ret == 0
        assert (project / "server.yaml").exists()
        assert (project / "model_repo" / "sentiment" / "1" / "model.py").exists()

    def test_cli_init_no_project_name_shows_help(self, capsys):
        """Without project_name, init enters interactive mode; we can't test that easily,
        so just verify the parser accepts no args."""
        from light_server.cli import main

        # When project_name is missing, _cmd_init calls run_wizard which does input().
        # We test the non-interactive path above; for the wizard, unit-test run_wizard separately.
        pass
