"""Phase 2 (2a + 2a-pre) — structural analytics over the committed graph, and the substrate
stamping of is_abstract/is_exported/visibility (FR0) that Martin's Abstractness needs.

Analytics tests use synthetic structural dicts (no DB/network). The FR0 adapter test uses a tiny
synthetic codegraph DB (the columns the adapter SELECTs) — hermetic, no codegraph CLI needed.
"""
import sqlite3

from cg_graphify_bridge import adapter, analytics


# ---------- builders ----------

def _node(nid, kind="function", file="src/a.py", abstract=None, exported=None, label=None):
    md = {"cg_kind": kind, "qualified_name": label or nid, "language": "python",
          "start_line": 1, "end_line": 2}
    if abstract is not None:
        md["is_abstract"] = abstract
    if exported is not None:
        md["is_exported"] = exported
    return {"id": nid, "label": label or nid, "file_type": "code", "source_file": file,
            "source_location": "L1", "metadata": md}


def _edge(s, t, rel="calls", weight=1.0):
    return {"source": s, "target": t, "relation": rel, "weight": weight}


def _struct(nodes, edges, communities=None):
    return {"schema_version": 1, "layer": "structural", "nodes": nodes, "edges": edges,
            "communities": communities or {}, "god_nodes": [], "surprising": [], "stats": {}}


# ---------- FR0: adapter stamps abstractness/export (synthetic codegraph DB) ----------

def _cg_db(tmp, node_rows, edge_rows=()):
    db = tmp / "codegraph.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE nodes (id,kind,name,qualified_name,file_path,signature,start_line,"
              "end_line,language,is_abstract,is_exported,visibility)")
    c.execute("CREATE TABLE edges (source,target,kind,provenance)")
    c.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", node_rows)
    c.executemany("INSERT INTO edges VALUES (?,?,?,?)", edge_rows)
    c.commit()
    c.close()
    return db


def test_adapter_stamps_is_abstract(tmp_path):
    db = _cg_db(tmp_path, [("1", "class", "Base", "m.Base", "m.py", "", 1, 9, "python", 1, 1, "public")])
    n = adapter.adapt(db).nodes[0]
    assert n["metadata"]["is_abstract"] is True


def test_adapter_stamps_is_exported_visibility(tmp_path):
    db = _cg_db(tmp_path, [("1", "function", "f", "m.f", "m.py", "()", 1, 2, "python", 0, 0, "private")])
    md = adapter.adapt(db).nodes[0]["metadata"]
    assert md["is_exported"] is False and md["visibility"] == "private"


def test_adapter_abstract_coerced_to_bool(tmp_path):
    db = _cg_db(tmp_path, [("1", "class", "C", "m.C", "m.py", "", 1, 2, "python", 1, 1, "public")])
    md = adapter.adapt(db).nodes[0]["metadata"]
    assert md["is_abstract"] is True and md["is_exported"] is True   # 1 -> True, not 1


def test_adapter_determinism_unchanged(tmp_path):
    rows = [("1", "class", "C", "m.C", "m.py", "", 1, 2, "python", 1, 0, "public"),
            ("2", "function", "f", "m.f", "m.py", "()", 3, 4, "python", 0, 1, "public")]
    db = _cg_db(tmp_path, rows)
    r1 = [n["id"] for n in adapter.adapt(db).nodes]
    r2 = [n["id"] for n in adapter.adapt(db).nodes]
    assert r1 == r2 and len(r1) == 2                                # stable order, both nodes present


# ---------- 2a: graph build + centrality ----------

def test_builds_digraph_from_structural():
    s = _struct([_node("A"), _node("B")],
                [_edge("A", "B"), _edge("A", "A"), _edge("A", "B", rel="contains")])
    dg = analytics.build_digraph(s)
    assert dg.has_edge("A", "B") and not dg.has_edge("A", "A")       # self-loop dropped
    assert dg.number_of_edges() == 1                                 # `contains` excluded


def test_betweenness_deterministic():
    s = _struct([_node("A"), _node("B"), _node("C")], [_edge("A", "B"), _edge("B", "C")])
    c1, c2 = analytics.centrality(s), analytics.centrality(s)
    assert c1 == c2                                                  # deterministic
    assert c1["B"]["betweenness"] >= c1["A"]["betweenness"]          # the broker scores highest


def test_pagerank_ranks_depended_upon():
    s = _struct([_node(x) for x in ("A", "B", "C", "D")],
                [_edge("A", "D"), _edge("B", "D"), _edge("C", "D")])
    c = analytics.centrality(s)
    assert c["D"]["pagerank"] > c["A"]["pagerank"]                   # the foundation wins


# ---------- 2a: cycles ----------

def test_scc_finds_planted_cycle():
    s = _struct([_node("A"), _node("B"), _node("C")],
                [_edge("A", "B"), _edge("B", "C"), _edge("C", "A")])
    assert ["A", "B", "C"] in analytics.cycles(s)["symbol_cycles"]


def test_condensation_cycle_suggests_cut():
    s = _struct([_node("A", file="f1.py"), _node("B", file="f2.py")],
                [_edge("A", "B", weight=5.0), _edge("B", "A", rel="imports", weight=1.0)])
    mc = analytics.cycles(s)["module_cycles"]
    assert mc and mc[0]["suggested_cut"]["weight"] == 1.0            # cheapest edge to break


# ---------- 2a: conductance / coupling ----------

def test_conductance_flags_leaky_community():
    nodes = [_node(x) for x in ("A", "B", "E", "C", "D")]
    edges = [_edge("A", "B"), _edge("B", "E"), _edge("A", "E"),      # c0 internal triangle
             _edge("C", "A"), _edge("D", "B")]                       # c1 leaks into c0
    cond = analytics.conductance(_struct(nodes, edges, {"c0": ["A", "B", "E"], "c1": ["C", "D"]}))
    assert cond and all(0 <= r["conductance"] <= 1 for r in cond)
    assert cond == sorted(cond, key=lambda r: (-r["conductance"], r["community"]))  # worst-first


def test_instability_inversion_flagged():
    nodes = [_node(x) for x in ("S", "U", "X", "Y")]
    edges = [_edge("X", "S"), _edge("Y", "S"), _edge("S", "U"), _edge("U", "X")]
    comms = {"c0": ["S"], "c1": ["U"], "c2": ["X"], "c3": ["Y"]}
    res = analytics.coupling_instability(_struct(nodes, edges, comms))
    assert any(d["from"] == "c0" and d["to"] == "c1" for d in res["inversions"])  # stable→unstable


# ---------- 2a: abstractness / distance / zones ----------

def test_abstractness_over_types_only():
    nodes = [_node("AC", kind="class", abstract=True), _node("CC", kind="class", abstract=False),
             _node("fn", kind="function", abstract=False)]
    row = analytics.abstractness_distance(_struct(nodes, [], {"c0": ["AC", "CC", "fn"]}))["communities"][0]
    assert row["types"] == 2 and row["abstractness"] == 0.5         # function excluded from A


def test_distance_from_main_sequence_and_zone_of_pain():
    nodes = [_node("P", kind="class", abstract=False), _node("X")]
    res = analytics.abstractness_distance(_struct(nodes, [_edge("X", "P")], {"c0": ["P"], "c1": ["X"]}))
    row = next(r for r in res["communities"] if r["community"] == "c0")
    assert row["zone"] == "pain" and row["distance"] == 1.0         # concrete + stable, far from main seq


def test_zone_of_uselessness_flagged():
    nodes = [_node("I1", kind="interface"), _node("I2", kind="interface"), _node("T", kind="class")]
    res = analytics.abstractness_distance(
        _struct(nodes, [_edge("I1", "T"), _edge("I2", "T")], {"c0": ["I1", "I2"], "c1": ["T"]}))
    row = next(r for r in res["communities"] if r["community"] == "c0")
    assert row["abstractness"] == 1.0 and row["zone"] == "uselessness"   # abstract but unused


def test_unknown_abstractness_caveat():
    n = {"id": "C", "label": "C", "file_type": "code", "source_file": "a.py", "source_location": "L1",
         "metadata": {"cg_kind": "class", "qualified_name": "C", "language": "python"}}  # NO is_abstract
    res = analytics.abstractness_distance(_struct([n], [], {"c0": ["C"]}))
    assert res["caveat"] is not None and res["abstractness_coverage"] < 1.0


# ---------- 2a: fan-out / dead code ----------

def test_fan_out_threshold():
    nodes = [_node("H")] + [_node(f"n{i}") for i in range(10)]
    edges = [_edge("H", f"n{i}") for i in range(10)]
    fan = analytics.fan_distribution(_struct(nodes, edges))
    assert any(h["id"] == "H" for h in fan["high_fan_out"])          # the SRP-violating hub


def test_dead_code_excludes_entrypoints():
    nodes = [_node("O", label="orphan"), _node("E", label="api", exported=True),
             _node("M", label="main"), _node("T", label="test_x", file="tests/test_x.py")]
    ids = {d["id"] for d in analytics.dead_code(_struct(nodes, []))}
    assert "O" in ids and "E" not in ids and "M" not in ids and "T" not in ids


def test_analytics_empty_graph_guards():
    res = analytics.analyze(_struct([], [], {}))
    assert res["cycles"]["symbol_cycles"] == [] and res["dead_code"] == []
    assert res["abstractness"]["caveat"] is None
