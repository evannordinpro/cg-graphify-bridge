"""Phase 4 — the insights showcase: composes Phase-2 `health` + `benchmark` into one beautiful,
GitHub-native, **content-deterministic** markdown (no timestamp/SHA → diff-gate friendly).

Pure composition — no new metric logic. CI renders it to `GRAPH_INSIGHTS.md` at the repo root and
commits it via the build-on-PR-branch commit-back, so the report is versioned with each build.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import benchmark as _benchmark
from . import health as _health


def build_insights(out: Path, repo: Path) -> dict:
    """Compose health (production-scoped) + benchmark + derived headline figures."""
    h = _health.health(out)
    b = _benchmark.benchmark(out, repo)
    ab = h["structural"]["abstractness"]["communities"]
    comb = h["combined"]
    return {
        "repo": Path(repo).name,
        "health": h, "benchmark": b,
        "headline": {
            "pinpoint": b["pinpoint"]["mean_reduction"],
            "global": b["global"]["mean_reduction"],
            "cycles": len(h["structural"]["cycles"]["module_cycles"]),
            "god_coverage": comb.get("god_node_coverage") if comb.get("available") else None,
            "pain": sum(1 for c in ab if c["zone"] == "pain"),
            "uselessness": sum(1 for c in ab if c["zone"] == "uselessness"),
            "debt": (h["knowledge_debt"] or {}).get("index"),
        },
    }


def _pct(x) -> str:
    return f"{x:.0%}" if isinstance(x, (int, float)) else "n/a"


def _bar(p, width: int = 20) -> str:
    p = max(0.0, min(1.0, p or 0.0))
    filled = round(p * width)
    return "`" + "█" * filled + "░" * (width - filled) + f"` {p:.0%}"


def _quadrant(communities: list) -> list:
    """A mermaid quadrantChart of the Martin main-sequence (x=Instability, y=Abstractness).
    Zone of Pain = bottom-left (stable+concrete); Zone of Uselessness = top-right (unstable+abstract)."""
    pts = sorted(communities, key=lambda c: (-c["distance"], c["community"]))[:16]
    out = ["```mermaid", "quadrantChart",
           "    title Architecture — Abstractness vs Instability (per community)",
           "    x-axis Stable --> Unstable",
           "    y-axis Concrete --> Abstract",
           # quadrantChart's lexer rejects ( ) + : in bare text — keep these labels to
           # alphanumerics, spaces, commas and hyphens or the whole diagram fails to render.
           "    quadrant-1 Zone of Uselessness",
           "    quadrant-2 Ideal - abstract and stable",
           "    quadrant-3 Zone of Pain",
           "    quadrant-4 Volatile leaf - ok"]
    for c in pts:
        label = (re.sub(r"[^A-Za-z0-9 ]", "", f"c{c['community']}")[:18]) or "c"
        out.append(f'    "{label}": [{c["instability"]:.3f}, {c["abstractness"]:.3f}]')
    out.append("```")
    return out


# Plain-language definition of EVERY stat the report surfaces — exactly what it measures.
_GLOSSARY = [
    ("Token efficiency (pinpoint / global)",
     "the % fewer tokens an agent reads to answer a question using the graph's node summaries "
     "instead of opening whole source files — *pinpoint* = single-symbol lookups, *global* = "
     "whole-subsystem questions."),
    ("Dependency cycle",
     "a set of files that depend on each other in a loop (A→B→…→A); cycles make changes ripple "
     "unpredictably — 0 is ideal."),
    ("Abstractness (A)",
     "fraction of a community's types that are abstract (interfaces / abstract classes) vs "
     "concrete — 0 = all concrete, 1 = all abstract."),
    ("Instability (I)",
     "a community's exposure to forced change = outgoing deps ÷ (incoming + outgoing) — 0 = stable "
     "(others depend on it), 1 = volatile (it depends on everything)."),
    ("Zone of Pain",
     "concrete *and* heavily depended-on (low A, low I): rigid and risky to change."),
    ("Zone of Uselessness",
     "abstract *but* unused (high A, high I): a dead abstraction to delete or inline."),
    ("Conductance (leakiest module)",
     "the share of a community's connections that cross its boundary — high = a leaky module not "
     "cleanly separated from the rest."),
    ("Betweenness (top hub)",
     "how often a symbol lies on the shortest path between other symbols — a high value is an "
     "architectural chokepoint the system routes through."),
    ("High fan-out",
     "symbols that depend on an unusually large number of others — a single-responsibility smell / "
     "refactor candidate."),
    ("Dead-code review queue",
     "symbols nothing else references (excluding entry points & exports) — a *review* list only; "
     "static analysis over-flags reflection/dynamic dispatch, so never auto-delete."),
    ("God-node coverage",
     "of the most-connected hub symbols, the % that have at least one documentation link."),
    ("Centrality-weighted coverage",
     "documentation coverage weighted by each symbol's importance — the gap vs raw coverage reveals "
     "whether the docs cover what actually matters."),
    ("Undocumented hubs",
     "central hub symbols with no documentation — the doc backlog, ordered by importance."),
    ("Darkest subsystem",
     "the community carrying the most architectural importance but the least documentation."),
    ("Undocumented load-bearing risk",
     "importance × (1 − documented), ranked — symbols that are both central and undocumented: "
     "document these first."),
    ("Knowledge debt",
     "a 0–1 roll-up of missing importance-weighted coverage + stale/dangling doc links — lower is "
     "better; shown with its components so it's never an opaque score."),
    ("Debt score",
     "a 0–1 technical-debt roll-up = weighted, saturating contributions from each debt type (cycles, "
     "Zone-of-Pain, god-objects, high-fan-out, dead-code, dangling links), shown per-type so it's "
     "never opaque — higher = more debt. Also broken down by feature (community) and component (file)."),
    ("God object",
     "a symbol with unusually high betweenness (an architectural chokepoint) — central enough that "
     "changing it ripples widely; a split candidate."),
    ("Dangling link",
     "a doc→code link whose target symbol no longer exists in the graph — a broken reference / "
     "documentation debt to fix or re-point."),
]


def _glossary() -> list:
    return (["<details>",
             "<summary>📖 <b>What each metric measures</b> — plain-language definitions</summary>", ""]
            + [f"- **{term}** — {definition}" for term, definition in _GLOSSARY]
            + ["", "</details>"])


def render_markdown(ins: dict) -> str:
    h, b, hd = ins["health"], ins["benchmark"], ins["headline"]
    s, comb, sem = h["structural"], h["combined"], h["semantic"]
    L = [f"# 📊 Graph Insights — {ins['repo']}", "",
         f"> **{_pct(hd['pinpoint'])} less context** to answer a pinpoint code question · "
         f"**{hd['cycles']}** dependency cycle{'' if hd['cycles'] == 1 else 's'} · "
         f"**{_pct(hd['god_coverage'])}** of architectural hubs documented", "",
         "| 🎯 Token efficiency | 🏛️ Architecture | 📚 Documentation |",
         "|:--:|:--:|:--:|",
         f"| {_pct(hd['pinpoint'])} pinpoint · {_pct(hd['global'])} global "
         f"| {hd['cycles']} cycles · {hd['pain']} Zone-of-Pain "
         f"| hubs {_pct(hd['god_coverage'])} · debt {hd['debt'] if hd['debt'] is not None else 'n/a'} |", ""]

    # 🎯 Token efficiency
    L += ["## 🎯 Token efficiency", "",
          "Graph-guided retrieval (node identity + neighbourhood) vs reading whole source files:", "",
          f"- **pinpoint** &nbsp; {_bar(b['pinpoint']['mean_reduction'])}",
          f"- **global** &nbsp;&nbsp;&nbsp; {_bar(b['global']['mean_reduction'])}", "",
          "> GraphRAG reports **26–97% fewer tokens** for graph-guided retrieval "
          "([arXiv:2404.16130](https://arxiv.org/abs/2404.16130)) — this repo lands in-band.",
          f"> _Tokenizer: {b['tokenizer']}; baseline: {b['baseline']}._", ""]

    # 🏛️ Architecture
    L += ["## 🏛️ Architecture", ""]
    ab = s["abstractness"]
    if ab["communities"]:
        L += _quadrant(ab["communities"]) + [""]
    else:
        L += ["_(no typed communities to plot)_", ""]
    if ab.get("caveat"):
        L += [f"> ⚠️ _{ab['caveat']}_", ""]
    mc = s["cycles"]["module_cycles"]
    L.append(f"- **Dependency cycles:** {len(mc)} "
             + ("— acyclic ✓" if not mc
                else f"— worst `{mc[0]['suggested_cut']['from']}` → `{mc[0]['suggested_cut']['to']}` (cut this edge)"))
    L.append(f"- **Zone of Pain:** {hd['pain']} · **Zone of Uselessness:** {hd['uselessness']} communities")
    if s["leaky_communities"]:
        lk = s["leaky_communities"][0]
        L.append(f"- **Leakiest module:** community {lk['community']} (conductance {lk['conductance']})")
    if s["god_objects"]:
        g = s["god_objects"][0]
        L.append(f"- **Top architectural hub (betweenness):** `{g['id']}`")
    L.append(f"- **High fan-out (SRP) candidates:** {len(s['fan'].get('high_fan_out', []))} · "
             f"**Dead-code review queue:** {s['dead_code']['count']}")
    L.append("")

    # 🧹 Technical Debt
    debt = h.get("debt", {})
    L += ["## 🧹 Technical Debt", "",
          f"**Debt score** &nbsp; {_bar(debt.get('score', 0))} _(0 = clean → 1 = heavy)_", ""]
    bt = debt.get("by_type", {})
    if bt:
        L += ["| Debt type | Count |", "|---|--:|"]
        L += [f"| {t} | {c} |" for t, c in sorted(bt.items(), key=lambda kv: (-kv[1], kv[0]))]
        L.append("")
    if debt.get("by_feature"):
        f0 = debt["by_feature"][0]
        L.append(f"- **Most-indebted feature:** community {f0['feature']} ({f0['debt_items']} debt items)")
    if debt.get("by_component"):
        c0 = debt["by_component"][0]
        L.append(f"- **Most-indebted component:** `{c0['component']}` ({c0['debt_items']} debt items)")
    sc = {t: v for t, v in debt.get("score_components", {}).items() if v > 0}
    if sc:
        L.append("- _score contributions: "
                 + ", ".join(f"{t} {v}" for t, v in sorted(sc.items(), key=lambda kv: -kv[1])) + "_")
    L.append("")

    # 📚 Documentation
    L += ["## 📚 Documenting what matters", ""]
    if comb.get("available"):
        L.append(f"- **God-node coverage** &nbsp; {_bar(comb['god_node_coverage'] or 0)}")
        L.append(f"- **Centrality-weighted coverage** &nbsp; {_bar(comb['centrality_weighted_coverage'])} "
                 "_(the gap vs raw coverage = mis-targeted doc effort)_")
        if comb["undocumented_god_nodes"]:
            L.append("- **Undocumented hubs:** "
                     + ", ".join(f"`{g['label']}`" for g in comb["undocumented_god_nodes"][:10]))
        if comb["dark_subsystems"]:
            d = comb["dark_subsystems"][0]
            L.append(f"- **Darkest subsystem:** community {d['community']} ({d['coverage']:.0%} documented)")
    else:
        L.append("- _no semantic overlay yet — run `semantic-prep` → `semantic-merge` to unlock "
                 "doc-coverage insights_")
    L.append("")

    # ⚠️ Risk queue
    if comb.get("available") and comb.get("risk_queue"):
        L += ["## ⚠️ Undocumented load-bearing — document these first", "",
              "<details><summary>Top risk = centrality × (1 − documented)</summary>", ""]
        L += [f"{i + 1}. `{q['label']}` — `{q['source_file']}`"
              for i, q in enumerate(comb["risk_queue"][:10])]
        L += ["", "</details>", ""]

    L += _glossary() + [""]

    L += ["---", "",
          "_Generated by [cg-graphify-bridge](https://github.com/evannordinpro/cg-graphify-bridge) "
          "from the committed knowledge graph (`graphify-out/`). Health metrics are production-scoped; "
          "see `docs/setup.md` → Health & benchmarks. Versioned per build via CI (content-deterministic)._"]
    return "\n".join(L) + "\n"
