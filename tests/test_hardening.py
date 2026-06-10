"""Tests for the no-egress hardening: orphan prune, singleton fold, freshness drift."""
from cg_graphify_bridge import adapter, freshness
from cg_graphify_bridge.adapter import AdaptResult


def _node(nid, kind="function", file="src/a.ts"):
    return {"id": nid, "label": nid, "file_type": "code", "source_file": file,
            "source_location": "L1", "metadata": {"cg_kind": kind}}


def test_prune_orphans_drops_unconnected_code_keeps_files():
    nodes = [_node("f", kind="file"), _node("used"), _node("orphan")]
    edges = [{"source": "f", "target": "used", "relation": "contains", "context": "contains",
              "confidence": "EXTRACTED", "weight": 1.0}]
    res = adapter.prune_orphans(AdaptResult(nodes, edges, {}, {}))
    ids = {n["id"] for n in res.nodes}
    assert "orphan" not in ids        # zero-edge code node dropped
    assert {"f", "used"} <= ids       # file + connected node kept
    assert res.stats["pruned_orphans"] == 1


def test_prune_orphans_noop_returns_same_object():
    nodes = [_node("f", kind="file")]
    res = AdaptResult(nodes, [], {}, {})
    assert adapter.prune_orphans(res) is res  # nothing to drop -> identity


def test_fold_singleton_into_file_sibling_community():
    nodes = [_node("a"), _node("b"), _node("solo")]  # all in src/a.ts
    res = AdaptResult(nodes, [], {}, {})
    communities = {"big": ["a", "b"], "s": ["solo"]}
    folded = adapter.fold_singleton_communities(communities, res)
    assert "s" not in folded                      # singleton community collapsed
    assert set(folded["big"]) == {"a", "b", "solo"}  # reassigned, not deleted


def test_fold_colocated_leftover_singletons_grouped():
    # 3 funcs in one module, each its own singleton, none with a non-singleton sibling
    nodes = [_node("x", file="src/m.ts"), _node("y", file="src/m.ts"), _node("z", file="src/m.ts")]
    res = AdaptResult(nodes, [], {}, {})
    communities = {"cx": ["x"], "cy": ["y"], "cz": ["z"]}
    folded = adapter.fold_singleton_communities(communities, res)
    assert len(folded) == 1                                   # collapsed to one module community
    assert set(next(iter(folded.values()))) == {"x", "y", "z"}


def test_fold_no_siblings_is_noop():
    nodes = [_node("a"), _node("b", file="src/a.ts"), _node("solo", file="src/z.ts")]
    res = AdaptResult(nodes, [], {}, {})
    communities = {"big": ["a", "b"], "s": ["solo"]}  # solo alone in its file
    assert adapter.fold_singleton_communities(communities, res) == communities


def test_freshness_detects_drift(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ts").write_text("export const x = 1;\n")
    out = tmp_path / "graphify-out"
    out.mkdir()
    freshness.write_manifest(out, tmp_path, ["src"])
    assert not (out / freshness.STALE).exists()
    assert freshness.check_stale(out, tmp_path, ["src"])["state"] == "fresh"

    (src / "a.ts").write_text("export const x = 2;\n")  # content drift
    st = freshness.check_stale(out, tmp_path, ["src"])
    assert st["state"] == "stale" and (out / freshness.STALE).exists()

    freshness.write_manifest(out, tmp_path, ["src"])     # rebuild consumes the marker
    assert not (out / freshness.STALE).exists()
