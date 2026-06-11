"""Phase 3 semantic-overlay tests — trace R4,R7 / D6,D17."""
import json
from pathlib import Path

from cg_graphify_bridge import adapter, driver, semantic
from conftest import SAMPLE


def _auth_service_id(res):
    return next(n["id"] for n in res.nodes if n["label"] == "AuthService")


def test_subagent_context_contains_no_source_code(cg_db):
    """R7: the subagent boundary carries identity metadata + docs, never code."""
    res = adapter.adapt(cg_db)
    ctx = semantic.build_subagent_context(res, docs=["The AuthService handles login."])
    assert ctx["code_nodes"], "expected a curated code-node list"
    for cn in ctx["code_nodes"]:
        assert set(cn.keys()) <= {"id", "label", "file", "cg_kind"}
        assert not any(k in cn for k in ("source", "body", "code", "signature"))


def test_semantic_edge_targets_valid_composite_id(cg_db):
    res = adapter.adapt(cg_db)
    aid = _auth_service_id(res)
    payload = {
        "nodes": [{"id": "doc:design", "label": "design.md", "file_type": "document"}],
        "edges": [{"source": "doc:design", "target": aid, "relation": "references"}],
    }
    merged = semantic.merge_semantic(payload, res)
    assert len(merged["semantic_edges"]) == 1
    assert merged["semantic_edges"][0]["target"] == aid
    assert merged["dangling"] == []


def test_dangling_semantic_edges_pruned_and_reported(cg_db):
    res = adapter.adapt(cg_db)
    payload = {
        "nodes": [{"id": "doc:design", "label": "d", "file_type": "document"}],
        "edges": [{"source": "doc:design", "target": "cg:doesnotexist", "relation": "references"}],
    }
    merged = semantic.merge_semantic(payload, res)
    assert merged["semantic_edges"] == []
    assert len(merged["dangling"]) == 1


def test_subagent_miss_falls_back_to_full_lookup(cg_db):
    """D17: target given by label only -> unique label match resolves it."""
    res = adapter.adapt(cg_db)
    payload = {
        "nodes": [{"id": "doc:design", "label": "d", "file_type": "document"}],
        "edges": [{"source": "doc:design", "target": "", "target_label": "AuthService",
                   "relation": "references"}],
    }
    merged = semantic.merge_semantic(payload, res)
    assert merged["fallback_resolved"] == 1
    assert merged["semantic_edges"][0]["target"] == _auth_service_id(res)


def test_ambiguous_label_does_not_falsely_resolve(cg_db):
    """'process' exists twice (collision) -> must NOT auto-resolve, goes dangling."""
    res = adapter.adapt(cg_db)
    payload = {
        "nodes": [{"id": "doc:d", "label": "d", "file_type": "document"}],
        "edges": [{"source": "doc:d", "target": "", "target_label": "process",
                   "relation": "references"}],
    }
    merged = semantic.merge_semantic(payload, res)
    assert merged["fallback_resolved"] == 0
    assert len(merged["dangling"]) == 1


def test_skill_overlay_patch_present():
    p = Path(__file__).resolve().parents[1] / "overlay" / "SKILL_overlay.md"
    assert p.exists()
    txt = p.read_text().lower()
    assert "composite" in txt and "codegraph" in txt and "target" in txt


def test_module_ref_resolves_via_file_stem(cg_db):
    """Task 5: a doc ref to a module name resolves to the file node by extension-stripped stem."""
    res = adapter.adapt(cg_db)
    payload = {
        "nodes": [{"id": "doc:d", "label": "d", "file_type": "document"}],
        "edges": [{"source": "doc:d", "target": "", "target_label": "billing", "relation": "explains"}],
    }
    merged = semantic.merge_semantic(payload, res)
    assert merged["fallback_resolved"] == 1
    fnode = next(n for n in res.nodes if n["id"] == merged["semantic_edges"][0]["target"])
    assert fnode["metadata"]["cg_kind"] == "file" and "billing" in fnode["label"]


def test_prep_tasks_and_merge_payloads_roundtrip(cg_db, tmp_path):
    """Scaling: prep writes per-doc tasks; merge consumes payloads into the overlay."""
    res = adapter.adapt(cg_db)
    fused = driver.build_fused(cg_db)
    out = tmp_path / "out"
    info = semantic.prep_tasks(res, fused, SAMPLE, out, max_nodes=50)
    assert info["tasks"] and info["tasks_dir"].exists()
    aid = _auth_service_id(res)
    pdir = out / ".cache" / "semantic" / "payloads"
    pdir.mkdir(parents=True)
    (pdir / "000.json").write_text(json.dumps({
        "nodes": [{"id": "doc:x", "label": "x", "file_type": "document"}],
        "edges": [{"source": "doc:x", "target": aid, "relation": "references"}],
    }))
    combined = semantic.merge_payloads(res, out)
    assert combined["stats"]["kept"] == 1
    assert combined["semantic_edges"][0]["target"] == aid


# ---------- dispatches: agent-confirmed dynamic wiring (pure-unit, no cg_db) ----------

def _mini_nodes():
    def n(nid, label, kind="function", s=1, e=1):
        return {"id": nid, "label": label, "file_type": "code", "source_file": "src/a.py",
                "source_location": f"L{s}",
                "metadata": {"cg_kind": kind, "qualified_name": label,
                             "start_line": s, "end_line": e}}
    return [n("cg:file", "a.py", kind="file", s=1, e=6),
            n("cg:site", "wire", s=4, e=5),
            n("cg:handler", "handler", s=1, e=2)]


def test_dispatches_edge_with_code_source_kept():
    res = adapter.AdaptResult(_mini_nodes(), [], {}, {})
    payload = {"nodes": [], "edges": [
        {"source": "cg:site", "target": "cg:handler", "relation": "dispatches"}]}
    merged = semantic.merge_semantic(payload, res)
    assert merged["semantic_edges"] == payload["edges"] and merged["dangling"] == []


def test_invented_edge_source_pruned():
    res = adapter.AdaptResult(_mini_nodes(), [], {}, {})
    payload = {"nodes": [], "edges": [
        {"source": "cg:invented", "target": "cg:handler", "relation": "dispatches"}]}
    merged = semantic.merge_semantic(payload, res)
    assert merged["semantic_edges"] == [] and len(merged["dangling"]) == 1


def test_dispatch_candidates_suggest_enclosing_source(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text(
        "def handler(args):\n    pass\n\ndef wire(sub):\n    sub.set_defaults(func=handler)\n")
    structural = {"nodes": _mini_nodes(), "edges": [], "communities": {}, "god_nodes": []}
    cands = semantic.dispatch_candidates(tmp_path, structural)
    assert [c["target"] for c in cands] == ["cg:handler"]
    c = cands[0]
    assert c["evidence"] == "src/a.py:5"
    assert c["suggested_source"] == "cg:site" and c["suggested_source_label"] == "wire"
