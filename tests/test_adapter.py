"""Phase 0/1 adapter tests — trace R1,R2,R3,R9 / D1,D3,D4,D12,D17."""
from cg_graphify_bridge import adapter


def test_schema_has_expected_columns(cg_db):
    nodes, edges = adapter.read_codegraph_db(cg_db)
    assert len(nodes) > 0 and len(edges) > 0
    ncols = set(nodes[0].keys())
    assert {"id", "kind", "name", "qualified_name", "file_path", "signature", "start_line"} <= ncols
    assert {"source", "target", "kind", "provenance"} <= set(edges[0].keys())


def test_composite_disambiguates_cross_file_same_name(cg_db):
    """The crown case: two top-level process() funcs, same qn, different files."""
    res = adapter.adapt(cg_db)
    procs = [n for n in res.nodes
             if n["label"] == "process" and n["metadata"]["cg_kind"] == "function"]
    assert len(procs) == 2, f"expected 2 process() funcs, got {len(procs)}"
    assert len({p["id"] for p in procs}) == 2, "composite ids must be distinct"
    assert len({p["metadata"]["qualified_name"] for p in procs}) == 1, \
        "qualified_name must be identical -> proves qn-alone would collide"


def test_qualified_name_alone_collides(cg_db):
    res = adapter.adapt(cg_db)
    qns = [n["metadata"]["qualified_name"] for n in res.nodes]
    composites = [n["id"] for n in res.nodes]
    assert len(set(qns)) < len(set(composites)), \
        "qualified_name must be less unique than the composite key"


def test_all_node_ids_are_composite(cg_db):
    res = adapter.adapt(cg_db)
    assert all(n["id"].startswith("cg:") for n in res.nodes)


def test_node_set_unique_after_merge(cg_db):
    res = adapter.adapt(cg_db)
    ids = [n["id"] for n in res.nodes]
    assert len(ids) == len(set(ids)), "100% unique composite ids after merge-on-collision"


def test_no_edge_references_unmapped_id(cg_db):
    res = adapter.adapt(cg_db)
    node_ids = {n["id"] for n in res.nodes}
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in res.edges)


def test_edge_kind_and_provenance_mapping(cg_db):
    res = adapter.adapt(cg_db)
    rels = {e["relation"] for e in res.edges}
    assert rels <= {"calls", "imports", "inherits", "contains", "references"}
    assert all(e["confidence"] in {"EXTRACTED", "INFERRED", "AMBIGUOUS"} for e in res.edges)


def test_all_code_nodes_tagged_origin(cg_db):
    res = adapter.adapt(cg_db)
    assert res.nodes and all(n["metadata"]["origin"] == "codegraph" for n in res.nodes)


def test_directed_call_edges_preserved(cg_db):
    """D15: adapter retains directed (source->target) call orientation."""
    res = adapter.adapt(cg_db)
    calls = [e for e in res.edges if e["relation"] == "calls"]
    assert calls, "expected at least one call edge"
    assert all(e["source"] != e["target"] for e in calls)


def test_analysis_view_excludes_file_nodes_and_contains(cg_db):
    res = adapter.adapt(cg_db)
    av = adapter.analysis_view(res)
    assert all(n["metadata"]["cg_kind"] != "file" for n in av["nodes"])
    assert all(e["relation"] != "contains" for e in av["edges"])


def test_analysis_view_excludes_test_paths(cg_db):
    res = adapter.adapt(cg_db)
    av = adapter.analysis_view(res)
    assert all("tests/" not in (n["source_file"] or "") for n in av["nodes"])


def test_linkable_subset_excludes_noise_kinds(cg_db):
    res = adapter.adapt(cg_db)
    sub = adapter.linkable_subset(res)
    kinds = {s["cg_kind"] for s in sub}
    assert {"import", "variable", "parameter", "file"}.isdisjoint(kinds)
    assert "function" in kinds


def test_linkable_subset_scoped_per_community(cg_db):
    res = adapter.adapt(cg_db)
    fake_comms = {0: [res.nodes[0]["id"]], 1: [n["id"] for n in res.nodes[1:]]}
    grouped = adapter.linkable_subset(res, communities=fake_comms)
    assert isinstance(grouped, dict)
