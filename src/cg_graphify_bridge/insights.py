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
           "    quadrant-1 Zone of Uselessness",
           "    quadrant-2 Ideal (abstract + stable)",
           "    quadrant-3 Zone of Pain",
           "    quadrant-4 Volatile leaf (ok)"]
    for c in pts:
        label = (re.sub(r"[^A-Za-z0-9 ]", "", f"c{c['community']}")[:18]) or "c"
        out.append(f'    "{label}": [{c["instability"]:.3f}, {c["abstractness"]:.3f}]')
    out.append("```")
    return out


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

    L += ["---", "",
          "_Generated by [cg-graphify-bridge](https://github.com/evannordinpro/cg-graphify-bridge) "
          "from the committed knowledge graph (`graphify-out/`). Health metrics are production-scoped; "
          "see `docs/setup.md` → Health & benchmarks. Versioned per build via CI (content-deterministic)._"]
    return "\n".join(L) + "\n"
