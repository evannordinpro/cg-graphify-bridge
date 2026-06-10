"""Phase 4 fix (R5) — clustering determinism via a pinned PYTHONHASHSEED.

networkx Louvain (and graspologic Leiden) tie-breaking is sensitive to Python's hash
randomization: with an UNPINNED PYTHONHASHSEED the partition varies run-to-run, so structural.json
is NOT byte-deterministic across processes (the committed-artifact contract). The clustering
commands re-exec once under PYTHONHASHSEED=0.

This regression escaped the P1 unit tests because hash randomization is fixed *within* a single
process — it only varies *across* processes. So the real guarantee needs a cross-process build
(below, requires codegraph); the unit tests pin the re-exec logic itself.
"""
import os
import subprocess
import sys

import pytest

from cg_graphify_bridge import cli
from conftest import ROOT, SAMPLE, requires_codegraph


def test_pin_hashseed_reexecs_build_when_unpinned(monkeypatch):
    seen = {}

    def fake_execv(exe, argv):
        seen["exe"], seen["argv"] = exe, argv
        raise RuntimeError("execv")   # halt as a real execv would replace the process

    monkeypatch.setattr(cli.os, "execv", fake_execv)
    monkeypatch.setattr(cli.sys, "argv", ["cg-graphify-bridge", "build", "/repo", "--out", "go"])
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    with pytest.raises(RuntimeError):
        cli._pin_hashseed_for("build")
    assert os.environ["PYTHONHASHSEED"] == "0"            # pinned before re-exec
    assert seen["argv"][1:3] == ["-m", "cg_graphify_bridge"] and "build" in seen["argv"]


def test_pin_hashseed_noop_when_already_pinned(monkeypatch):
    called = []
    monkeypatch.setattr(cli.os, "execv", lambda *a: called.append(1))
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    cli._pin_hashseed_for("build")
    assert called == []                                   # already pinned -> no re-exec (no loop)


def test_pin_hashseed_skips_nonclustering_commands(monkeypatch):
    called = []
    monkeypatch.setattr(cli.os, "execv", lambda *a: called.append(1))
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    for cmd in ("status", "check-semantic", "doctor", "semantic-merge"):
        cli._pin_hashseed_for(cmd)
    assert called == []                                   # the hook-path commands never re-exec


@requires_codegraph
def test_build_byte_deterministic_across_processes(tmp_path):
    """Two independent build processes (default, i.e. UNPINNED, PYTHONHASHSEED in the parent env)
    must produce byte-identical structural.json — the tool self-pins via re-exec. This is the
    real clustering-determinism guarantee; it fails without the PYTHONHASHSEED fix."""
    import shutil
    dst = tmp_path / "s"
    shutil.copytree(SAMPLE, dst)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONHASHSEED"}  # force the default (randomized)
    env["PYTHONPATH"] = str(ROOT / "src")

    def build(outname):
        r = subprocess.run([sys.executable, "-m", "cg_graphify_bridge", "build", str(dst),
                            "--substrate", "codegraph", "--out", outname],
                           env=env, capture_output=True, text=True)
        assert r.returncode == 0, (r.stderr or r.stdout)[-600:]
        return (dst / outname / "structural.json").read_bytes()

    assert build("go-a") == build("go-b")
