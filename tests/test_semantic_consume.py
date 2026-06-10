"""Phase 3 P3b (R4, KD7) — semantic-prep/merge consume the committed structural.json layer
instead of re-extracting + re-clustering.

Success criteria:
- the prep path NEVER calls cluster.cluster (re-clustering on a dev box is the one engine-drift
  source the committed-artifact model removes; CI's communities are read from structural.json);
- merged semantic edges key to the structural layer's composite ids (or doc nodes), nothing else;
- a missing structural layer fails loudly (the dev must pull/build it first).
"""
import json
from types import SimpleNamespace

from cg_graphify_bridge import adapter, cli, driver, semantic
from cg_graphify_bridge.adapter import AdaptResult


def _fused():
    nodes = [
        {"id": "cg:aaa", "label": "A", "file_type": "code", "source_file": "a.ts",
         "source_location": "L1", "metadata": {"cg_kind": "function"}},
        {"id": "cg:bbb", "label": "B", "file_type": "code", "source_file": "b.ts",
         "source_location": "L1", "metadata": {"cg_kind": "function"}},
    ]
    edges = [{"source": "cg:bbb", "target": "cg:aaa", "relation": "calls", "context": "calls",
              "confidence": "EXTRACTED", "weight": 1.0}]
    return {"adapt": AdaptResult(nodes, edges, {}, {"composite_nodes": 2}),
            "communities": {"c0": ["cg:aaa", "cg:bbb"]},
            "god_nodes": [{"id": "cg:aaa", "label": "A", "degree": 1}],
            "surprising": []}


def test_from_structural_roundtrips(tmp_path):
    driver.write_structural(_fused(), tmp_path)
    structural = driver.read_layer(tmp_path, "structural")
    res = adapter.from_structural(structural)
    assert {n["id"] for n in res.nodes} == {"cg:aaa", "cg:bbb"}
    # the reconstructed res is usable for label resolution (the merge path depends on this)
    idx = semantic._label_index(res)
    assert "cg:aaa" in idx[semantic._norm("A")]


def test_semantic_prep_consumes_structural_no_recluster(tmp_path, monkeypatch):
    out = tmp_path / "graphify-out"
    driver.write_structural(_fused(), out)                  # committed structural layer present
    (tmp_path / "README.md").write_text("The A function authenticates; B calls it.\n")
    called = []
    monkeypatch.setattr(driver.cluster, "cluster", lambda *a, **k: called.append(1) or {})
    args = SimpleNamespace(repo=str(tmp_path), out="graphify-out",
                           max_nodes=50, max_docs=None, filter=None)
    cli._semantic_prep(args)
    assert called == []                                     # cluster.cluster NEVER invoked (R4)
    assert (out / ".cache" / "semantic" / "tasks").is_dir()
    assert list((out / ".cache" / "semantic" / "tasks").glob("*.json"))


def test_semantic_merge_consumes_structural_no_recluster(tmp_path, monkeypatch):
    out = tmp_path / "graphify-out"
    driver.write_structural(_fused(), out)
    pdir = out / ".cache" / "semantic" / "payloads"
    pdir.mkdir(parents=True)
    (pdir / "000.json").write_text(json.dumps({
        "nodes": [{"id": "doc:x", "label": "x", "file_type": "document"}],
        "edges": [{"source": "doc:x", "target": "cg:aaa", "relation": "references"}],
    }))
    called = []
    monkeypatch.setattr(driver.cluster, "cluster", lambda *a, **k: called.append(1) or {})
    args = SimpleNamespace(repo=str(tmp_path), out="graphify-out",
                           activate=False, keep_scratch=True)
    cli._semantic_merge(args)
    assert called == []                                     # no re-cluster on merge either
    assert (out / "semantic.json").exists() and (out / "graph.json").exists()


def test_semantic_edge_targets_in_structural_ids(tmp_path):
    out = tmp_path / "graphify-out"
    driver.write_structural(_fused(), out)
    structural = driver.read_layer(out, "structural")
    res = adapter.from_structural(structural)
    pdir = out / ".cache" / "semantic" / "payloads"
    pdir.mkdir(parents=True)
    (pdir / "000.json").write_text(json.dumps({
        "nodes": [{"id": "doc:x", "label": "design", "file_type": "document"}],
        "edges": [
            {"source": "doc:x", "target": "cg:aaa", "relation": "references"},   # exact composite id
            {"source": "doc:x", "target": "", "target_label": "B", "relation": "explains"},  # by label
        ],
    }))
    combined = semantic.merge_payloads(res, out)
    driver.write_semantic(combined, out)
    sem = driver.read_layer(out, "semantic")
    struct_ids = {n["id"] for n in structural["nodes"]}
    doc_ids = {n["id"] for n in sem["semantic_nodes"]}
    assert sem["semantic_edges"], "expected kept edges"
    for e in sem["semantic_edges"]:
        assert e["target"] in struct_ids or e["target"] in doc_ids   # keyed only to known ids
    # the label-only edge resolved to the structural composite id for B
    assert any(e["target"] == "cg:bbb" for e in sem["semantic_edges"])


def test_semantic_prep_errors_without_structural(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    args = SimpleNamespace(repo=str(tmp_path), out="graphify-out",
                           max_nodes=50, max_docs=None, filter=None)
    try:
        cli._semantic_prep(args)
        assert False, "expected SystemExit when structural.json is absent"
    except SystemExit as e:
        assert "structural.json" in str(e)
