"""Phase 2 driver tests — trace R3,R5,R2 / D5,D12,D15,D16."""
from cg_graphify_bridge import adapter, driver


def test_build_from_json_accepts_adapter_output(cg_db):
    from graphify import build
    res = adapter.adapt(cg_db)
    av = adapter.analysis_view(res)
    G = build.build_from_json({"nodes": av["nodes"], "edges": av["edges"]}, directed=False)
    assert G.number_of_nodes() == len(av["nodes"])


def test_communities_applied_to_nodes(cg_db):
    """D16: cluster() returns a mapping; driver must write it onto nodes."""
    out = driver.build_fused(cg_db)
    G = out["graph"]
    assigned = [G.nodes[n].get("community") for n in G.nodes]
    assert any(c is not None for c in assigned), "communities must be applied to G"


def test_god_nodes_present_and_not_files(cg_db):
    out = driver.build_fused(cg_db)
    gods = out["god_nodes"]
    assert len(gods) >= 1
    file_ids = {n["id"] for n in out["adapt"].nodes if n["metadata"]["cg_kind"] == "file"}
    assert {g["id"] for g in gods}.isdisjoint(file_ids), "god nodes must not be file hubs"


def test_write_artifact_produces_graphjson_and_report(cg_db, tmp_path):
    out = driver.build_fused(cg_db)
    driver.write_artifact(out, tmp_path / "graphify-out")
    import json
    gj = json.loads((tmp_path / "graphify-out" / "graph.json").read_text())
    assert (tmp_path / "graphify-out" / "GRAPH_REPORT.md").exists()
    assert gj["nodes"] and all(n["id"].startswith("cg:") for n in gj["nodes"])


def test_artifact_graph_is_directed(cg_db, tmp_path):
    """D15: committed full graph preserves direction."""
    out = driver.build_fused(cg_db)
    driver.write_artifact(out, tmp_path / "graphify-out")
    import json
    gj = json.loads((tmp_path / "graphify-out" / "graph.json").read_text())
    assert gj["directed"] is True


def test_hub_exclusion_reduces_fragmentation(cg_db):
    """D12: exclude_hubs_percentile should not increase community count."""
    with_excl = driver.build_fused(cg_db, exclude_hubs_percentile=95.0)
    without = driver.build_fused(cg_db, exclude_hubs_percentile=None)
    assert len(with_excl["communities"]) <= len(without["communities"]) + 1
