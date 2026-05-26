import shutil
import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class FrontendBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        frontend_dir = Path("frontend")
        if not (frontend_dir / "package.json").exists():
            print("frontend/package.json not found, skipping", file=sys.stderr)
            return

        subprocess.run(
            ["npm", "ci"],
            cwd=str(frontend_dir),
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        dist_src = frontend_dir / "dist"
        dist_dst = Path("src/light_server/webui/static/dist")
        if dist_dst.exists():
            shutil.rmtree(dist_dst)
        shutil.copytree(dist_src, dist_dst)

        build_data["artifacts"].append("src/light_server/webui/static/dist/**/*")
