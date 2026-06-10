"""Phase 4 P4d (R1/R3, KD12) — `init` one-shot repo setup: build + gitignore + AGENTS.md +
.gitattributes + (best-effort) git hooks; idempotent.

build_repo is monkeypatched to a stub structural write so the orchestration is tested without a
node/codegraph substrate (build itself is covered by the build/determinism/real-repo tests).
"""
from types import SimpleNamespace

from cg_graphify_bridge import cli, driver
from cg_graphify_bridge.adapter import AdaptResult


def _fake_build(repo, out_name, **kw):
    out = repo / out_name
    nodes = [{"id": "cg:a", "label": "A", "file_type": "code", "source_file": "src/a.ts",
              "source_location": "L1", "metadata": {"cg_kind": "function"}}]
    driver.write_structural({"adapt": AdaptResult(nodes, [], {}, {}), "communities": {},
                             "god_nodes": [], "surprising": []}, out)  # real structural.json + gitignore
    return {"out_dir": str(out), "nodes": 1}


def _args(repo):
    return SimpleNamespace(repo=str(repo), out="graphify-out", substrate="auto", scopes=None)


def test_init_creates_artifacts_and_gitignore(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "build_repo", _fake_build)
    cli._init(_args(tmp_path))
    out = tmp_path / "graphify-out"
    assert (out / "structural.json").exists()
    assert "graph.json" in (out / ".gitignore").read_text()       # fused cache gitignored
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".gitattributes").exists()
    assert "semantic.json merge=cg-semantic" in (tmp_path / ".gitattributes").read_text()


def test_init_writes_agents_md(tmp_path):
    txt = cli._write_agents_md(tmp_path, "graphify-out").read_text()
    assert "structural.json" in txt and "semantic.json" in txt and "graph.json" in txt
    assert "cg-graphify-bridge status" in txt                      # tells consumers how to check freshness


def test_init_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "build_repo", _fake_build)
    cli._init(_args(tmp_path))
    agents1 = (tmp_path / "AGENTS.md").read_text()
    gattr1 = (tmp_path / ".gitattributes").read_text()
    cli._init(_args(tmp_path))                                     # re-run
    assert (tmp_path / "AGENTS.md").read_text() == agents1         # not duplicated/clobbered
    assert (tmp_path / ".gitattributes").read_text() == gattr1
    assert agents1.count(cli._AGENTS_MARK) == 1


def test_init_preserves_existing_agents_md(tmp_path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("# My existing agent notes\n")
    monkeypatch.setattr(cli, "build_repo", _fake_build)
    cli._init(_args(tmp_path))
    txt = (tmp_path / "AGENTS.md").read_text()
    assert "My existing agent notes" in txt and cli._AGENTS_MARK in txt  # appended, not clobbered
