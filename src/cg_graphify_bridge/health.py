"""Phase 2 (2b) — `health`: structural + semantic + COMBINED codebase-health metrics over the
committed graph, each paired with the action it implies. Reads committed layers (offline, no
rebuild) plus — when a repo path is given — a textual scan of the indexed sources that rescues
dynamically-wired symbols from the dead-code queue. Emits a structured dict (`--json`) and a
markdown report. Advisory — never gates.

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


def dynamic_refs(repo: Path, structural: dict, candidates: list) -> dict:
    """Rescue dynamically-wired symbols from the dead-code queue via a textual source scan.

    A symbol dispatched dynamically produces no call edge — argparse `set_defaults(func=handler)`,
    callback/registry tables, `getattr`-by-name strings, constants read as bare identifiers — which
    is exactly the false-positive class the dead-code note warns about. Evidence = the symbol's
    name occurring in any indexed source file as a VALUE: not followed by `(` (a call — the graph's
    job), not an assignment to it, not its own def/class line, not an import line. Textual on
    purpose: a quoted name (getattr dispatch) or a mention in a comment counts — the queue is a
    review list, not a gate, and should err toward fewer false positives.

    Returns {node_id: "file:line" of the first evidence}; scan order is sorted, so deterministic
    for a fixed working tree. Single-character names are skipped (they collide with everything).
    """
    texts = []
    for sf in sorted({n.get("source_file") for n in structural.get("nodes", []) if n.get("source_file")}):
        try:
            texts.append((sf, (repo / sf).read_text(errors="replace").splitlines()))
        except OSError:
            continue
    _import_line = re.compile(r"^\s*(?:from\s+\S+\s+)?import\s")
    hits: dict = {}
    for c in sorted(candidates, key=lambda d: d["id"]):
        name = c.get("label") or ""
        if len(name) < 2:
            continue
        esc = re.escape(name)
        ref = re.compile(rf"\b{esc}\b(?!\s*\()(?!\s*=[^=])")
        defline = re.compile(rf"^\s*(?:async\s+def|def|class)\s+{esc}\b")
        for sf, lines in texts:
            for i, line in enumerate(lines, 1):
                if defline.match(line) or _import_line.match(line):
                    continue
                if ref.search(line):
                    hits[c["id"]] = f"{sf}:{i}"
                    break
            if c["id"] in hits:
                break
    return hits


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


# Per-type debt weights + saturation constants for the transparent 0–1 score (documented here so
# the number is never opaque). Saturation: count/(count+SAT) — a few cycles already hurt (low SAT);
# dead-code needs many to matter (high SAT).
_DEBT_WEIGHTS = {"cycle": 0.30, "zone-of-pain": 0.20, "god-object": 0.15,
                 "high-fan-out": 0.15, "dead-code": 0.10, "dangling-link": 0.10}
_DEBT_SAT = {"cycle": 2, "zone-of-pain": 3, "god-object": 3,
             "high-fan-out": 5, "dead-code": 25, "dangling-link": 3}


def debt_assessment(structural: dict, sm: dict, sem: dict) -> dict:
    """Aggregate the EXISTING debt signals (cycles, Zone-of-Pain, high-fan-out, god-objects,
    dead-code, dangling doc-links) into ranked breakdowns by TYPE / FEATURE (community) /
    COMPONENT (file) + a transparent 0–1 score (per-type contributions shown). Composition only —
    no new metric logic. Phase-6 FAQ reuses the by-feature / by-component rollups."""
    import statistics
    from collections import Counter

    meta = {n["id"]: n for n in structural.get("nodes", [])}
    comm_of = {m: cid for cid, members in structural.get("communities", {}).items() for m in members}
    items: list[dict] = []

    def _add(t, label, *, nid=None, community=None, file=None):
        items.append({"type": t, "label": label, "id": nid, "community": community, "file": file})

    for c in sm["cycles"]["module_cycles"]:
        _add("cycle", " ↔ ".join(c["members"][:3]), file=(c["members"][0] if c["members"] else None))
    for c in sm["abstractness"]["communities"]:
        if c["zone"] == "pain":
            _add("zone-of-pain", f"community {c['community']}", community=c["community"])
    for h in sm["fan"].get("high_fan_out", []):
        _add("high-fan-out", h.get("label", h["id"]), nid=h["id"],
             community=comm_of.get(h["id"]), file=h.get("source_file"))
    cent = sm["centrality"]
    btws = [v["betweenness"] for v in cent.values()]
    if btws:
        thr = statistics.fmean(btws) + 2 * (statistics.pstdev(btws) if len(btws) > 1 else 0.0)
        for nid, v in cent.items():
            if v["betweenness"] > thr and v["betweenness"] > 0:
                n = meta.get(nid, {})
                _add("god-object", n.get("label", nid), nid=nid,
                     community=comm_of.get(nid), file=n.get("source_file"))
    for d in sm["dead_code"]:
        _add("dead-code", d.get("label", d["id"]), nid=d["id"],
             community=comm_of.get(d["id"]), file=d.get("source_file"))
    if sem.get("available"):
        for dl in sem["dangling_links"]:
            _add("dangling-link", f"{dl['source']} → {dl['target']}")

    items.sort(key=lambda i: (i["type"], i.get("file") or "", i.get("id") or i.get("label") or ""))
    by_type = dict(sorted(Counter(i["type"] for i in items).items()))
    feat = Counter(i["community"] for i in items if i.get("community"))
    comp = Counter(i["file"] for i in items if i.get("file"))
    by_feature = sorted(({"feature": k, "debt_items": v} for k, v in feat.items()),
                        key=lambda x: (-x["debt_items"], str(x["feature"])))
    by_component = sorted(({"component": k, "debt_items": v} for k, v in comp.items()),
                          key=lambda x: (-x["debt_items"], x["component"]))
    contrib = {t: round(_DEBT_WEIGHTS[t] * (by_type.get(t, 0) / (by_type.get(t, 0) + _DEBT_SAT[t])), 4)
               for t in _DEBT_WEIGHTS}
    return {"score": round(min(1.0, sum(contrib.values())), 4), "score_components": contrib,
            "by_type": by_type, "by_feature": by_feature[:10], "by_component": by_component[:10],
            "total_items": len(items), "items": items}


def health(out: Path, *, include_tests: bool = False, repo: Path | None = None) -> dict:
    """Full health pass over the committed layers in `out`. Production-scoped by default
    (test files excluded uniformly from every metric); pass include_tests=True for the whole graph.
    With `repo`, dead-code candidates with textual value references in the indexed sources
    (argparse/callback/getattr wiring) are excluded as dynamically wired — see dynamic_refs()."""
    structural = driver.read_layer(out, "structural")
    if structural is None:
        raise SystemExit(f"no structural.json in {out} — build the graph first (or pull it)")
    semantic = driver.read_layer(out, "semantic")
    scoped = structural if include_tests else source_scope(structural)
    sm = analytics.analyze(scoped)                # one centrality compute, reused below
    dyn = dynamic_refs(repo, scoped, sm["dead_code"]) if repo else {}
    dyn_wired = sorted(({"id": d["id"], "label": d.get("label", d["id"]), "evidence": dyn[d["id"]]}
                        for d in sm["dead_code"] if d["id"] in dyn), key=lambda x: x["id"])
    if dyn:        # debt_assessment reads sm["dead_code"], so the score sees the filtered queue too
        sm["dead_code"] = [d for d in sm["dead_code"] if d["id"] not in dyn]
    cent = sm["centrality"]
    sem = semantic_health(scoped, semantic)
    comb = combined_health(scoped, semantic, cent)
    debt = debt_assessment(scoped, sm, sem)
    return {
        "out_dir": str(out),
        "scope": "all (incl. tests)" if include_tests else "source-only (tests excluded)",
        "debt": debt,
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
                          "dynamically_wired_excluded": len(dyn_wired),
                          "dynamically_wired": dyn_wired[:10],
                          "note": "static review queue — over-flags dynamic/reflection/framework-wired symbols"
                          + (f"; {len(dyn_wired)} dropped via textual value-reference evidence"
                             if dyn_wired else
                             ("" if repo else "; pass the repo path to drop dynamically-wired symbols"))},
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
