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
