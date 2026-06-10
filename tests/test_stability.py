"""The crown stability test — trace R2/D1.

Proves the composite id is identical across a pure line-shifting edit (the exact
case codegraph's primary, line-bearing id FAILS). This is the premise the whole
merge architecture rests on, validated against real codegraph behaviour.
"""
from cg_graphify_bridge import adapter
from conftest import index_repo, requires_codegraph


def _target(db):
    res = adapter.adapt(db)
    n = next(n for n in res.nodes
             if n["label"] == "target" and n["metadata"]["cg_kind"] == "function")
    return n["id"], n["metadata"]["start_line"]


@requires_codegraph
def test_composite_id_stable_across_line_shift(tmp_path):
    a = tmp_path / "a" / "m"
    a.mkdir(parents=True)
    (a / "x.py").write_text("def target(x):\n    return x + 1\n")

    b = tmp_path / "b" / "m"
    b.mkdir(parents=True)
    (b / "x.py").write_text("\n\n\n\n\n\ndef target(x):\n    return x + 1\n")

    id_a, line_a = _target(index_repo(tmp_path / "a"))
    id_b, line_b = _target(index_repo(tmp_path / "b"))

    assert line_a != line_b, "line numbers must genuinely differ between variants"
    assert id_a == id_b, "composite id MUST be stable across a pure line shift (D1)"
