"""Phase 3 P3a (R3/R8, KD7) — split write_artifact into committed structural.json +
semantic.json layers with a lazily-materialized, gitignored fused graph.json.

Success criteria asserted here:
- build emits structural.json + semantic.json (each schema-stamped);
- graph.json + .cache/ are gitignored in the out dir (no fused merge wars);
- materialize(layers) == direct fusion of the same in-memory fused, BYTE-for-byte
  (the JSON round-trip through the layers is lossless);
- schema_version is present on structural + semantic + manifest;
- materialize requires structural and tolerates a missing semantic layer.

Uses hand-built fused/semantic dicts (no codegraph/clustering) so the writer/materializer
determinism is the unit under test and the suite runs anywhere.
"""
import json

import networkx as nx
import pytest
from networkx.readwrite import json_graph

from cg_graphify_bridge import driver, engine, freshness
from cg_graphify_bridge.adapter import AdaptResult


def _fused():
    nodes = [  # out of order on purpose — the writer must sort
        {"id": "cg:bbb", "label": "B", "file_type": "code", "source_file": "b.ts",
         "source_location": "L1", "metadata": {"cg_kind": "function"}},
        {"id": "cg:aaa", "label": "A", "file_type": "code", "source_file": "a.ts",
         "source_location": "L1", "metadata": {"cg_kind": "function"}},
    ]
    edges = [
        {"source": "cg:bbb", "target": "cg:aaa", "relation": "calls", "context": "calls",
         "confidence": "EXTRACTED", "weight": 1.0},
        {"source": "cg:aaa", "target": "cg:bbb", "relation": "references", "context": "references",
         "confidence": "EXTRACTED", "weight": 1.0},
    ]
    res = AdaptResult(nodes, edges, {}, {"composite_nodes": 2})
    return {
        "adapt": res,
        "communities": {"c0": ["cg:aaa", "cg:bbb"]},
        "god_nodes": [{"id": "cg:aaa", "label": "A", "degree": 1},
                      {"id": "cg:bbb", "label": "B", "degree": 1}],
        "surprising": [{"source": "cg:bbb", "target": "cg:aaa", "_score": 0.5}],
    }


def _semantic():
    return {
        "semantic_nodes": [{"id": "doc:design", "label": "design.md", "file_type": "document"}],
        "semantic_edges": [{"source": "doc:design", "target": "cg:aaa", "relation": "references",
                            "context": "semantic", "confidence": "INFERRED", "weight": 1.0}],
        "stats": {"kept": 1, "dangling": 0, "fallback": 0},
    }


def _reference_graph_bytes(fused, semantic, path):
    """Frozen pre-split fusion: build graph.json directly from the in-memory fused object.
    materialize() (which goes via the JSON layers) must reproduce this byte-for-byte."""
    res = fused["adapt"]
    id2comm = {nid: c for c, ids in fused["communities"].items() for nid in ids}
    god_ids = {g["id"] for g in fused["god_nodes"]}
    FG = nx.DiGraph()
    for n in sorted(res.nodes, key=lambda n: n["id"]):
        attrs = {k: v for k, v in n.items() if k != "id"}
        attrs["community"] = id2comm.get(n["id"])
        attrs["god_node"] = n["id"] in god_ids
        FG.add_node(n["id"], **attrs)
    for e in sorted(res.edges, key=lambda e: (e["source"], e["target"], e["relation"])):
        FG.add_edge(e["source"], e["target"], relation=e["relation"], context=e["context"],
                    confidence=e["confidence"], weight=e["weight"])
    if semantic:
        for n in sorted(semantic["semantic_nodes"], key=lambda n: n["id"]):
            attrs = {k: v for k, v in n.items() if k != "id"}
            attrs.setdefault("file_type", "document")
            FG.add_node(n["id"], **attrs)
        for e in sorted(semantic["semantic_edges"],
                        key=lambda e: (e.get("source", ""), e.get("target", ""), e.get("relation", ""))):
            FG.add_edge(e["source"], e["target"], relation=e.get("relation", "references"),
                        context=e.get("context", "semantic"),
                        confidence=e.get("confidence", "INFERRED"), weight=e.get("weight", 1.0))
    path.write_text(json.dumps(json_graph.node_link_data(FG, edges="edges"), indent=2,
                               sort_keys=True, ensure_ascii=False) + "\n")


def test_split_emits_structural_and_semantic(tmp_path):
    driver.write_structural(_fused(), tmp_path)
    driver.write_semantic(_semantic(), tmp_path)
    s = json.loads((tmp_path / "structural.json").read_text())
    sem = json.loads((tmp_path / "semantic.json").read_text())
    assert s["layer"] == "structural" and s["nodes"] and s["edges"]
    assert [n["id"] for n in s["nodes"]] == ["cg:aaa", "cg:bbb"]   # sorted
    assert sem["layer"] == "semantic" and sem["semantic_edges"]
    # structural.json must NOT contain graph.json's fused/derived shape (it's the source layer)
    assert "nodes" in s and "links" not in s


def test_graph_json_gitignored(tmp_path):
    driver.write_structural(_fused(), tmp_path)
    gi = (tmp_path / ".gitignore").read_text()
    assert "graph.json" in gi and ".cache/" in gi


def test_materialize_equals_presplit_fused(tmp_path):
    fused, sem = _fused(), _semantic()
    # path A: split to JSON layers, then materialize the fused graph
    driver.write_structural(fused, tmp_path)
    driver.write_semantic(sem, tmp_path)
    driver.materialize(tmp_path)
    got = (tmp_path / "graph.json").read_bytes()
    # path B: reference fusion straight from the in-memory object (no layer round-trip)
    ref = tmp_path / "ref"
    ref.mkdir()
    _reference_graph_bytes(fused, sem, ref / "graph.json")
    assert got == (ref / "graph.json").read_bytes()    # JSON layer round-trip is lossless
    data = json.loads(got)
    assert data["directed"] is True and "edges" in data  # D15 + key pinned


def test_schema_version_on_all_layers(tmp_path):
    (tmp_path / "src").mkdir()
    driver.write_structural(_fused(), tmp_path)
    driver.write_semantic(_semantic(), tmp_path)
    freshness.write_manifest(tmp_path, tmp_path, ["src"], engine_stamp=engine.detect_engine())
    sv = engine.SCHEMA_VERSION
    for name in ("structural.json", "semantic.json", ".cg_manifest.json"):
        assert json.loads((tmp_path / name).read_text())["schema_version"] == sv


def test_materialize_requires_structural_tolerates_missing_semantic(tmp_path):
    with pytest.raises(SystemExit):                 # no structural.json yet
        driver.materialize(tmp_path)
    driver.write_structural(_fused(), tmp_path)     # structural only, no semantic
    out = driver.materialize(tmp_path)
    assert out["semantic_edges"] == 0
    assert (tmp_path / "graph.json").exists()


def test_write_artifact_shim_emits_graph_and_report(tmp_path):
    # the compat shim still produces graph.json + GRAPH_REPORT.md for legacy consumers/tests
    written = driver.write_artifact(_fused(), tmp_path, semantic=_semantic())
    assert (tmp_path / "graph.json").exists() and (tmp_path / "GRAPH_REPORT.md").exists()
    assert (tmp_path / "structural.json").exists() and (tmp_path / "semantic.json").exists()
    assert written["semantic_edges"] == 1
    assert set(written) >= {"graph_json", "report", "nodes", "edges", "semantic_edges"}
