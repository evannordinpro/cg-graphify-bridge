"""Phase 3 P3c (R8/R10, KD7) — consumer/materialize resilience.

Success criteria:
- materialize tolerates a missing semantic layer (structural-only is valid);
- a corrupt or wrong-schema layer is REJECTED on read (never silently consumed);
- a consumer gets identical results whether reading the graph.json cache or rematerializing
  from the committed layers (the split is invisible to consumers);
- the consumer never hard-blocks: a corrupt cache rebuilds; an unreadable structural degrades
  to a best-effort file read rather than crashing.
"""
import json

import pytest

from cg_graphify_bridge import driver
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
            "god_nodes": [{"id": "cg:aaa", "label": "A", "degree": 1}], "surprising": []}


def _semantic():
    return {"semantic_nodes": [{"id": "doc:d", "label": "d.md", "file_type": "document"}],
            "semantic_edges": [{"source": "doc:d", "target": "cg:aaa", "relation": "references"}],
            "stats": {"kept": 1}}


def test_materialize_tolerates_missing_semantic(tmp_path):
    driver.write_structural(_fused(), tmp_path)             # no semantic.json
    out = driver.materialize(tmp_path)
    assert out["semantic_edges"] == 0
    assert out["nodes"] == 2 and (tmp_path / "graph.json").exists()


def test_corrupt_layer_schema_rejected(tmp_path):
    driver.write_structural(_fused(), tmp_path)
    # (a) malformed JSON -> rejected
    (tmp_path / "structural.json").write_text("{ not valid json ]")
    with pytest.raises(SystemExit):
        driver.read_layer(tmp_path, "structural")
    with pytest.raises(SystemExit):
        driver.materialize(tmp_path)
    # (b) wrong schema_version -> rejected
    driver.write_structural(_fused(), tmp_path)
    data = json.loads((tmp_path / "structural.json").read_text())
    data["schema_version"] = driver.SCHEMA_VERSION + 99
    (tmp_path / "structural.json").write_text(json.dumps(data))
    with pytest.raises(SystemExit):
        driver.read_layer(tmp_path, "structural")


def test_consumer_query_parity_pre_post_split(tmp_path):
    driver.write_structural(_fused(), tmp_path)
    driver.write_semantic(_semantic(), tmp_path)
    driver.materialize(tmp_path)
    via_cache = driver.load_fused(tmp_path)                 # reads the graph.json cache
    (tmp_path / "graph.json").unlink()                      # drop cache -> rematerialize from layers
    via_layers = driver.load_fused(tmp_path)

    def _key(g):
        return (sorted(n["id"] for n in g["nodes"]),
                sorted((e["source"], e["target"]) for e in g["edges"]))

    assert _key(via_cache) == _key(via_layers)              # consumer sees the same graph both ways
    assert not via_cache.get("degraded") and not via_layers.get("degraded")


def test_consumer_rebuilds_corrupt_cache(tmp_path):
    driver.write_structural(_fused(), tmp_path)
    driver.write_semantic(_semantic(), tmp_path)
    (tmp_path / "graph.json").write_text("CORRUPT")          # poisoned cache, layers are fine
    g = driver.load_fused(tmp_path)
    assert {n["id"] for n in g["nodes"]} >= {"cg:aaa", "cg:bbb", "doc:d"}  # rebuilt from layers
    assert not g.get("degraded")


def test_consumer_never_blocks_on_corrupt_structural(tmp_path):
    # structural unreadable AND no cache -> degrade to best-effort file read, do NOT raise
    (tmp_path / "structural.json").write_text("}{")
    (tmp_path / "semantic.json").write_text(json.dumps({
        "schema_version": driver.SCHEMA_VERSION, "layer": "semantic",
        "semantic_nodes": [{"id": "doc:d", "label": "d"}], "semantic_edges": [], "stats": {}}))
    g = driver.load_fused(tmp_path)                          # must not raise
    assert g.get("degraded") is True
    assert any(n["id"] == "doc:d" for n in g["nodes"])       # salvaged what it could
