"""Unit tests for the TS type-aware substrate ingest (adapt_ts).

The Node extractor (extract.cjs) is integration-exercised on real repos; here we
monkeypatch run_extractor with a canned payload so the Python mapping layer —
composite-id assignment, edge-relation mapping, residual merges, unmapped handling,
and determinism — is tested deterministically with no node dependency.
"""
from cg_graphify_bridge import ts_substrate
from cg_graphify_bridge.adapter import composite_id

# two files; B.run() calls A.helper() (cross-file), B extends Base.
# ids 0/3 are files, 1=helper(fn), 2=Base(class), 4=B(class), 5=run(method).
_FIXTURE = {
    "nodes": [
        {"id": 0, "kind": "file", "name": "a.ts", "qualified_name": "src/a.ts",
         "file_path": "src/a.ts", "signature": "", "line": 1},
        {"id": 1, "kind": "function", "name": "helper", "qualified_name": "src/a.ts::helper",
         "file_path": "src/a.ts", "signature": "(x)", "line": 3},
        {"id": 2, "kind": "class", "name": "Base", "qualified_name": "src/a.ts::Base",
         "file_path": "src/a.ts", "signature": "", "line": 8},
        {"id": 3, "kind": "file", "name": "b.ts", "qualified_name": "src/b.ts",
         "file_path": "src/b.ts", "signature": "", "line": 1},
        {"id": 4, "kind": "class", "name": "B", "qualified_name": "src/b.ts::B",
         "file_path": "src/b.ts", "signature": "", "line": 2},
        {"id": 5, "kind": "method", "name": "run", "qualified_name": "src/b.ts::B.run",
         "file_path": "src/b.ts", "signature": "()", "line": 4},
    ],
    "edges": [
        {"source": 0, "target": 1, "kind": "contains"},
        {"source": 0, "target": 2, "kind": "contains"},
        {"source": 3, "target": 4, "kind": "contains"},
        {"source": 4, "target": 5, "kind": "contains"},
        {"source": 5, "target": 1, "kind": "calls"},        # cross-file call
        {"source": 4, "target": 2, "kind": "extends"},       # -> inherits
        {"source": 5, "target": 999, "kind": "references"},  # dangling target -> unmapped
    ],
    "stats": {"files": 2, "nodes": 6, "edges": 7, "crossFileEdges": 2},
}


def _adapt(monkeypatch, payload):
    monkeypatch.setattr(ts_substrate, "run_extractor", lambda repo, scopes, extractor=None: payload)
    return ts_substrate.adapt_ts("/repo", ["src"])


def test_node_count_and_composite_ids(monkeypatch):
    res = _adapt(monkeypatch, _FIXTURE)
    assert len(res.nodes) == 6  # no merges in the fixture
    helper = next(n for n in res.nodes if n["label"] == "helper")
    assert helper["id"] == composite_id("src/a.ts", "src/a.ts::helper", "function", "(x)")
    assert helper["metadata"]["origin"] == "ts-substrate"
    assert helper["metadata"]["language"] == "typescript"


def test_edge_relation_mapping_and_unmapped(monkeypatch):
    res = _adapt(monkeypatch, _FIXTURE)
    rels = sorted(e["relation"] for e in res.edges)
    # 4 contains + 1 calls + 1 inherits(extends); the dangling reference is dropped
    assert rels == ["calls", "contains", "contains", "contains", "contains", "inherits"]
    assert res.stats["unmapped_edges"] == 1
    assert res.stats["substrate"] == "ts-typechecker"
    assert res.stats["kind_dist"]["class"] == 2


def test_crossfile_call_resolves_to_composite_endpoints(monkeypatch):
    res = _adapt(monkeypatch, _FIXTURE)
    run_id = composite_id("src/b.ts", "src/b.ts::B.run", "method", "()")
    helper_id = composite_id("src/a.ts", "src/a.ts::helper", "function", "(x)")
    calls = [e for e in res.edges if e["relation"] == "calls"]
    assert calls and calls[0]["source"] == run_id and calls[0]["target"] == helper_id


def test_residual_collision_merges(monkeypatch):
    # two raw nodes with identical (file,qn,kind,sig) -> one composite node, merge recorded
    dup = {"nodes": _FIXTURE["nodes"] + [dict(_FIXTURE["nodes"][1], id=42)],
           "edges": [], "stats": {}}
    res = _adapt(monkeypatch, dup)
    assert res.stats["merges"] == 1
    assert len(res.nodes) == 6
    helper = next(n for n in res.nodes if n["label"] == "helper")
    assert 42 in helper["metadata"]["cg_merged_ids"]


def test_deterministic_ids(monkeypatch):
    a = _adapt(monkeypatch, _FIXTURE)
    b = _adapt(monkeypatch, _FIXTURE)
    assert [n["id"] for n in a.nodes] == [n["id"] for n in b.nodes]
