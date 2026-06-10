"""Phase 4 P4a (R4, KD9) — semantic freshness computed on demand from the manifest baseline.

Success criteria:
- editing a DOC marks semantic stale;
- editing a LINKED source file (target of a semantic edge) marks semantic stale;
- editing a NON-linked code file marks STRUCTURAL stale but leaves SEMANTIC fresh (the inverse
  of graphify's code_only test — a code-only edit needs no semantic re-merge);
- the semantic baseline survives a structural rebuild (build must not reset it).
"""
from cg_graphify_bridge import driver, engine, freshness
from cg_graphify_bridge.adapter import AdaptResult


def _setup(tmp):
    repo = tmp
    (repo / "src").mkdir()
    (repo / "docs").mkdir()
    (repo / "src" / "a.ts").write_text("export function A(){return 1}\n")   # linked by the doc edge
    (repo / "src" / "b.ts").write_text("export function B(){return 2}\n")   # NOT linked
    (repo / "docs" / "d.md").write_text("The A function does X.\n")
    out = repo / "graphify-out"
    nodes = [
        {"id": "cg:a", "label": "A", "file_type": "code", "source_file": "src/a.ts",
         "source_location": "L1", "metadata": {"cg_kind": "function"}},
        {"id": "cg:b", "label": "B", "file_type": "code", "source_file": "src/b.ts",
         "source_location": "L1", "metadata": {"cg_kind": "function"}},
    ]
    driver.write_structural({"adapt": AdaptResult(nodes, [], {}, {}),
                             "communities": {"c0": ["cg:a", "cg:b"]}, "god_nodes": [],
                             "surprising": []}, out)
    driver.write_semantic({"semantic_nodes": [{"id": "doc:d", "label": "d.md", "file_type": "document"}],
                           "semantic_edges": [{"source": "doc:d", "target": "cg:a",
                                               "relation": "references"}], "stats": {}}, out)
    freshness.write_manifest(out, repo, ["src"], engine_stamp=engine.detect_engine())
    freshness.write_semantic_freshness(out, repo)
    return repo, out


def test_initial_state_is_fresh(tmp_path):
    repo, out = _setup(tmp_path)
    st = freshness.compute_status(out, repo)
    assert st["structural"]["state"] == "fresh"
    assert st["semantic"]["state"] == "fresh"
    assert st["semantic"]["linked_count"] == 1 and st["semantic"]["docs_count"] == 1


def test_semantic_stale_on_doc_change(tmp_path):
    repo, out = _setup(tmp_path)
    (repo / "docs" / "d.md").write_text("The A function now does Y and Z.\n")  # doc edit
    st = freshness.compute_status(out, repo)
    assert st["semantic"]["state"] == "stale"


def test_semantic_stale_on_linked_file_change(tmp_path):
    repo, out = _setup(tmp_path)
    (repo / "src" / "a.ts").write_text("export function A(){return 42}\n")  # LINKED file edit
    st = freshness.compute_status(out, repo)
    assert st["semantic"]["state"] == "stale"
    assert st["structural"]["state"] == "stale"   # code changed -> structural also stale


def test_code_only_edit_not_semantically_stale(tmp_path):
    repo, out = _setup(tmp_path)
    (repo / "src" / "b.ts").write_text("export function B(){return 99}\n")  # NON-linked code edit
    st = freshness.compute_status(out, repo)
    assert st["structural"]["state"] == "stale"   # build is due
    assert st["semantic"]["state"] == "fresh"     # but the overlay is NOT — the key inverse


def test_semantic_baseline_preserved_across_structural_build(tmp_path):
    repo, out = _setup(tmp_path)
    # a structural rebuild (e.g. CI) rewrites the manifest — it must keep the semantic baseline
    freshness.write_manifest(out, repo, ["src"], engine_stamp=engine.detect_engine())
    m = freshness.read_manifest(out)
    assert "semantic" in m and m["semantic"]["linked_count"] == 1
    assert freshness.compute_status(out, repo)["semantic"]["state"] == "fresh"


def test_compute_status_unbuilt_when_no_manifest(tmp_path):
    st = freshness.compute_status(tmp_path / "graphify-out", tmp_path)
    assert st["state"] == "unbuilt" and st["semantic"]["state"] == "unbuilt"
