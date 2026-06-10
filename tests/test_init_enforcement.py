"""Phase 6 P6b/P6c (R7/R8, KD9/KD10) — init wires the Claude hooks into .claude/settings.json
(additive, idempotent) and configures the semantic.json union merge driver.
"""
import json
import subprocess
from types import SimpleNamespace

from cg_graphify_bridge import cli, driver
from cg_graphify_bridge.adapter import AdaptResult


def _fake_build(repo, out_name, **kw):
    driver.write_structural({"adapt": AdaptResult([], [], {}, {}), "communities": {},
                             "god_nodes": [], "surprising": []}, repo / out_name)
    return {"out_dir": str(repo / out_name)}


# ---------- P6b: Claude hook wiring ----------

def test_write_claude_hooks_wires_sessionstart_and_stop(tmp_path):
    res = cli.write_claude_hooks(tmp_path, "graphify-out")
    assert set(res["added"]) == {"SessionStart", "Stop"}
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "SessionStart" in data["hooks"] and "Stop" in data["hooks"]
    blob = json.dumps(data["hooks"])
    assert "hook-sessionstart" in blob and "hook-stop" in blob


def test_claude_hooks_idempotent(tmp_path):
    cli.write_claude_hooks(tmp_path, "graphify-out")
    res2 = cli.write_claude_hooks(tmp_path, "graphify-out")
    assert res2["added"] == []                                  # nothing added on re-run
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert len(data["hooks"]["Stop"]) == 1                      # not duplicated


def test_claude_hooks_preserve_existing_settings(tmp_path):
    s = tmp_path / ".claude"
    s.mkdir()
    (s / "settings.json").write_text(json.dumps(
        {"model": "opus", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}]}}))
    cli.write_claude_hooks(tmp_path, "graphify-out")
    data = json.loads((s / "settings.json").read_text())
    assert data["model"] == "opus"                              # unrelated keys preserved
    stops = json.dumps(data["hooks"]["Stop"])
    assert "echo existing" in stops and "hook-stop" in stops    # existing + ours both present


# ---------- P6c: semantic.json union merge driver ----------

def _sem(edges):
    return {"schema_version": 1, "layer": "semantic",
            "semantic_nodes": [{"id": "doc:x", "label": "x", "file_type": "document"}],
            "semantic_edges": edges, "stats": {}}


def _e(target):
    return {"source": "doc:x", "target": target, "relation": "references"}


def test_merge_driver_unions_overlays(tmp_path):
    ours, theirs = tmp_path / "ours.json", tmp_path / "theirs.json"
    ours.write_text(json.dumps(_sem([_e("cg:a")])))
    theirs.write_text(json.dumps(_sem([_e("cg:b")])))
    cli._merge_driver(SimpleNamespace(ours=str(ours), theirs=str(theirs)))
    merged = json.loads(ours.read_text())                       # result written to OURS (%A)
    assert {e["target"] for e in merged["semantic_edges"]} == {"cg:a", "cg:b"}
    assert merged["layer"] == "semantic"


def test_merge_driver_deterministic_order_independent(tmp_path):
    def run(a, b):
        o, t = tmp_path / "o.json", tmp_path / "t.json"
        o.write_text(json.dumps(_sem(a)))
        t.write_text(json.dumps(_sem(b)))
        cli._merge_driver(SimpleNamespace(ours=str(o), theirs=str(t)))
        return o.read_text()
    assert run([_e("cg:a")], [_e("cg:b")]) == run([_e("cg:b")], [_e("cg:a")])   # symmetric union


def test_init_configures_merge_driver(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "build_repo", _fake_build)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    cli._init(SimpleNamespace(repo=str(tmp_path), out="graphify-out", substrate="auto", scopes=None))
    drv = subprocess.run(["git", "-C", str(tmp_path), "config", "--get", "merge.cg-semantic.driver"],
                         capture_output=True, text=True).stdout.strip()
    assert "merge-driver" in drv and "%A %B" in drv
