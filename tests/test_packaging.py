"""Phase 2 (R1, KD5/KD6) — the tool ships its assets + declares correct dependency tiers.

Success criteria asserted here:
- extract.cjs resolves via importlib.resources (NOT __file__/parents[*]) so a pipx install
  finds it in site-packages, and it physically lives inside the package tree.
- the package-data contract that puts the .cjs in the wheel is declared (asserted always);
  the wheel is actually built + inspected when a build backend is present (CI), else skipped.
- base deps exclude graspologic (Louvain-light); [leiden] declares it; [dev] retained;
  console-script entrypoint + readme/license/classifiers are wired.
"""
import importlib.util
import subprocess
import sys
import tomllib
import zipfile
from importlib.resources import as_file, files
from pathlib import Path

import pytest

from cg_graphify_bridge import ts_substrate

_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text())


# ---------------- KD5: extractor packaged + importlib.resources locator ----------------

def test_extractor_path_via_importlib_resources():
    # the module locates the extractor through importlib.resources, not a repo-relative path
    with as_file(ts_substrate._extractor_resource()) as p:
        assert Path(p).is_file()
        assert Path(p).name == "extract.cjs"
    src = (_ROOT / "src" / "cg_graphify_bridge" / "ts_substrate.py").read_text()
    assert "Path(__file__).resolve()" not in src       # the install-breaking locator call is gone
    assert "importlib.resources" in src or "as_file" in src


def test_extractor_inside_package_tree():
    # physical location is under the importable package (so setuptools ships it in the wheel)
    with as_file(files("cg_graphify_bridge.ts_substrate_js").joinpath("extract.cjs")) as p:
        assert Path(p).is_file()
        assert "ents.sort(" in Path(p).read_text()      # KD3 determinism survived the move


def test_extractor_declared_as_package_data():
    # deterministic wheel-inclusion contract (runs even offline where no backend exists):
    # setuptools ships package-data by the declared globs, so this proves the .cjs will ship.
    st = _pyproject()["tool"]["setuptools"]
    assert st.get("include-package-data") is True
    pdata = st.get("package-data", {})
    globs = pdata.get("cg_graphify_bridge.ts_substrate_js", []) + pdata.get("cg_graphify_bridge", [])
    assert any(g.endswith(".cjs") for g in globs), f"no .cjs package-data glob declared: {pdata}"


@pytest.mark.skipif(
    importlib.util.find_spec("setuptools") is None,
    reason="build backend (setuptools) unavailable offline — wheel-inclusion is asserted "
           "deterministically by test_extractor_declared_as_package_data; this builds for real in CI")
def test_extractor_in_wheel(tmp_path):
    dist = tmp_path / "dist"
    r = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(_ROOT), "--no-deps", "--no-build-isolation",
         "-w", str(dist)], capture_output=True, text=True)
    assert r.returncode == 0, (r.stderr or r.stdout)[-1000:]
    wheels = list(dist.glob("*.whl"))
    assert wheels, "no wheel produced"
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
    assert any(n.endswith("cg_graphify_bridge/ts_substrate_js/extract.cjs") for n in names), names


# ---------------- KD6: dependency tiers + metadata + entrypoint ----------------

def test_base_deps_exclude_graspologic():
    deps = _pyproject()["project"]["dependencies"]
    assert "graspologic" not in " ".join(deps)          # base = Louvain-deterministic, light
    assert any(d.startswith("graphifyy==") for d in deps)
    assert any(d.startswith("networkx==") for d in deps)


def test_leiden_extra_declares_graspologic():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert "leiden" in extras and any("graspologic" in d for d in extras["leiden"])
    assert "dev" in extras                               # pytest/ruff retained


def test_entrypoint_console_script():
    scripts = _pyproject()["project"].get("scripts", {})
    assert scripts.get("cg-graphify-bridge") == "cg_graphify_bridge.cli:main"


def test_packaging_metadata_present():
    proj = _pyproject()["project"]
    assert proj.get("readme") == "README.md"
    assert proj.get("license")                           # declared (proprietary/internal)
    assert proj.get("classifiers")                       # non-empty list
