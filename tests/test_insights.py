"""Phase 4 — the insights showcase (compose health + benchmark → beautiful versioned markdown)."""
from pathlib import Path
from types import SimpleNamespace

from cg_graphify_bridge import cli, driver, insights
from cg_graphify_bridge.adapter import AdaptResult

ROOT = Path(__file__).resolve().parents[1]


def _node(nid, kind="function", file="src/a.py", abstract=None, exported=None, label=None):
    md = {"cg_kind": kind, "qualified_name": label or nid, "language": "python", "start_line": 1, "end_line": 2}
    if abstract is not None:
        md["is_abstract"] = abstract
    if exported is not None:
        md["is_exported"] = exported
    return {"id": nid, "label": label or nid, "file_type": "code", "source_file": file,
            "source_location": "L1", "metadata": md}


def _setup(tmp_path, with_semantic=True):
    repo = tmp_path
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "a.py").write_text("class C:\n" + "\n".join(f"    def m{i}(self): pass" for i in range(60)) + "\n")
    out = repo / "graphify-out"
    nodes = [_node("C", kind="class", abstract=False), _node("A"), _node("B")]
    driver.write_structural(
        {"adapt": AdaptResult(nodes, [{"source": "A", "target": "C", "relation": "calls", "weight": 1.0},
                                      {"source": "B", "target": "C", "relation": "calls", "weight": 1.0}], {}, {}),
         "communities": {"c0": ["C", "A", "B"]}, "god_nodes": [{"id": "C", "label": "C", "degree": 2}],
         "surprising": []}, out)
    if with_semantic:
        driver.write_semantic({"semantic_nodes": [{"id": "doc:d", "label": "d", "file_type": "document"}],
                               "semantic_edges": [{"source": "doc:d", "target": "A", "relation": "references"}],
                               "stats": {}}, out)
    return repo, out


# ---------- 4a: compose + render ----------

def test_build_insights_composes_health_and_benchmark(tmp_path):
    repo, out = _setup(tmp_path)
    ins = insights.build_insights(out, repo)
    assert set(ins) >= {"repo", "health", "benchmark", "headline"}
    assert ins["health"]["combined"]["available"] is True and "pinpoint" in ins["benchmark"]


def test_insights_handles_missing_semantic(tmp_path):
    repo, out = _setup(tmp_path, with_semantic=False)
    md = insights.render_markdown(insights.build_insights(out, repo))
    assert "no semantic overlay" in md          # graceful — value/structural still render


def test_render_contains_mermaid_quadrant(tmp_path):
    repo, out = _setup(tmp_path)
    md = insights.render_markdown(insights.build_insights(out, repo))
    assert "```mermaid" in md and "quadrantChart" in md and "Zone of Pain" in md


def test_render_cites_graphrag_band(tmp_path):
    repo, out = _setup(tmp_path)
    md = insights.render_markdown(insights.build_insights(out, repo))
    assert "26–97%" in md and "2404.16130" in md


def test_render_shows_god_node_coverage_and_hubs(tmp_path):
    repo, out = _setup(tmp_path)
    md = insights.render_markdown(insights.build_insights(out, repo))
    assert "God-node coverage" in md and "`C`" in md   # C is an undocumented hub


def test_render_unicode_gauges(tmp_path):
    repo, out = _setup(tmp_path)
    md = insights.render_markdown(insights.build_insights(out, repo))
    assert "█" in md or "░" in md


def test_render_defines_each_metric(tmp_path):
    repo, out = _setup(tmp_path)
    md = insights.render_markdown(insights.build_insights(out, repo))
    assert "What each metric measures" in md                  # the glossary section
    for term in ("Token efficiency", "Instability (I)", "Abstractness (A)", "Conductance",
                 "Betweenness", "Zone of Pain", "Zone of Uselessness", "God-node coverage",
                 "Centrality-weighted coverage", "Dead-code review queue", "Knowledge debt",
                 "Undocumented load-bearing risk"):
        assert term in md, f"glossary missing definition for: {term}"


# ---------- Phase 5: Technical Debt section ----------

def test_render_has_debt_section(tmp_path):
    repo, out = _setup(tmp_path)
    md = insights.render_markdown(insights.build_insights(out, repo))
    assert "## 🧹 Technical Debt" in md and "Debt score" in md


def test_render_debt_score_gauge(tmp_path):
    repo, out = _setup(tmp_path)
    md = insights.render_markdown(insights.build_insights(out, repo))
    assert "| Debt type | Count |" in md              # the by-type breakdown renders


def test_glossary_defines_debt_terms(tmp_path):
    repo, out = _setup(tmp_path)
    md = insights.render_markdown(insights.build_insights(out, repo))
    for term in ("Debt score", "God object", "Dangling link"):
        assert term in md


def test_render_deterministic_no_timestamp(tmp_path):
    repo, out = _setup(tmp_path)
    a = insights.render_markdown(insights.build_insights(out, repo))
    b = insights.render_markdown(insights.build_insights(out, repo))
    assert a == b                                  # content-deterministic (diff-gate friendly)
    assert "content-deterministic" in a            # footer states it; no date/SHA in body


# ---------- 4b: CLI ----------

def test_cli_insights_stdout(tmp_path, capsys):
    repo, _ = _setup(tmp_path)
    cli._insights(SimpleNamespace(repo=str(repo), out="graphify-out", out_file=None))
    assert "# 📊 Graph Insights" in capsys.readouterr().out


def test_cli_insights_out_file_writes(tmp_path):
    repo, _ = _setup(tmp_path)
    cli._insights(SimpleNamespace(repo=str(repo), out="graphify-out", out_file="GRAPH_INSIGHTS.md"))
    assert "Graph Insights" in (repo / "GRAPH_INSIGHTS.md").read_text()


# ---------- 4c: CI wiring ----------

def test_tool_workflow_generates_insights():
    wf = (ROOT / ".github" / "workflows" / "graph-build.yml").read_text()
    assert "insights . --out-file GRAPH_INSIGHTS.md" in wf
    assert "GRAPH_INSIGHTS.md" in wf.split("layers=")[1].split("\n")[0]   # in the committed layers


def test_template_insights_opt_in_gated():
    tmpl = cli._read_template("graph-build.yml")
    assert "insights . --out-file GRAPH_INSIGHTS.md" in tmpl
    assert "CG_INSIGHTS" in tmpl and "vars.CG_INSIGHTS == 'true'" in tmpl   # opt-in gate


# ---------- 4d: docs ----------

def test_setup_documents_insights():
    txt = (ROOT / "docs" / "setup.md").read_text()
    assert "insights" in txt and "GRAPH_INSIGHTS.md" in txt
