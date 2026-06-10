"""Phase 1 — cross-machine determinism of the committed artifacts (R5/R6, KD1–KD4, pins).

These assert the success criterion "same source -> byte-identical structural.json across
machines/reruns": write_artifact ordering + serialization, SQL row ordering, the pinned
deps, and the extractor walk-sort. write_artifact is exercised with a hand-built `fused`
dict so no clustering/graphify call is needed (the determinism of the *writer* is the unit).
"""
import json
import sqlite3
from pathlib import Path

import pytest

from cg_graphify_bridge import adapter, driver
from cg_graphify_bridge.adapter import AdaptResult

_ROOT = Path(__file__).resolve().parents[1]


def _fused():
    # nodes + edges intentionally OUT OF ORDER to prove the writer sorts them
    nodes = [
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
        # god_nodes out of order + degree-tied -> KD4 tiebreak by id
        "god_nodes": [{"id": "cg:bbb", "label": "B", "degree": 1},
                      {"id": "cg:aaa", "label": "A", "degree": 1}],
        "surprising": [{"source": "cg:bbb", "target": "cg:aaa"}],
    }


def test_write_artifact_rerun_byte_identical(tmp_path):
    d1, d2 = tmp_path / "a", tmp_path / "b"
    driver.write_artifact(_fused(), d1)
    driver.write_artifact(_fused(), d2)
    assert (d1 / "graph.json").read_bytes() == (d2 / "graph.json").read_bytes()
    assert (d1 / "GRAPH_REPORT.md").read_bytes() == (d2 / "GRAPH_REPORT.md").read_bytes()


def test_write_artifact_sorted_nodes_edges(tmp_path):
    driver.write_artifact(_fused(), tmp_path)
    data = json.loads((tmp_path / "graph.json").read_text())
    assert [n["id"] for n in data["nodes"]] == ["cg:aaa", "cg:bbb"]  # sorted by id
    pairs = [(e["source"], e["target"], e["relation"]) for e in data["edges"]]
    assert pairs == sorted(pairs)  # edges sorted by (source,target,relation)


def test_graph_json_stable_key_and_trailing_newline(tmp_path):
    driver.write_artifact(_fused(), tmp_path)
    txt = (tmp_path / "graph.json").read_text()
    assert txt.endswith("\n")
    data = json.loads(txt)
    assert "edges" in data and "links" not in data  # edges="edges" key pinned


def test_report_god_nodes_tiebreak_by_id(tmp_path):
    driver.write_artifact(_fused(), tmp_path)
    report = (tmp_path / "GRAPH_REPORT.md").read_text()
    # degree-tied A and B -> A (lower id) listed before B
    assert report.index("`cg:aaa`") < report.index("`cg:bbb`")
    assert report.endswith("\n")


def test_read_codegraph_db_ordered(tmp_path):
    db = tmp_path / "cg.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE nodes (id TEXT, kind TEXT, name TEXT, qualified_name TEXT, "
                "file_path TEXT, signature TEXT, start_line INT, end_line INT, language TEXT)")
    con.execute("CREATE TABLE edges (source TEXT, target TEXT, kind TEXT, provenance TEXT)")
    # inserted z before a; deterministic read must return a first
    con.execute("INSERT INTO nodes VALUES ('n2','function','foo','z.ts::foo','z.ts','()',1,2,'ts')")
    con.execute("INSERT INTO nodes VALUES ('n1','function','bar','a.ts::bar','a.ts','()',1,2,'ts')")
    con.execute("INSERT INTO edges VALUES ('z','a','calls','tree-sitter')")
    con.execute("INSERT INTO edges VALUES ('a','z','references','tree-sitter')")
    con.commit()
    con.close()
    nrows, erows = adapter.read_codegraph_db(db)
    assert [r["file_path"] for r in nrows] == ["a.ts", "z.ts"]
    assert [(r["source"], r["target"]) for r in erows] == [("a", "z"), ("z", "a")]


def test_deps_pinned_for_determinism():
    txt = (_ROOT / "pyproject.toml").read_text()
    assert "graphifyy==0.8.36" in txt
    assert "networkx==3.6.1" in txt


def test_extractor_walk_is_sorted():
    # extractor now ships inside the package (KD5) — locate it where it lives post-install
    from importlib.resources import as_file, files
    with as_file(files("cg_graphify_bridge.ts_substrate_js").joinpath("extract.cjs")) as p:
        assert "ents.sort(" in Path(p).read_text()  # KD3 readdir sort present
