"""Phase 1 (Curation + Isolation) — prevention + detection of competing graphify/codegraph
agent integrations, and the opt-in `serve` wrapper.

Prevention (FR1a): `init` writes `disabledMcpjsonServers:["codegraph"]` to block a project-local
codegraph MCP. Detection (FR1b/FR3/FR4, advisory + fail-open): a user-global codegraph MCP,
graphify native-rebuild git hooks, a graphify-native semantic.json. `serve` (FR6): launch
graphify's MCP over the COMMITTED graph, never auto-wired. Docs (FR5).
"""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from cg_graphify_bridge import cli, driver, engine, freshness
from cg_graphify_bridge.adapter import AdaptResult

ROOT = Path(__file__).resolve().parents[1]


def _boom(*a, **k):
    raise RuntimeError("boom")


def _mcp(servers: dict) -> str:
    return json.dumps({"mcpServers": servers})


def _setup(tmp):
    """A repo with a valid committed structural + (bridge) semantic layer + manifest baseline."""
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


# ---------- FR1a: init prevents a local codegraph MCP (disabledMcpjsonServers) ----------

def test_init_writes_codegraph_mcp_disable(tmp_path):
    res = cli.write_claude_hooks(tmp_path, "graphify-out")
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "codegraph" in data["disabledMcpjsonServers"]
    assert res["disabled_mcp_added"] == ["codegraph"]


def test_init_preserves_existing_settings_and_hooks(tmp_path):
    s = tmp_path / ".claude"
    s.mkdir()
    (s / "settings.json").write_text(json.dumps(
        {"model": "opus", "disabledMcpjsonServers": ["foo"],
         "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
    cli.write_claude_hooks(tmp_path, "graphify-out")
    data = json.loads((s / "settings.json").read_text())
    assert data["model"] == "opus"                                   # unrelated key preserved
    assert {"foo", "codegraph"} <= set(data["disabledMcpjsonServers"])  # existing + ours
    stops = json.dumps(data["hooks"]["Stop"])
    assert "echo hi" in stops and "hook-stop" in stops               # existing + ours hook present


def test_init_preserves_existing_disabled_servers(tmp_path):
    s = tmp_path / ".claude"
    s.mkdir()
    (s / "settings.json").write_text(json.dumps({"disabledMcpjsonServers": ["foo", "codegraph"]}))
    res = cli.write_claude_hooks(tmp_path, "graphify-out")
    data = json.loads((s / "settings.json").read_text())
    assert data["disabledMcpjsonServers"].count("codegraph") == 1    # not duplicated
    assert res["disabled_mcp_added"] == []                           # already present


def test_init_disable_idempotent(tmp_path):
    cli.write_claude_hooks(tmp_path, "graphify-out")
    cli.write_claude_hooks(tmp_path, "graphify-out")
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert data["disabledMcpjsonServers"] == ["codegraph"]           # single entry


# ---------- FR1b: detect a codegraph MCP we cannot block (user-global) ----------

def test_detects_codegraph_mcp_global(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    (home / ".claude.json").write_text(_mcp({"codegraph": {"command": "codegraph", "args": ["serve"]}}))
    msg = cli._detect_codegraph_mcp(home, tmp_path)
    assert msg and "codegraph MCP" in msg


def test_detects_codegraph_mcp_local_mcp_json(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    (tmp_path / ".mcp.json").write_text(
        _mcp({"cg": {"command": "node", "args": ["/x/codegraph", "serve", "--mcp"]}}))
    assert cli._detect_codegraph_mcp(home, tmp_path)


def test_no_codegraph_mcp_when_clean(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    (tmp_path / ".mcp.json").write_text(_mcp({"github": {"command": "gh-mcp", "args": ["serve"]}}))
    assert cli._detect_codegraph_mcp(home, tmp_path) is None


def test_codegraph_mcp_malformed_json_fails_open(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    (home / ".claude.json").write_text("{not valid json")
    assert cli._detect_codegraph_mcp(home, tmp_path) is None         # no crash, no finding


# ---------- FR3: detect graphify native-rebuild git hooks ----------

def test_detects_graphify_git_hook(tmp_path):
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "post-commit").write_text("#!/bin/sh\n# graphify-hook-start\n# graphify-hook-end\n")
    assert cli._detect_graphify_rebuild_hooks(tmp_path)


def test_graphify_hook_warning_cites_skip_env(tmp_path):
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "post-checkout").write_text("# graphify-hook-start\n")
    assert "GRAPHIFY_SKIP_HOOK" in cli._detect_graphify_rebuild_hooks(tmp_path)


def test_ignores_graphify_prose_mention(tmp_path):
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    # a hook that merely runs the bridge (no graphify rebuild marker) is NOT flagged
    (hooks / "post-commit").write_text("#!/bin/sh\ncg-graphify-bridge status . --check || true\n")
    assert cli._detect_graphify_rebuild_hooks(tmp_path) is None


# ---------- FR4: detect a graphify-native semantic.json schema clash ----------

def test_flags_native_semantic_json(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "semantic.json").write_text(json.dumps({"nodes": [], "edges": []}))  # no layer marker
    msg = cli._detect_semantic_schema_clash(out)
    assert msg and "layer" in msg


def test_passes_valid_bridge_semantic_json(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    driver.write_semantic({"semantic_nodes": [], "semantic_edges": [], "stats": {}}, out)
    assert cli._detect_semantic_schema_clash(out) is None


def test_missing_semantic_json_no_finding(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    assert cli._detect_semantic_schema_clash(out) is None


# ---------- aggregator + wiring (advisory, fail-open, exit-code-neutral) ----------

def test_check_conflicts_aggregates(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    (tmp_path / ".mcp.json").write_text(_mcp({"codegraph": {"command": "codegraph", "args": ["serve"]}}))
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "semantic.json").write_text(json.dumps({"nodes": []}))    # also a clash
    findings = cli._check_conflicts(tmp_path, out, home=home)
    assert len(findings) >= 2


def test_one_probe_error_does_not_suppress_others(tmp_path, monkeypatch):
    home = tmp_path / "h"
    home.mkdir()
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "semantic.json").write_text(json.dumps({"nodes": []}))    # clash finding
    monkeypatch.setattr(cli, "_detect_codegraph_mcp", _boom)         # one probe raises
    findings = cli._check_conflicts(tmp_path, out, home=home)
    assert any("layer" in f for f in findings)                       # semantic finding survived


def test_doctor_includes_conflicts(tmp_path):
    (tmp_path / ".mcp.json").write_text(
        _mcp({"codegraph": {"command": "codegraph", "args": ["serve", "--mcp"]}}))
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    rep = cli.doctor_report(tmp_path, home=fake_home)
    assert "conflicts" in rep and any("codegraph MCP" in c for c in rep["conflicts"])


def test_doctor_exit_code_unchanged_on_conflict(tmp_path, monkeypatch):
    (tmp_path / ".mcp.json").write_text(_mcp({"codegraph": {"command": "codegraph", "args": ["serve"]}}))
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.delenv("CODEGRAPH_BIN", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda n: "/usr/bin/" + n)  # all deps "present"
    (tmp_path / "node_modules" / "typescript").mkdir(parents=True)
    rep = cli.doctor_report(tmp_path, home=fake_home)
    assert rep["conflicts"]                                          # conflict surfaced
    assert rep["ok"] is True                                        # but deps drive ok -> --strict won't exit


def test_status_warns_on_semantic_clash(tmp_path):
    repo, out = _setup(tmp_path)
    (out / "semantic.json").write_text(json.dumps({"nodes": []}))   # clobber w/ native shape
    p = cli._status(SimpleNamespace(repo=str(repo), out="graphify-out", scopes=None,
                                    check=False, quiet=True))
    assert any("layer" in w for w in p["warnings"])


# ---------- FR6: opt-in serve (over the committed graph; never auto-wired) ----------

def test_serve_materializes_when_graph_missing(tmp_path, monkeypatch):
    repo, out = _setup(tmp_path)
    assert not (out / "graph.json").exists()
    import graphify.serve as gs
    calls = []
    monkeypatch.setattr(gs, "serve", lambda p: calls.append(p))
    cli._serve(SimpleNamespace(repo=str(repo), out="graphify-out"))
    assert (out / "graph.json").exists()                            # materialized for the MCP
    assert calls and calls[0].endswith("graphify-out/graph.json")


def test_serve_invokes_graphify_serve_with_committed_graph(tmp_path, monkeypatch):
    repo, out = _setup(tmp_path)
    driver.materialize(out)                                         # graph.json already present
    import graphify.serve as gs
    calls = []
    monkeypatch.setattr(gs, "serve", lambda p: calls.append(p))
    cli._serve(SimpleNamespace(repo=str(repo), out="graphify-out"))
    assert len(calls) == 1
    assert Path(calls[0]).name == "graph.json" and Path(calls[0]).parent.name == "graphify-out"


def test_init_does_not_wire_serve(tmp_path):
    cli.write_claude_hooks(tmp_path, "graphify-out")
    assert "serve" not in (tmp_path / ".claude" / "settings.json").read_text()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    cli.install_freshness_hooks(tmp_path, "graphify-out")
    for h in ("post-commit", "post-merge", "post-checkout"):
        assert "serve" not in (tmp_path / ".git" / "hooks" / h).read_text()
    assert "cg-graphify-bridge serve" not in cli._read_template("graph-build.yml")  # not in CI either


# ---------- FR5: docs ----------

def test_setup_documents_isolation_and_serve():
    txt = (ROOT / "docs" / "setup.md").read_text()
    assert "disabledMcpjsonServers" in txt
    assert "GRAPHIFY_SKIP_HOOK" in txt
    assert "codegraph install" in txt
    assert "serve" in txt


def test_agents_md_has_isolation_note(tmp_path):
    txt = cli._write_agents_md(tmp_path, "graphify-out").read_text()
    assert "disabledMcpjsonServers" in txt and "codegraph install" in txt
    assert "serve" in txt
