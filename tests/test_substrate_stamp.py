"""R6 — the extraction SUBSTRATE (codegraph / typescript) version is stamped into the manifest and
drift-checked, complementing the clustering-engine guard. Substrate drift is ADVISORY (a version
bump only *may* change extraction; the diff-gate catches real churn), unlike the hard engine guard.
"""
import json
import shutil
import subprocess

from cg_graphify_bridge import cli, engine
from conftest import SAMPLE, requires_codegraph


# ---------- drift detection (pure) ----------

def test_substrate_drift_warns_on_version_mismatch():
    msg = engine.check_substrate_drift(
        {"substrate": "codegraph", "substrate_version": "codegraph@0.9.8"},
        "codegraph", "codegraph@0.9.9")
    assert msg and "substrate drift" in msg and "0.9.8" in msg and "0.9.9" in msg


def test_substrate_drift_none_on_match():
    assert engine.check_substrate_drift(
        {"substrate": "codegraph", "substrate_version": "codegraph@0.9.9"},
        "codegraph", "codegraph@0.9.9") is None


def test_substrate_drift_none_when_unstampable():
    assert engine.check_substrate_drift(None, "codegraph", "codegraph@0.9.9") is None
    assert engine.check_substrate_drift({"hash": "x"}, "codegraph", "codegraph@0.9.9") is None  # pre-stamp


# ---------- version capture ----------

def test_substrate_version_reads_target_typescript(tmp_path):
    tsdir = tmp_path / "node_modules" / "typescript"
    tsdir.mkdir(parents=True)
    (tsdir / "package.json").write_text(json.dumps({"name": "typescript", "version": "5.4.2"}))
    assert cli._substrate_version("ts", tmp_path) == "typescript@5.4.2"


def test_substrate_version_ts_missing_returns_none(tmp_path):
    assert cli._substrate_version("ts", tmp_path) is None


@requires_codegraph
def test_substrate_version_codegraph_real():
    v = cli._substrate_version("codegraph", SAMPLE)
    assert v and v.startswith("codegraph@")


@requires_codegraph
def test_build_stamps_substrate_into_manifest(tmp_path):
    dst = tmp_path / "s"
    shutil.copytree(SAMPLE, dst)
    subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
    cli.build_repo(dst, "graphify-out", substrate="codegraph")
    m = json.loads((dst / "graphify-out" / ".cg_manifest.json").read_text())
    assert m["substrate"] == "codegraph" and m["substrate_version"].startswith("codegraph@")
