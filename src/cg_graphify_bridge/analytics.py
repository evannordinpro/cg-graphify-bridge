"""Phase 2 (2a) — structural graph analytics over the COMMITTED structural.json.

Pure, deterministic, offline: reads the committed layer only (never codegraph / never rebuilds),
so it runs anywhere the graph is checked in. The shared spine for `health`, `benchmark`, and a
future impact/callers surface. Granularity discipline (research §cross-cutting): centrality + SCC
at the SYMBOL level; conductance / coupling / abstractness at the COMMUNITY level.

networkx (already a pinned dep) provides the primitives. All outputs are sorted for determinism.
"""
from __future__ import annotations

import statistics
from collections import Counter

# Edge relations that are NESTING, not dependencies — excluded from the dependency graph
# (mirrors driver.degree_graph's analysis-view semantics).
_CONTAINMENT = {"contains"}
# OO "type" kinds for Martin's Abstractness (A is defined over types, not functions/vars).
_TYPE_KINDS = {"class", "interface", "struct", "enum", "protocol"}


def _meta(structural: dict) -> dict:
    """node id -> node dict, for metadata lookups."""
    return {n["id"]: n for n in structural.get("nodes", [])}


def build_digraph(structural: dict):
    """Directed DEPENDENCY graph (calls/imports/references; `contains` excluded). Weighted."""
    import networkx as nx
    dg = nx.DiGraph()
    dg.add_nodes_from(n["id"] for n in structural.get("nodes", []))
    for e in structural.get("edges", []):
        if e.get("relation") in _CONTAINMENT:
            continue
        if e["source"] == e["target"]:
            continue  # self-loop: meaningless for these metrics
        w = e.get("weight", 1.0) or 1.0
        if dg.has_edge(e["source"], e["target"]):
            dg[e["source"]][e["target"]]["weight"] += w
        else:
            dg.add_edge(e["source"], e["target"], weight=w)
    return dg


def centrality(structural: dict) -> dict:
    """Per-node {degree, in, out, betweenness, pagerank}. Betweenness on the undirected view
    (architectural bottleneck); PageRank on the dependency graph itself — our edges are
    source-depends-on-target, so depended-upon foundations carry the in-edges PageRank rewards.
    Both deterministic."""
    import networkx as nx
    dg = build_digraph(structural)
    ug = dg.to_undirected()
    btw = nx.betweenness_centrality(ug) if ug.number_of_nodes() > 2 else {n: 0.0 for n in ug}
    try:
        pr = nx.pagerank(dg) if dg.number_of_edges() else {n: 0.0 for n in dg}
    except nx.PowerIterationFailedConvergence:
        pr = {n: 0.0 for n in dg}
    out = {}
    for n in dg.nodes():
        out[n] = {"degree": dg.in_degree(n) + dg.out_degree(n),
                  "in": dg.in_degree(n), "out": dg.out_degree(n),
                  "betweenness": round(btw.get(n, 0.0), 6), "pagerank": round(pr.get(n, 0.0), 6)}
    return out


def cycles(structural: dict) -> dict:
    """Dependency cycles via SCC (Tarjan). symbol_cycles = mutually-recursive symbol sets;
    module_cycles = SCCs of the FILE condensation graph (the real smell — Acyclic Dependencies
    Principle). Each module cycle reports a suggested cut = its lowest-weight cross-file edge."""
    import networkx as nx
    dg = build_digraph(structural)
    meta = _meta(structural)
    symbol_cycles = sorted(
        ([*sorted(s)] for s in nx.strongly_connected_components(dg) if len(s) > 1),
        key=lambda s: (-len(s), s))
    # File-level condensation.
    fg = nx.DiGraph()
    for u, v, d in dg.edges(data=True):
        fu = (meta.get(u, {}).get("source_file") or u)
        fv = (meta.get(v, {}).get("source_file") or v)
        if fu == fv:
            continue
        w = d.get("weight", 1.0)
        if fg.has_edge(fu, fv):
            fg[fu][fv]["weight"] += w
        else:
            fg.add_edge(fu, fv, weight=w)
    module_cycles = []
    for scc in nx.strongly_connected_components(fg):
        if len(scc) < 2:
            continue
        members = sorted(scc)
        internal = [(u, v, fg[u][v]["weight"]) for u in scc for v in fg.successors(u) if v in scc]
        cut = min(internal, key=lambda t: (t[2], t[0], t[1])) if internal else None
        module_cycles.append({
            "members": members, "size": len(members),
            "internal_edges": len(internal),
            "suggested_cut": ({"from": cut[0], "to": cut[1], "weight": cut[2]} if cut else None)})
    module_cycles.sort(key=lambda c: (-c["size"], c["members"]))
    return {"symbol_cycles": symbol_cycles, "module_cycles": module_cycles}


def conductance(structural: dict) -> list:
    """Per-community conductance φ(S)=cut(S)/min(vol S, vol V\\S) on the undirected dependency
    graph — the boundary coupling-vs-cohesion ratio. High = a leaky module. Sorted worst-first."""
    import networkx as nx
    from networkx.algorithms.cuts import conductance as nx_conductance
    ug = build_digraph(structural).to_undirected()
    rows = []
    for cid, members in structural.get("communities", {}).items():
        s = {m for m in members if m in ug}
        if not s or len(s) == ug.number_of_nodes():
            continue
        try:
            phi = nx_conductance(ug, s)
        except (ZeroDivisionError, nx.NetworkXError):
            continue
        rows.append({"community": cid, "conductance": round(phi, 4), "size": len(s)})
    rows.sort(key=lambda r: (-r["conductance"], r["community"]))
    return rows


def coupling_instability(structural: dict) -> dict:
    """Per-community Martin coupling: Ca (incoming external deps), Ce (outgoing external deps),
    Instability I = Ce/(Ca+Ce). Also flags Stable-Dependencies-Principle inversions (a more
    stable community depending on a less stable one)."""
    dg = build_digraph(structural)
    comm_of = {}
    for cid, members in structural.get("communities", {}).items():
        for m in members:
            comm_of[m] = cid
    ca = Counter()
    ce = Counter()
    cross = Counter()  # (src_comm, dst_comm) -> weight, for inversion detection
    for u, v in dg.edges():
        cu, cv = comm_of.get(u), comm_of.get(v)
        if cu is None or cv is None or cu == cv:
            continue
        ce[cu] += 1   # u's community depends outward
        ca[cv] += 1   # v's community is depended upon
        cross[(cu, cv)] += 1
    rows = []
    inst = {}
    for cid in structural.get("communities", {}):
        a, e = ca[cid], ce[cid]
        i = round(e / (a + e), 4) if (a + e) else 0.0
        inst[cid] = i
        rows.append({"community": cid, "ca": a, "ce": e, "instability": i})
    rows.sort(key=lambda r: r["community"])
    inversions = sorted(
        ({"from": cu, "to": cv, "i_from": inst.get(cu, 0.0), "i_to": inst.get(cv, 0.0)}
         for (cu, cv) in cross if inst.get(cu, 0.0) < inst.get(cv, 0.0)),
        key=lambda d: (d["i_to"] - d["i_from"]), reverse=True)
    # KD1 (Phase 6): the cross-community nearest-neighbor map — who depends on whom, weighted.
    neighbors = sorted(({"from": cu, "to": cv, "weight": w} for (cu, cv), w in cross.items()),
                       key=lambda d: (-d["weight"], d["from"], d["to"]))
    return {"communities": rows, "inversions": inversions, "instability": inst,
            "neighbors": neighbors}


def _is_abstract_type(n: dict) -> bool:
    md = n.get("metadata", {})
    return bool(md.get("is_abstract")) or md.get("cg_kind") == "interface"


def abstractness_distance(structural: dict) -> dict:
    """Per-community Abstractness A=abstract types/total types, Distance from main sequence
    D=|A+I-1|, and the Zone classification (research §1.7). Needs the is_abstract stamp (FR0);
    reports the fraction of type-nodes lacking the stamp as an honesty caveat."""
    coup = coupling_instability(structural)["instability"]
    meta = _meta(structural)
    stamped = unstamped = 0
    rows = []
    for cid, members in structural.get("communities", {}).items():
        types = [meta[m] for m in members if m in meta
                 and meta[m].get("metadata", {}).get("cg_kind") in _TYPE_KINDS]
        if not types:
            continue
        for t in types:
            if "is_abstract" in t.get("metadata", {}):
                stamped += 1
            else:
                unstamped += 1
        a = round(sum(_is_abstract_type(t) for t in types) / len(types), 4)
        i = coup.get(cid, 0.0)
        d = round(abs(a + i - 1), 4)
        zone = ("pain" if i < 0.3 and a < 0.3 else
                "uselessness" if i > 0.7 and a > 0.7 else "main-sequence")
        action = ("extract an interface (unstable concrete hub)" if i > 0.8 and a < 0.2 else
                  "depend on abstractions, not the concrete core" if zone == "pain" else
                  "delete/inline the unused abstraction" if zone == "uselessness" else None)
        rows.append({"community": cid, "abstractness": a, "instability": i, "distance": d,
                     "types": len(types), "zone": zone, "action": action})
    rows.sort(key=lambda r: (-r["distance"], r["community"]))
    total = stamped + unstamped
    caveat = (None if not unstamped else
              f"{unstamped}/{total} type-nodes lack the is_abstract stamp (legacy graph — rebuild "
              f"with the current tool); treated as concrete.")
    return {"communities": rows, "abstractness_coverage": round(stamped / total, 4) if total else 1.0,
            "caveat": caveat}


def fan_distribution(structural: dict) -> dict:
    """In/out-degree distribution over the dependency graph + high-fan-out refactor candidates
    (fan-out smell ≈ 7±2 cognitive-load cap, combined with a distributional outlier test)."""
    dg = build_digraph(structural)
    meta = _meta(structural)
    outs = [d for _, d in dg.out_degree()]
    if not outs:
        return {"fan_out": {}, "high_fan_out": []}
    mean = statistics.fmean(outs)
    std = statistics.pstdev(outs) if len(outs) > 1 else 0.0
    threshold = max(7, round(mean + 2 * std))

    def pct(p):
        return sorted(outs)[min(len(outs) - 1, int(round(p * (len(outs) - 1))))]
    high = sorted(
        ({"id": n, "label": meta.get(n, {}).get("label", n),
          "source_file": meta.get(n, {}).get("source_file"), "fan_out": d}
         for n, d in dg.out_degree() if d > threshold),
        key=lambda x: (-x["fan_out"], x["id"]))
    ins = [d for _, d in dg.in_degree()]
    return {"fan_out": {"median": pct(0.5), "p90": pct(0.9), "p99": pct(0.99), "max": max(outs),
                        "mean": round(mean, 2), "threshold": threshold},
            "fan_in": {"median": (sorted(ins)[len(ins) // 2] if ins else 0), "max": (max(ins) if ins else 0)},
            "high_fan_out": high}


def _is_entrypoint(n: dict) -> bool:
    """Heuristic exclusions for dead-code (avoid false positives): files/imports/modules, exported
    public API, dunders/main, and anything under a tests/ path."""
    md = n.get("metadata", {})
    name = n.get("label") or ""
    sf = (n.get("source_file") or "")
    if md.get("cg_kind") in ("file", "import", "module"):
        return True
    if md.get("is_exported"):
        return True
    if name in ("main", "__init__", "__main__") or (name.startswith("__") and name.endswith("__")):
        return True
    if name.startswith("test_") or "tests/" in sf or sf.startswith("test") or "/test" in sf:
        return True
    return False


def dead_code(structural: dict) -> list:
    """Zero-in-degree code symbols that aren't entrypoints — a REVIEW QUEUE (never auto-delete;
    reflection/DI/external-API over-flag statically)."""
    dg = build_digraph(structural)
    meta = _meta(structural)
    out = []
    for n in dg.nodes():
        nd = meta.get(n)
        if not nd or nd.get("metadata", {}).get("cg_kind") in ("file", "import", "module"):
            continue
        if dg.in_degree(n) == 0 and not _is_entrypoint(nd):
            out.append({"id": n, "label": nd.get("label", n),
                        "source_file": nd.get("source_file"),
                        "cg_kind": nd.get("metadata", {}).get("cg_kind")})
    out.sort(key=lambda x: (x.get("source_file") or "", x["id"]))
    return out


def analyze(structural: dict) -> dict:
    """Orchestrate the full structural-analytics pass (one graph build, all metrics)."""
    return {
        "centrality": centrality(structural),
        "cycles": cycles(structural),
        "conductance": conductance(structural),
        "coupling": coupling_instability(structural),
        "abstractness": abstractness_distance(structural),
        "fan": fan_distribution(structural),
        "dead_code": dead_code(structural),
    }
