"""Standalone-ness guards: the distribution is named for the standalone tool, and the committed
hook/CI commands invoke the PATH-installed `cg-graphify-bridge` rather than baking a build-time
PYTHONPATH/`python3 -m` path (every consumer pipx-installs the tool, so it's on PATH)."""
import inspect
import tomllib
from pathlib import Path

from cg_graphify_bridge import cli

_ROOT = Path(__file__).resolve().parents[1]


def test_distribution_named_standalone():
    proj = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
    assert proj["name"] == "cg-graphify-bridge"


def test_hook_commands_target_path_install():
    assert cli._resolve_hook_cmd("hook-stop", "graphify-out") == "cg-graphify-bridge hook-stop"
    assert cli._resolve_hook_cmd("hook-sessionstart", "out") == "cg-graphify-bridge hook-sessionstart --out out"


def test_default_hook_builder_has_no_pythonpath():
    # the .claude hook command builder must not bake a PYTHONPATH / `python3 -m` install path
    src = inspect.getsource(cli._resolve_hook_cmd)
    assert "PYTHONPATH" not in src and "python3 -m" not in src
