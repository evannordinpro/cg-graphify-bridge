"""Phase 4 P4b (R4/R7, KD9) — `status` (rich freshness + exact refresh commands) and
`check-semantic` (the Stop-hook gate: exit codes + --require-committed).

Success criteria:
- status flags semantic stale on a doc change and emits a copy-pasteable refresh command;
- a code-only (non-linked) edit shows structural stale but semantic fresh (no semantic advice);
- check-semantic exits non-zero when stale, zero when fresh;
- --require-committed also blocks when semantic.json is fresh-but-uncommitted, passes when committed.
"""
import subprocess
from types import SimpleNamespace

import pytest

from cg_graphify_bridge import cli, driver, engine, freshness
from cg_graphify_bridge.adapter import AdaptResult


def _setup(tmp):
    repo = tmp
    (repo / "src").mkdir()
    (repo / "docs").mkdir()
    (repo / "src" / "a.ts").write_text("export function A(){return 1}\n")   # linked
    (repo / "src" / "b.ts").write_text("export function B(){return 2}\n")   # not linked
    (repo / "docs" / "d.md").write_text("The A function does X.\n")
    out = repo / "graphify-out"
    nodes = [{"id": "cg:a", "label": "A", "file_type": "code", "source_file": "src/a.ts",
              "source_location": "L1", "metadata": {"cg_kind": "function"}},
             {"id": "cg:b", "label": "B", "file_type": "code", "source_file": "src/b.ts",
              "source_location": "L1", "metadata": {"cg_kind": "function"}}]
    driver.write_structural({"adapt": AdaptResult(nodes, [], {}, {}),
                             "communities": {"c0": ["cg:a", "cg:b"]}, "god_nodes": [],
                             "surprising": []}, out)
    driver.write_semantic({"semantic_nodes": [{"id": "doc:d", "label": "d.md", "file_type": "document"}],
                           "semantic_edges": [{"source": "doc:d", "target": "cg:a",
                                               "relation": "references"}], "stats": {}}, out)
    freshness.write_manifest(out, repo, ["src"], engine_stamp=engine.detect_engine())
    freshness.write_semantic_freshness(out, repo)
    return repo, out


def _status(repo):
    return cli._status(SimpleNamespace(repo=str(repo), out="graphify-out", scopes=None,
                                       check=False, quiet=True))


# ---------- status ----------

def test_status_detects_semantic_stale_on_doc_change(tmp_path):
    repo, _ = _setup(tmp_path)
    (repo / "docs" / "d.md").write_text("The A function does X and now also Y.\n")
    p = _status(repo)
    assert p["semantic"]["state"] == "stale"
    assert "semantic" in p["advice"]


def test_status_emits_copyable_command(tmp_path):
    repo, _ = _setup(tmp_path)
    (repo / "docs" / "d.md").write_text("changed\n")
    cmd = _status(repo)["advice"]["semantic"]
    assert "semantic-prep" in cmd and "semantic-merge" in cmd and str(repo) in cmd


def test_status_code_only_edit_not_stale(tmp_path):
    repo, _ = _setup(tmp_path)
    (repo / "src" / "b.ts").write_text("export function B(){return 99}\n")  # non-linked code
    p = _status(repo)
    assert p["structural"]["state"] == "stale"     # build due
    assert p["semantic"]["state"] == "fresh"       # overlay NOT due
    assert "semantic" not in p["advice"]           # so no semantic command is emitted


# ---------- check-semantic ----------

def _check(repo, require_committed=False):
    cli._check_semantic(SimpleNamespace(repo=str(repo), out="graphify-out",
                                        require_committed=require_committed, quiet=True))


def test_check_semantic_fresh_exit_zero(tmp_path):
    repo, _ = _setup(tmp_path)
    _check(repo)   # fresh -> returns without raising (exit 0)


def test_check_semantic_stale_exit_nonzero(tmp_path):
    repo, _ = _setup(tmp_path)
    (repo / "docs" / "d.md").write_text("edited\n")
    with pytest.raises(SystemExit) as ei:
        _check(repo)
    assert ei.value.code == 1


def test_check_semantic_require_committed_gate(tmp_path):
    repo, out = _setup(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=repo, check=True)
    _check(repo, require_committed=True)            # fresh + committed -> exit 0
    (out / "semantic.json").write_text((out / "semantic.json").read_text() + "\n")  # now dirty
    with pytest.raises(SystemExit):                 # fresh but uncommitted -> blocked
        _check(repo, require_committed=True)
