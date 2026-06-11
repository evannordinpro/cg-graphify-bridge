"""Phase 2 (2b) — `health`: structural + semantic + combined metrics + the markdown report.

Pure functions tested with synthetic structural/semantic dicts; health.health() tested as an
integration over layers written to disk via driver (the real read path).
"""
import json

from cg_graphify_bridge import analytics, driver, health
from cg_graphify_bridge.adapter import AdaptResult


def _node(nid, kind="function", file="src/a.py", exported=None, label=None):
    md = {"cg_kind": kind, "qualified_name": label or nid, "language": "python", "start_line": 1}
    if exported is not None:
        md["is_exported"] = exported
    return {"id": nid, "label": label or nid, "file_type": "code", "source_file": file,
            "source_location": "L1", "metadata": md}


def _edge(s, t, rel="calls", w=1.0):
    return {"source": s, "target": t, "relation": rel, "weight": w}


def _struct(nodes, edges, communities=None, gods=None):
    return {"schema_version": 1, "layer": "structural", "nodes": nodes, "edges": edges,
            "communities": communities or {}, "god_nodes": gods or [], "surprising": [], "stats": {}}


def _sem(edges, nodes=None):
    return {"schema_version": 1, "layer": "semantic",
            "semantic_nodes": nodes or [{"id": "doc:d", "label": "d.md", "file_type": "document"}],
            "semantic_edges": edges, "stats": {}}


def _se(target, source="doc:d", rel="references"):
    return {"source": source, "target": target, "relation": rel}


def _write_layers(out, nodes, edges, communities=None, gods=None, sem_edges=None):
    driver.write_structural({"adapt": AdaptResult(nodes, edges, {}, {}),
                             "communities": communities or {}, "god_nodes": gods or [],
                             "surprising": []}, out)
    if sem_edges is not None:
        driver.write_semantic({"semantic_nodes": [{"id": "doc:d", "label": "d", "file_type": "document"}],
                               "semantic_edges": sem_edges, "stats": {}}, out)


# ---------- semantic ----------

def test_coverage_overall_and_public():
    code = [_node("A", exported=True), _node("B", exported=False), _node("C", kind="class", exported=True)]
    sh = health.semantic_health(_struct(code, []), _sem([_se("A")]))
    assert sh["coverage_overall"] == round(1 / 3, 4)
    assert sh["public_api_coverage"] == 0.5             # A,C public; A documented -> 1/2


def test_public_api_coverage_caveat_without_stamp():
    sh = health.semantic_health(_struct([_node("A")], []), _sem([_se("A")]))  # no is_exported stamp
    assert sh["public_api_coverage"] is None and sh["public_api_caveat"]


def test_health_lists_dangling_link():
    sh = health.semantic_health(_struct([_node("A")], []), _sem([_se("cg:missing")]))
    assert sh["dangling_links"] and sh["dangling_links"][0]["target"] == "cg:missing"


def test_health_lists_orphan_doc():
    sem = _sem([_se("A")], nodes=[{"id": "doc:d", "label": "d", "file_type": "document"},
                                  {"id": "doc:orphan", "label": "o", "file_type": "document"}])
    sh = health.semantic_health(_struct([_node("A")], []), sem)
    assert "doc:orphan" in sh["orphan_docs"]


def test_health_runs_without_semantic_layer():
    s = _struct([_node("A"), _node("B")], [_edge("A", "B")])
    assert health.semantic_health(s, None)["available"] is False
    assert health.combined_health(s, None, analytics.centrality(s))["available"] is False


# ---------- combined (the differentiator) ----------

def test_god_node_coverage_rate():
    s = _struct([_node("A"), _node("B")], [_edge("A", "B")],
                gods=[{"id": "A", "label": "A", "degree": 1}, {"id": "B", "label": "B", "degree": 1}])
    comb = health.combined_health(s, _sem([_se("A")]), analytics.centrality(s))
    assert comb["god_node_coverage"] == 0.5
    assert any(g["id"] == "B" for g in comb["undocumented_god_nodes"])


def test_centrality_weighted_coverage():
    s = _struct([_node(x) for x in ("A", "B", "C", "D")],
                [_edge("A", "D"), _edge("B", "D"), _edge("C", "D")])
    cent = analytics.centrality(s)
    doc_d = health.combined_health(s, _sem([_se("D")]), cent)["centrality_weighted_coverage"]
    doc_a = health.combined_health(s, _sem([_se("A")]), cent)["centrality_weighted_coverage"]
    assert doc_d > doc_a                               # documenting the hub covers more weight


def test_dark_subsystems_ranked():
    s = _struct([_node(x) for x in ("A", "B", "C", "D")], [_edge("A", "B")],
                {"c0": ["A", "B"], "c1": ["C", "D"]})
    dk = health.combined_health(s, _sem([_se("A")]), analytics.centrality(s))["dark_subsystems"]
    assert dk == sorted(dk, key=lambda d: (-d["darkness"], d["community"]))


def test_undocumented_risk_queue_ranks_central_undocumented():
    s = _struct([_node(x) for x in ("A", "B", "C", "D")],
                [_edge("A", "D"), _edge("B", "D"), _edge("C", "D")])
    comb = health.combined_health(s, _sem([_se("A")]), analytics.centrality(s))  # A documented, D not
    assert comb["risk_queue"][0]["id"] == "D"          # central + undocumented -> top


# ---------- knowledge debt (roll-up shows components) ----------

def test_knowledge_debt_components():
    kd = health.knowledge_debt({"available": True, "dangling_links": [1, 2], "orphan_docs": [1]},
                               {"centrality_weighted_coverage": 0.4})
    assert set(kd) >= {"missing_weighted_coverage", "dangling_links", "orphan_docs", "index"}
    assert kd["missing_weighted_coverage"] == 0.6      # never an opaque single number


# ---------- integration: health() + report over committed layers ----------

def test_health_structural_lists_cycles_with_cut(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("A", file="f1.py"), _node("B", file="f2.py")],
                  [_edge("A", "B", w=5.0), _edge("B", "A", rel="imports", w=1.0)])
    mc = health.health(out)["structural"]["cycles"]["module_cycles"]
    assert mc and mc[0]["suggested_cut"]["weight"] == 1.0


def test_health_flags_god_object(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node(x) for x in ("A", "B", "C")], [_edge("A", "B"), _edge("B", "C")])
    assert health.health(out)["structural"]["god_objects"]      # ranked hubs present


def test_health_lists_dead_code(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("used"), _node("orphan", label="orphan")], [_edge("used", "orphan")])
    dc = health.health(out)["structural"]["dead_code"]
    assert dc["count"] >= 1 and "review queue" in dc["note"]


def test_health_json_shape(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("A", exported=True), _node("B")], [_edge("A", "B")],
                  communities={"c0": ["A", "B"]}, gods=[{"id": "A", "label": "A", "degree": 1}],
                  sem_edges=[_se("A")])
    r = health.health(out)
    assert set(r) >= {"structural", "semantic", "combined", "knowledge_debt"}
    assert r["combined"]["available"] is True and r["semantic"]["available"] is True


def test_health_report_renders_all_sections(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("A", exported=True), _node("B")], [_edge("A", "B")],
                  communities={"c0": ["A", "B"]}, gods=[{"id": "A", "label": "A", "degree": 1}],
                  sem_edges=[_se("A")])
    rep = health.render_report(health.health(out))
    for h in ("# Codebase Health Report", "## Structural", "## Semantic", "## Combined"):
        assert h in rep


# ---------- P2-OBS1: production source-scoping (tests excluded by default) ----------

def test_source_scope_excludes_test_nodes():
    nodes = [_node("S", file="src/a.py"), _node("T", file="tests/test_a.py"),
             _node("TF", label="test_x", file="src/x.py")]               # test_ label even under src/
    s = _struct(nodes, [_edge("T", "S")], {"c0": ["S", "T"], "c1": ["TF"]},
                gods=[{"id": "T", "label": "T", "degree": 1}, {"id": "S", "label": "S", "degree": 1}])
    scoped = health.source_scope(s)
    ids = {n["id"] for n in scoped["nodes"]}
    assert ids == {"S"}                                                  # tests/ path + test_ label dropped
    assert scoped["edges"] == []                                         # the T->S edge went with T
    assert "c1" not in scoped["communities"]                            # emptied community removed
    assert [g["id"] for g in scoped["god_nodes"]] == ["S"]


def test_health_excludes_tests_by_default(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("S", file="src/a.py"), _node("T", label="test_s", file="tests/test_a.py")],
                  [_edge("T", "S")], communities={"c0": ["S", "T"]}, sem_edges=[_se("S")])
    r = health.health(out)
    assert r["scope"].startswith("source-only")
    assert r["semantic"]["code_count"] == 1                              # only S counted (T excluded)
    assert all(q["id"] != "T" for q in r["combined"]["risk_queue"])


def test_health_include_tests_flag(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("S", file="src/a.py"), _node("T", label="test_s", file="tests/test_a.py")],
                  [_edge("T", "S")], communities={"c0": ["S", "T"]}, sem_edges=[_se("S")])
    r = health.health(out, include_tests=True)
    assert r["scope"].startswith("all")
    assert r["semantic"]["code_count"] == 2                              # both counted


# ---------- Phase 5: technical-debt assessment ----------

def _debt(structural, semantic=None):
    sm = analytics.analyze(structural)
    sem = health.semantic_health(structural, semantic)
    return health.debt_assessment(structural, sm, sem)


def test_debt_by_type_counts():
    s = _struct([_node("A", file="f1.py"), _node("B", file="f2.py"), _node("orphan")],
                [_edge("A", "B"), _edge("B", "A")], communities={"c0": ["A", "B", "orphan"]})
    bt = _debt(s)["by_type"]
    assert bt.get("cycle", 0) >= 1 and bt.get("dead-code", 0) >= 1       # file cycle + orphan


def test_debt_by_feature_rollup():
    s = _struct([_node("o1"), _node("o2")], [], communities={"c0": ["o1"], "c1": ["o2"]})
    feats = {f["feature"] for f in _debt(s)["by_feature"]}
    assert {"c0", "c1"} <= feats                                        # dead-code rolled up per community


def test_debt_by_component_rollup():
    s = _struct([_node("o1", file="src/x.py"), _node("o2", file="src/x.py")], [],
                communities={"c0": ["o1", "o2"]})
    bc = _debt(s)["by_component"]
    assert bc and bc[0]["component"] == "src/x.py" and bc[0]["debt_items"] >= 2


def test_debt_score_shows_components():
    d = _debt(_struct([_node("o")], [], communities={"c0": ["o"]}))
    assert 0 <= d["score"] <= 1
    assert d["score_components"]["dead-code"] > 0                       # never opaque — components shown


def test_debt_empty_graph_zero():
    d = _debt(_struct([], []))
    assert d["score"] == 0.0 and d["total_items"] == 0


def test_health_includes_debt(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("o", file="src/a.py")], [], communities={"c0": ["o"]})
    r = health.health(out)
    assert "debt" in r and "score" in r["debt"] and "by_type" in r["debt"]


# ---------- dynamic-wiring scan (dead-code false-positive rescue) ----------

def _src(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_dynamic_refs_rescues_argparse_handler(tmp_path):
    _src(tmp_path, "src/a.py",
         "def handler(args):\n    pass\n\ndef wire(sub):\n    sub.set_defaults(func=handler)\n")
    st = _struct([_node("H", label="handler", file="src/a.py")], [])
    dyn = health.dynamic_refs(tmp_path, st, [{"id": "H", "label": "handler", "source_file": "src/a.py"}])
    assert dyn == {"H": "src/a.py:5"}                  # the set_defaults line, not the def line


def test_dynamic_refs_rescues_bare_constant_read(tmp_path):
    _src(tmp_path, "src/a.py",
         '_MARK = "x"\n\ndef use(path):\n    return stamp(path, _MARK)\n')
    st = _struct([_node("M", label="_MARK", file="src/a.py")], [])
    dyn = health.dynamic_refs(tmp_path, st, [{"id": "M", "label": "_MARK", "source_file": "src/a.py"}])
    assert "M" in dyn                                  # arg-position read; its own `_MARK = ` line skipped


def test_dynamic_refs_ignores_defs_calls_assignments_imports(tmp_path):
    _src(tmp_path, "src/a.py",
         "from x import truly_dead\n\ndef truly_dead():\n    pass\n\ntruly_dead = 1\nclass truly_dead:\n    pass\n")
    st = _struct([_node("D", label="truly_dead", file="src/a.py")], [])
    dyn = health.dynamic_refs(tmp_path, st, [{"id": "D", "label": "truly_dead", "source_file": "src/a.py"}])
    assert dyn == {}                                   # no VALUE reference anywhere -> stays dead


def test_health_drops_dynamically_wired_only_with_repo(tmp_path):
    _src(tmp_path, "src/a.py",
         "def handler(args):\n    pass\n\ndef wire(sub):\n    sub.set_defaults(func=handler)\n")
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("H", label="handler", file="src/a.py")], [])
    base = health.health(out)["structural"]["dead_code"]
    assert base["count"] == 1 and base["dynamically_wired_excluded"] == 0
    dc = health.health(out, repo=tmp_path)["structural"]["dead_code"]
    assert dc["count"] == 0 and dc["dynamically_wired_excluded"] == 1
    assert dc["dynamically_wired"][0]["evidence"] == "src/a.py:5"


def test_debt_score_sees_filtered_dead_code(tmp_path):
    _src(tmp_path, "src/a.py",
         "def handler(args):\n    pass\n\ndef wire(sub):\n    sub.set_defaults(func=handler)\n")
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("H", label="handler", file="src/a.py")], [])
    with_repo = health.health(out, repo=tmp_path)["debt"]["by_type"].get("dead-code", 0)
    without = health.health(out)["debt"]["by_type"].get("dead-code", 0)
    assert without == 1 and with_repo == 0


def test_confirmed_dispatches_edge_authoritative_for_dead_code(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("H", label="handler", file="src/a.py")], [],
                  sem_edges=[{"source": "doc:d", "target": "H", "relation": "dispatches"}])
    dc = health.health(out)["structural"]["dead_code"]
    assert dc["count"] == 0 and dc["dispatch_confirmed_excluded"] == 1


def test_dispatches_edges_do_not_count_as_doc_coverage(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("H", label="handler", file="src/a.py")], [],
                  sem_edges=[{"source": "doc:d", "target": "H", "relation": "dispatches"}])
    r = health.health(out)
    assert r["semantic"]["coverage_overall"] == 0.0   # liveness wiring is not documentation


# ---------- comment-aware heuristic + stateful triage ----------

def test_comment_mention_is_not_dynamic_evidence(tmp_path):
    _src(tmp_path, "src/a.py",
         "def victim():\n    pass\n\n# we stopped calling victim here\nx = 1  # victim was removed\n")
    st = _struct([_node("V", label="victim", file="src/a.py")], [])
    assert health.dynamic_refs(tmp_path, st, [{"id": "V", "label": "victim",
                                               "source_file": "src/a.py"}]) == {}


def test_quoted_name_still_counts_as_dispatch_evidence(tmp_path):
    _src(tmp_path, "src/a.py",
         'def victim():\n    pass\n\ndef go(mod):\n    return getattr(mod, "victim")()\n')
    st = _struct([_node("V", label="victim", file="src/a.py")], [])
    dyn = health.dynamic_refs(tmp_path, st, [{"id": "V", "label": "victim",
                                              "source_file": "src/a.py"}])
    assert dyn == {"V": "src/a.py:5"}


def test_triage_keep_verdict_acknowledges_queue_item(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("K", label="keeper", file="src/a.py")], [])
    (out / "triage.json").write_text(json.dumps({"schema_version": 1, "verdicts": [
        {"id": "K", "label": "keeper", "verdict": "keep", "reason": "external API"}]}))
    dc = health.health(out)["structural"]["dead_code"]
    assert dc["count"] == 0
    assert dc["acknowledged"][0]["id"] == "K" and dc["acknowledged"][0]["reason"] == "external API"
    assert dc["triage_stale"] == []


def test_triage_stale_verdict_surfaced(tmp_path):
    out = tmp_path / "graphify-out"
    _write_layers(out, [_node("A", label="alive", file="src/a.py")], [])
    (out / "triage.json").write_text(json.dumps({"schema_version": 1, "verdicts": [
        {"id": "cg:gone", "label": "gone", "verdict": "keep", "reason": "old"}]}))
    dc = health.health(out)["structural"]["dead_code"]
    assert dc["triage_stale"] == ["cg:gone"] and "STALE" in dc["note"]
