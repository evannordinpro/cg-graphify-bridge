"""Phase 3 — callers / callees / impact navigation over the committed graph."""
import json
from types import SimpleNamespace

import pytest

from cg_graphify_bridge import cli, driver, query
from cg_graphify_bridge.adapter import AdaptResult


def _node(nid, kind="function", file="src/a.py", qn=None, label=None):
    return {"id": nid, "label": label or nid, "file_type": "code", "source_file": file,
            "source_location": "L1",
            "metadata": {"cg_kind": kind, "qualified_name": qn or (label or nid), "language": "python"}}


def _edge(s, t, rel="calls"):
    return {"source": s, "target": t, "relation": rel, "weight": 1.0}


def _struct(nodes, edges):
    return {"schema_version": 1, "layer": "structural", "nodes": nodes, "edges": edges,
            "communities": {}, "god_nodes": [], "surprising": [], "stats": {}}


def _write(out, nodes, edges):
    driver.write_structural({"adapt": AdaptResult(nodes, edges, {}, {}), "communities": {},
                             "god_nodes": [], "surprising": []}, out)


def _ids(res):
    return {r["id"] for r in res["results"]}


# ---------- resolve ----------

def test_resolve_by_label():
    s = _struct([_node("X", label="build_repo")], [])
    assert [n["id"] for n in query.resolve(s, "build_repo")] == ["X"]


def test_resolve_by_qualified_name():
    s = _struct([_node("X", label="foo", qn="pkg.mod.foo")], [])
    assert [n["id"] for n in query.resolve(s, "pkg.mod.foo")] == ["X"]    # not a label, matched by qn


def test_resolve_ambiguous_returns_all():
    s = _struct([_node("A", label="helper"), _node("B", label="helper")], [])
    assert {n["id"] for n in query.resolve(s, "helper")} == {"A", "B"}


def test_resolve_unknown_empty():
    assert query.resolve(_struct([_node("X")], []), "nope") == []


# ---------- callers / callees ----------

def test_callers_direct():
    s = _struct([_node(x) for x in ("A", "B", "X")], [_edge("A", "X"), _edge("B", "X")])
    assert _ids(query.callers(s, "X")) == {"A", "B"}                      # A,B depend on X


def test_callers_none_for_leaf_target():
    s = _struct([_node("Z"), _node("A")], [_edge("Z", "A")])
    assert query.callers(s, "Z")["results"] == []                        # nothing depends on Z


def test_callers_depth2():
    s = _struct([_node(x) for x in ("A", "B", "X")], [_edge("A", "B"), _edge("B", "X")])
    r = query.callers(s, "X", depth=2)
    assert _ids(r) == {"A", "B"} and r["by_hop"] == {1: 1, 2: 1}         # B hop1, A hop2


def test_callees_direct():
    s = _struct([_node(x) for x in ("X", "A", "B")], [_edge("X", "A"), _edge("X", "B")])
    assert _ids(query.callees(s, "X")) == {"A", "B"}


def test_callees_excludes_contains():
    s = _struct([_node(x) for x in ("X", "A", "B")], [_edge("X", "A", rel="contains"), _edge("X", "B")])
    assert _ids(query.callees(s, "X")) == {"B"}                           # `contains` is not a dependency


# ---------- impact ----------

def test_impact_transitive_dependents():
    s = _struct([_node(x) for x in ("A", "B", "X")], [_edge("A", "B"), _edge("B", "X")])
    assert _ids(query.impact(s, "X")) == {"A", "B"}                       # full transitive blast radius


def test_impact_depth1_equals_direct_callers():
    s = _struct([_node(x) for x in ("A", "B", "X")], [_edge("A", "B"), _edge("B", "X")])
    assert _ids(query.impact(s, "X", depth=1)) == _ids(query.callers(s, "X", depth=1))


def test_impact_leaf_empty():
    s = _struct([_node("Z"), _node("A")], [_edge("Z", "A")])
    assert query.impact(s, "Z")["results"] == []


def test_impact_hop_grouping():
    s = _struct([_node(x) for x in ("A", "B", "X")], [_edge("A", "B"), _edge("B", "X")])
    assert query.impact(s, "X")["by_hop"] == {1: 1, 2: 1}


# ---------- CLI ----------

def _cli(tmp_path, cmd, symbol, nodes, edges, depth=1, as_json=True):
    _write(tmp_path / "graphify-out", nodes, edges)
    cli._query_cmd(SimpleNamespace(repo=str(tmp_path), out="graphify-out", symbol=symbol,
                                   depth=depth, json=as_json, cmd=cmd))


def test_cli_impact_json_shape(tmp_path, capsys):
    _cli(tmp_path, "impact", "X", [_node(x) for x in ("A", "B", "X")],
         [_edge("A", "B"), _edge("B", "X")], depth=None)
    out = json.loads(capsys.readouterr().out)
    assert out["kind"] == "impact" and out["count"] == 2 and "by_hop" in out


def test_cli_ambiguous_symbol_exits_nonzero(tmp_path, capsys):
    with pytest.raises(SystemExit) as ei:
        _cli(tmp_path, "callers", "dup", [_node("A", label="dup"), _node("B", label="dup")], [],
             as_json=False)
    assert ei.value.code == 2
    assert "ambiguous" in capsys.readouterr().out.lower()


def test_cli_unknown_symbol_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit) as ei:
        _cli(tmp_path, "callees", "ghost", [_node("X")], [])
    assert ei.value.code == 2


# ---------- docs ----------

def test_setup_documents_query_commands():
    from pathlib import Path
    txt = (Path(__file__).resolve().parents[1] / "docs" / "setup.md").read_text()
    assert "callers" in txt and "callees" in txt and "impact" in txt
