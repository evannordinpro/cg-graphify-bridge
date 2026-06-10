"""Phase 6 P6a (R7/R10, KD9) — the Claude SessionStart/Stop hook subcommands.

Stop: blocks session-end when the semantic overlay is stale OR refreshed-but-uncommitted;
allows when fresh+committed; the escape hatch force-allows; any error FAILS OPEN (never bricks).
SessionStart: injects a freshness advisory when stale, is silent when fresh, and materializes
the gitignored fused graph.json if missing. Hooks resolve the repo via git; tests pin it.
"""
import json
import subprocess
from types import SimpleNamespace

from cg_graphify_bridge import cli, driver, engine, freshness
from cg_graphify_bridge.adapter import AdaptResult


def _boom(*a, **k):
    raise RuntimeError("boom")


def _setup(tmp):
    repo = tmp
    (repo / "src").mkdir()
    (repo / "docs").mkdir()
    (repo / "src" / "a.ts").write_text("export function A(){return 1}\n")
    (repo / "docs" / "d.md").write_text("The A function does X.\n")
    out = repo / "graphify-out"
    nodes = [{"id": "cg:a", "label": "A", "file_type": "code", "source_file": "src/a.ts",
              "source_location": "L1", "metadata": {"cg_kind": "function"}}]
    driver.write_structural({"adapt": AdaptResult(nodes, [], {}, {}), "communities": {"c0": ["cg:a"]},
                             "god_nodes": [], "surprising": []}, out)
    driver.write_semantic({"semantic_nodes": [{"id": "doc:d", "label": "d.md", "file_type": "document"}],
                           "semantic_edges": [{"source": "doc:d", "target": "cg:a",
                                               "relation": "references"}], "stats": {}}, out)
    freshness.write_manifest(out, repo, ["src"], engine_stamp=engine.detect_engine())
    freshness.write_semantic_freshness(out, repo)
    return repo, out


def _args():
    return SimpleNamespace(out="graphify-out")


# ---------- Stop ----------

def test_stop_blocks_when_semantic_stale(tmp_path, monkeypatch, capsys):
    repo, _ = _setup(tmp_path)
    (repo / "docs" / "d.md").write_text("changed\n")          # doc edit -> stale
    monkeypatch.setattr(cli, "_hook_repo", lambda: repo)
    cli._hook_stop(_args())
    d = json.loads(capsys.readouterr().out)
    assert d["decision"] == "block" and "semantic-merge" in d["reason"]


def test_stop_allows_when_fresh(tmp_path, monkeypatch, capsys):
    repo, _ = _setup(tmp_path)
    monkeypatch.setattr(cli, "_hook_repo", lambda: repo)
    cli._hook_stop(_args())
    assert capsys.readouterr().out.strip() == ""              # no block


def test_stop_blocks_when_committed_overlay_is_uncommitted(tmp_path, monkeypatch, capsys):
    repo, out = _setup(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "i"],
                   cwd=repo, check=True)
    (out / "semantic.json").write_text((out / "semantic.json").read_text() + "\n")  # fresh but dirty
    monkeypatch.setattr(cli, "_hook_repo", lambda: repo)
    cli._hook_stop(_args())
    d = json.loads(capsys.readouterr().out)
    assert d["decision"] == "block" and "uncommitted" in d["reason"]


def test_stop_escape_hatch_allows(tmp_path, monkeypatch, capsys):
    repo, _ = _setup(tmp_path)
    (repo / "docs" / "d.md").write_text("changed\n")          # stale...
    monkeypatch.setattr(cli, "_hook_repo", lambda: repo)
    monkeypatch.setenv("CG_BRIDGE_DISABLE", "1")              # ...but escaped
    cli._hook_stop(_args())
    assert capsys.readouterr().out.strip() == ""


def test_stop_fail_open_on_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_hook_repo", lambda: tmp_path)
    monkeypatch.setattr(freshness, "compute_status", _boom)   # guard error
    cli._hook_stop(_args())
    assert capsys.readouterr().out.strip() == ""              # fail open -> no block


# ---------- SessionStart ----------

def test_sessionstart_advises_when_stale(tmp_path, monkeypatch, capsys):
    repo, _ = _setup(tmp_path)
    (repo / "docs" / "d.md").write_text("changed\n")
    monkeypatch.setattr(cli, "_hook_repo", lambda: repo)
    cli._hook_sessionstart(_args())
    d = json.loads(capsys.readouterr().out)
    assert d["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "semantic" in d["hookSpecificOutput"]["additionalContext"].lower()


def test_sessionstart_silent_when_fresh(tmp_path, monkeypatch, capsys):
    repo, _ = _setup(tmp_path)
    monkeypatch.setattr(cli, "_hook_repo", lambda: repo)
    cli._hook_sessionstart(_args())
    assert capsys.readouterr().out.strip() == ""


def test_sessionstart_materializes_missing_fused(tmp_path, monkeypatch):
    repo, out = _setup(tmp_path)
    assert not (out / "graph.json").exists()
    monkeypatch.setattr(cli, "_hook_repo", lambda: repo)
    cli._hook_sessionstart(_args())
    assert (out / "graph.json").exists()                      # materialized for the consumer


def test_sessionstart_fail_open_on_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_hook_repo", lambda: tmp_path)
    monkeypatch.setattr(freshness, "compute_status", _boom)
    cli._hook_sessionstart(_args())
    assert capsys.readouterr().out.strip() == ""
