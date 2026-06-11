"""py_calls — supplemental Python cross-module call edges (the codegraph same-file gap).

Pure-unit: synthetic AdaptResults over real tmp_path sources; no codegraph needed.
"""
from cg_graphify_bridge import py_calls
from cg_graphify_bridge.adapter import AdaptResult


def _n(nid, label, file, kind="function", qn=None, s=1, e=None):
    return {"id": nid, "label": label, "file_type": "code", "source_file": file,
            "source_location": f"L{s}",
            "metadata": {"cg_kind": kind, "qualified_name": qn or label,
                         "start_line": s, "end_line": e if e is not None else s}}


_A_SRC = """from . import b
from .b import helper as h
import pkg.b as pb

def caller():
    b.target()
    h()
    pb.other()

b.module_level()
"""

_B_SRC = """def target(): pass
def helper(): pass
def other(): pass
def module_level(): pass
"""


def _fixture(tmp_path):
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg/__init__.py").write_text("")
    (tmp_path / "pkg/a.py").write_text(_A_SRC)
    (tmp_path / "pkg/b.py").write_text(_B_SRC)
    nodes = [
        _n("cg:fa", "a.py", "pkg/a.py", kind="file", s=1, e=10),
        _n("cg:fb", "b.py", "pkg/b.py", kind="file", s=1, e=4),
        _n("cg:fi", "__init__.py", "pkg/__init__.py", kind="file"),
        _n("cg:caller", "caller", "pkg/a.py", s=5, e=8),
        _n("cg:target", "target", "pkg/b.py", s=1),
        _n("cg:helper", "helper", "pkg/b.py", s=2),
        _n("cg:other", "other", "pkg/b.py", s=3),
        _n("cg:modlvl", "module_level", "pkg/b.py", s=4),
    ]
    return AdaptResult(nodes, [], {}, {})


def _pairs(res):
    return {(e["source"], e["target"]) for e in res.edges}


def test_enrich_resolves_module_attr_symbol_and_dotted_aliases(tmp_path):
    res = py_calls.enrich(tmp_path, _fixture(tmp_path))
    got = _pairs(res)
    assert ("cg:caller", "cg:target") in got      # b.target()   via `from . import b`
    assert ("cg:caller", "cg:helper") in got      # h()          via `from .b import helper as h`
    assert ("cg:caller", "cg:other") in got       # pb.other()   via `import pkg.b as pb`
    assert res.stats["pyast_call_edges"] == 4
    e = next(e for e in res.edges if e["target"] == "cg:target")
    assert e["relation"] == "calls" and e["context"] == "pyast" and e["confidence"] == "INFERRED"


def test_module_level_call_attributes_to_file_node(tmp_path):
    res = py_calls.enrich(tmp_path, _fixture(tmp_path))
    assert ("cg:fa", "cg:modlvl") in _pairs(res)  # b.module_level() outside any def


def test_existing_edges_not_duplicated(tmp_path):
    fix = _fixture(tmp_path)
    fix.edges.append({"source": "cg:caller", "target": "cg:target", "relation": "calls",
                      "context": "calls", "confidence": "EXTRACTED", "weight": 1.0,
                      "source_file": "", "source_location": ""})
    res = py_calls.enrich(tmp_path, fix)
    assert res.stats["pyast_call_edges"] == 3     # cg:caller->cg:target already present
    assert sum(1 for e in res.edges
               if (e["source"], e["target"]) == ("cg:caller", "cg:target")) == 1


def test_ambiguous_absolute_import_never_guesses(tmp_path):
    for d in ("x", "y"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "m.py").write_text("def f(): pass\n")
    (tmp_path / "main.py").write_text("import m\n\ndef go():\n    m.f()\n")
    nodes = [_n("cg:go", "go", "main.py", s=3, e=4),
             _n("cg:xf", "f", "x/m.py"), _n("cg:yf", "f", "y/m.py")]
    res = py_calls.enrich(tmp_path, AdaptResult(nodes, [], {}, {}))
    assert res.edges == []                        # two suffix matches for `m` -> skipped


def test_unresolved_and_instance_calls_skipped(tmp_path):
    (tmp_path / "a.py").write_text(
        "def go(self):\n    print('x')\n    self.run()\n    unknown.thing()\n")
    res = py_calls.enrich(tmp_path, AdaptResult([_n("cg:go", "go", "a.py", s=1, e=4)], [], {}, {}))
    assert res.edges == []


def test_nested_def_not_a_resolution_target(tmp_path):
    # qualified_name != label marks a nested/shadowed def — must not be importable-by-name
    (tmp_path / "a.py").write_text("from .b import inner\n\ndef go():\n    inner()\n")
    (tmp_path / "b.py").write_text("def outer():\n    def inner(): pass\n")
    nodes = [_n("cg:go", "go", "a.py", s=3, e=4),
             _n("cg:inner", "inner", "b.py", qn="outer::inner", s=2)]
    res = py_calls.enrich(tmp_path, AdaptResult(nodes, [], {}, {}))
    assert res.edges == []


def test_deterministic_and_noop_for_non_python(tmp_path):
    r1 = py_calls.enrich(tmp_path, _fixture(tmp_path))
    r2 = py_calls.enrich(tmp_path, _fixture(tmp_path))
    assert r1.edges == r2.edges
    ts = AdaptResult([_n("cg:t", "t", "src/x.ts")], [], {}, {})
    assert py_calls.enrich(tmp_path, ts) is ts    # no .py files -> same object back
