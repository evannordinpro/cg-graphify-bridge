"""Phase 2 (2b) — `health`: structural + semantic + COMBINED codebase-health metrics over the
committed graph, each paired with the action it implies. Reads committed layers only (offline, no
rebuild). Emits a structured dict (`--json`) and a markdown report. Advisory — never gates.

The combined section is the differentiator: "are we documenting what structurally matters" —
god-node / centrality-weighted doc coverage + the undocumented-load-bearing risk queue.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from . import analytics, driver

# Test/non-production node detection — health is about PRODUCTION code, so by default test files are
# excluded uniformly from every metric (codegraph indexes the whole repo, incl. tests/). P2-OBS1.
_TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs", "e2e"}


def _is_test_node(node: dict) -> bool:
    sf = (node.get("source_file") or "").replace("\\", "/")
    parts = sf.split("/")
    if any(p in _TEST_DIRS for p in parts):
        return True
    base = parts[-1] if parts else ""
    if base.startswith("test_") or re.search(r"(_test|\.test|\.spec)\.[A-Za-z0-9]+$", base):
        return True
    return (node.get("label") or "").startswith("test_")


def source_scope(structural: dict) -> dict:
    """Return a copy of `structural` with test/non-production nodes (and edges/communities/god_nodes
    referencing them) removed — so coverage denominators, centrality, cycles, and the risk queue all
    reflect production code consistently."""
    keep = {n["id"] for n in structural.get("nodes", []) if not _is_test_node(n)}
    comms = {c: [m for m in ms if m in keep] for c, ms in structural.get("communities", {}).items()}
    return {**structural,
            "nodes": [n for n in structural.get("nodes", []) if n["id"] in keep],
            "edges": [e for e in structural.get("edges", [])
                      if e.get("source") in keep and e.get("target") in keep],
            "communities": {c: ms for c, ms in comms.items() if ms},
            "god_nodes": [g for g in structural.get("god_nodes", []) if g["id"] in keep]}


def _code_nodes(structural: dict) -> list:
    return [n for n in structural.get("nodes", [])
            if n.get("file_type") == "code"
            and n.get("metadata", {}).get("cg_kind") not in ("file", "import", "module")]


def _documented_targets(semantic: dict | None) -> set:
    if not semantic:
        return set()
    return {e["target"] for e in semantic.get("semantic_edges", []) if e.get("target")}


def semantic_health(structural: dict, semantic: dict | None) -> dict:
    """Doc coverage (overall / by-kind / public-API via is_exported) + dangling/orphan drift."""
    code = _code_nodes(structural)
    code_ids = {n["id"] for n in code}
    if not semantic:
        return {"available": False, "note": "no semantic.json — run semantic-prep/merge to build the overlay"}
    documented = _documented_targets(semantic) & code_ids
    kc = defaultdict(lambda: [0, 0])
    for n in code:
        k = n["metadata"].get("cg_kind", "?")
        kc[k][1] += 1
        if n["id"] in documented:
            kc[k][0] += 1
    public = [n for n in code if n["metadata"].get("is_exported")]
    has_export_stamp = any("is_exported" in n["metadata"] for n in code)
    all_ids = {n["id"] for n in structural.get("nodes", [])}
    dangling = sorted(({"source": e["source"], "target": e["target"]}
                       for e in semantic.get("semantic_edges", [])
                       if e.get("target") and e["target"] not in all_ids),
                      key=lambda d: (d["source"], d["target"]))
    doc_srcs = {e["source"] for e in semantic.get("semantic_edges", [])}
    orphans = sorted(n["id"] for n in semantic.get("semantic_nodes", []) if n["id"] not in doc_srcs)
    return {
        "available": True,
        "coverage_overall": round(len(documented) / len(code), 4) if code else 0.0,
        "documented_count": len(documented), "code_count": len(code),
        "by_kind": {k: {"documented": d, "total": t, "coverage": round(d / t, 4)}
                    for k, (d, t) in sorted(kc.items())},
        "public_api_coverage": (round(sum(n["id"] in documented for n in public) / len(public), 4)
                                if public else None),
        "public_api_caveat": (None if has_export_stamp else
                              "no is_exported stamp (legacy graph) — rebuild for public-API coverage"),
        "dangling_links": dangling, "orphan_docs": orphans,
    }


def combined_health(structural: dict, semantic: dict | None, cent: dict) -> dict:
    """The cross-layer metrics: god-node + centrality-weighted coverage, dark subsystems, and the
    undocumented-load-bearing risk queue = centrality × (1 − documented)."""
    code = _code_nodes(structural)
    code_ids = {n["id"] for n in code}
    if not semantic:
        return {"available": False}
    documented = _documented_targets(semantic) & code_ids
    pr = {nid: cent.get(nid, {}).get("pagerank", 0.0) for nid in code_ids}
    tot = sum(pr.values()) or 1.0
    wcov = round(sum(pr[n] for n in documented) / tot, 4)
    gods = structural.get("god_nodes", [])
    god_undoc = [{"id": g["id"], "label": g.get("label", g["id"])}
                 for g in gods if g["id"] not in documented]
    dark = []
    for cid, members in structural.get("communities", {}).items():
        mem = [m for m in members if m in code_ids]
        if not mem:
            continue
        cov = sum(m in documented for m in mem) / len(mem)
        mass = sum(pr.get(m, 0.0) for m in mem)
        dark.append({"community": cid, "coverage": round(cov, 4), "centrality_mass": round(mass, 6),
                     "darkness": round(mass * (1 - cov), 6), "size": len(mem)})
    dark.sort(key=lambda d: (-d["darkness"], d["community"]))
    maxpr = max(pr.values()) if pr else 1.0
    risk = [{"id": n["id"], "label": n.get("label", n["id"]), "source_file": n.get("source_file"),
             "pagerank": cent.get(n["id"], {}).get("pagerank", 0.0),
             "betweenness": cent.get(n["id"], {}).get("betweenness", 0.0),
             "risk": round((cent.get(n["id"], {}).get("pagerank", 0.0) / maxpr) if maxpr else 0.0, 6)}
            for n in code if n["id"] not in documented]
    risk.sort(key=lambda r: (-r["risk"], -r["betweenness"], r["id"]))
    return {
        "available": True,
        "god_node_coverage": (round((len(gods) - len(god_undoc)) / len(gods), 4) if gods else None),
        "undocumented_god_nodes": god_undoc,
        "centrality_weighted_coverage": wcov,
        "dark_subsystems": dark[:10],
        "risk_queue": risk[:15],
    }


def knowledge_debt(sem: dict, comb: dict) -> dict | None:
    """Roll-up index — always emitted WITH its components (never an opaque single number)."""
    if not sem.get("available"):
        return None
    missing = round(1 - comb.get("centrality_weighted_coverage", 0.0), 4)
    dangling, orphans = len(sem["dangling_links"]), len(sem["orphan_docs"])
    return {"missing_weighted_coverage": missing, "dangling_links": dangling, "orphan_docs": orphans,
            "index": round(0.6 * missing + 0.2 * min(1, dangling / 10) + 0.2 * min(1, orphans / 10), 4)}


def health(out: Path, *, include_tests: bool = False) -> dict:
    """Full health pass over the committed layers in `out`. Production-scoped by default
    (test files excluded uniformly from every metric); pass include_tests=True for the whole graph."""
    structural = driver.read_layer(out, "structural")
    if structural is None:
        raise SystemExit(f"no structural.json in {out} — build the graph first (or pull it)")
    semantic = driver.read_layer(out, "semantic")
    scoped = structural if include_tests else source_scope(structural)
    sm = analytics.analyze(scoped)                # one centrality compute, reused below
    cent = sm["centrality"]
    sem = semantic_health(scoped, semantic)
    comb = combined_health(scoped, semantic, cent)
    return {
        "out_dir": str(out),
        "scope": "all (incl. tests)" if include_tests else "source-only (tests excluded)",
        "structural": {
            "cycles": sm["cycles"],
            "leaky_communities": sm["conductance"][:5],
            "god_objects": sorted(
                ({"id": k, "betweenness": v["betweenness"], "degree": v["degree"]}
                 for k, v in cent.items()),
                key=lambda d: (-d["betweenness"], -d["degree"], d["id"]))[:10],
            "coupling": sm["coupling"]["communities"],
            "instability_inversions": sm["coupling"]["inversions"][:10],
            "abstractness": sm["abstractness"],
            "fan": sm["fan"],
            "dead_code": {"count": len(sm["dead_code"]), "top": sm["dead_code"][:15],
                          "note": "static review queue — over-flags dynamic/reflection/framework-wired symbols"},
        },
        "semantic": sem,
        "combined": comb,
        "knowledge_debt": knowledge_debt(sem, comb),
    }


def render_report(r: dict) -> str:
    """Human-readable markdown (matches the GRAPH_REPORT.md convention)."""
    L = ["# Codebase Health Report", "",
         f"_Advisory metrics over the committed graph — scope: **{r.get('scope', 'source-only')}**. "
         "Structural = architecture; semantic = where knowledge lives; combined = documenting what matters._", ""]
    s = r["structural"]
    L += ["## Structural", ""]
    mc = s["cycles"]["module_cycles"]
    L.append(f"- **Dependency cycles (file-level):** {len(mc)}" +
             (f" — worst: {mc[0]['members']} (cut `{mc[0]['suggested_cut']['from']}`→"
              f"`{mc[0]['suggested_cut']['to']}`)" if mc else " — none (acyclic ✓)"))
    if s["leaky_communities"]:
        lk = s["leaky_communities"][0]
        L.append(f"- **Leakiest community:** {lk['community']} (conductance {lk['conductance']})")
    if s["god_objects"]:
        g = s["god_objects"][0]
        L.append(f"- **Top architectural hub (betweenness):** `{g['id']}` ({g['betweenness']})")
    ab = s["abstractness"]
    pain = [c for c in ab["communities"] if c["zone"] == "pain"]
    useless = [c for c in ab["communities"] if c["zone"] == "uselessness"]
    L.append(f"- **Zone of Pain:** {len(pain)} communities · **Zone of Uselessness:** {len(useless)}"
             + (f"  _(caveat: {ab['caveat']})_" if ab["caveat"] else ""))
    L.append(f"- **High fan-out (SRP) candidates:** {len(s['fan'].get('high_fan_out', []))}")
    L.append(f"- **Dead-code review queue:** {s['dead_code']['count']} "
             f"_(static — {s['dead_code']['note'].split('—')[1].strip()})_")
    sem = r["semantic"]
    L += ["", "## Semantic", ""]
    if not sem.get("available"):
        L.append(f"- {sem.get('note', 'no overlay')}")
    else:
        L.append(f"- **Doc coverage:** {sem['coverage_overall']:.0%} "
                 f"({sem['documented_count']}/{sem['code_count']} symbols)")
        if sem["public_api_coverage"] is not None:
            L.append(f"- **Public-API coverage:** {sem['public_api_coverage']:.0%}")
        elif sem["public_api_caveat"]:
            L.append(f"- **Public-API coverage:** n/a — {sem['public_api_caveat']}")
        L.append(f"- **Dangling doc links:** {len(sem['dangling_links'])} · "
                 f"**Orphan docs:** {len(sem['orphan_docs'])}")
    comb = r["combined"]
    L += ["", "## Combined (documenting what matters)", ""]
    if not comb.get("available"):
        L.append("- no semantic overlay — combined metrics unavailable")
    else:
        gr = comb["god_node_coverage"]
        L.append(f"- **God-node doc coverage:** {gr:.0%}" if gr is not None else "- no god nodes")
        if comb["undocumented_god_nodes"]:
            L.append(f"  - undocumented hubs: " +
                     ", ".join(f"`{g['label']}`" for g in comb["undocumented_god_nodes"][:8]))
        L.append(f"- **Centrality-weighted coverage:** {comb['centrality_weighted_coverage']:.0%} "
                 f"_(gap vs raw = mis-targeted doc effort)_")
        if comb["dark_subsystems"]:
            d = comb["dark_subsystems"][0]
            L.append(f"- **Darkest subsystem:** {d['community']} (coverage {d['coverage']:.0%}, "
                     f"centrality mass {d['centrality_mass']})")
        if comb["risk_queue"]:
            L += ["", "### Undocumented-load-bearing risk queue (do these first)", ""]
            L += [f"{i + 1}. `{q['label']}` — {q['source_file']} "
                  f"(pagerank {q['pagerank']}, betweenness {q['betweenness']})"
                  for i, q in enumerate(comb["risk_queue"][:10])]
    kd = r.get("knowledge_debt")
    if kd:
        L += ["", "## Knowledge debt", "",
              f"- index **{kd['index']}** = missing-weighted-coverage {kd['missing_weighted_coverage']} "
              f"· dangling {kd['dangling_links']} · orphans {kd['orphan_docs']}"]
    return "\n".join(L) + "\n"
