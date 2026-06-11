"""Phase 2 (2c) — `benchmark`: token-reduction per query class, real-or-fallback tokenizer."""
import pytest

from cg_graphify_bridge import benchmark, driver
from cg_graphify_bridge.adapter import AdaptResult


def _node(nid, file="src/a.py"):
    return {"id": nid, "label": nid, "file_type": "code", "source_file": file,
            "source_location": "L1",
            "metadata": {"cg_kind": "function", "qualified_name": nid, "signature": "()"}}


def _write(out, nodes, edges, communities, gods):
    driver.write_structural({"adapt": AdaptResult(nodes, edges, {}, {}),
                             "communities": communities, "god_nodes": gods, "surprising": []}, out)


def _repo(tmp_path):
    repo = tmp_path
    (repo / "src").mkdir(parents=True)
    # a deliberately large source file so the naive baseline >> graph identity lines
    (repo / "src" / "a.py").write_text("def big():\n" + "\n".join(f"    x{i} = {i}" for i in range(300)) + "\n")
    out = repo / "graphify-out"
    _write(out, [_node("A"), _node("B")],
           [{"source": "A", "target": "B", "relation": "calls", "weight": 1.0}],
           {"c0": ["A", "B"]}, [{"id": "A", "label": "A", "degree": 1}])
    return repo, out


def test_benchmark_reduction_per_query_class(tmp_path):
    repo, out = _repo(tmp_path)
    r = benchmark.benchmark(out, repo)
    assert r["pinpoint"]["questions"] and r["global"]["questions"]
    pin = r["pinpoint"]["questions"][0]
    assert {"query", "graph_tokens", "baseline_tokens", "reduction"} <= set(pin)
    assert pin["reduction"] > 0                      # identity lines ≪ the whole 300-line file


def test_benchmark_labels_tokenizer_and_baseline(tmp_path):
    repo, out = _repo(tmp_path)
    r = benchmark.benchmark(out, repo)
    assert r["tokenizer"] and "naive full-file read" in r["baseline"]


def test_benchmark_fallback_when_no_tiktoken(monkeypatch):
    monkeypatch.setattr(benchmark, "_load_tiktoken", lambda: None)
    fn, name = benchmark._tokenizer()
    assert "chars/4" in name and fn("abcdefgh") >= 1


def test_benchmark_uses_real_tokenizer_when_available():
    if benchmark._load_tiktoken() is None:
        pytest.skip("tiktoken not installed — fallback path covered separately")
    _, name = benchmark._tokenizer()
    assert "tiktoken" in name


# ---------- 2d: opt-in non-blocking CI advisory ----------

def test_ci_advisory_is_non_blocking():
    from cg_graphify_bridge import cli
    tmpl = cli._read_template("graph-build.yml")
    assert "cg-graphify-bridge health" in tmpl       # the advisory step exists
    assert "continue-on-error: true" in tmpl         # never gates the build
    assert "CG_HEALTH_ADVISORY" in tmpl              # opt-in via repo variable
