"""Phase 3 — navigation over the COMMITTED graph: callers / callees / impact.

Re-implements codegraph's query capability over the bridge's committed structural.json (codegraph's
own query is locked to the live .codegraph db). Reuses analytics.build_digraph (one graph builder):
edge source→target = "source depends on target", so callers(X)=predecessors, callees(X)=successors,
and impact(X)=transitive dependents (the blast radius if X changes). Offline, deterministic.
"""
from __future__ import annotations

from collections import defaultdict

from . import analytics


def resolve(structural: dict, name: str) -> list:
    """Human-typed name → node(s). Precedence: exact label → exact qualified_name → suffix match.
    Returns ALL matches at the first tier that hits (ambiguity is surfaced, never silently picked)."""
    nodes = structural.get("nodes", [])

    def srt(seq):
        return sorted(seq, key=lambda n: n["id"])
    exact_label = [n for n in nodes if n.get("label") == name]
    if exact_label:
        return srt(exact_label)
    exact_qn = [n for n in nodes if n.get("metadata", {}).get("qualified_name") == name]
    if exact_qn:
        return srt(exact_qn)
    suffix = [n for n in nodes
              if (n.get("metadata", {}).get("qualified_name") or "").endswith(name)
              or (n.get("label") or "").endswith(name)]
    return srt(suffix)


def _relation_map(structural: dict) -> dict:
    """(source, target) -> sorted dependency relations (for annotating direct hits)."""
    m = defaultdict(set)
    for e in structural.get("edges", []):
        if e.get("relation") == "contains" or e["source"] == e["target"]:
            continue
        m[(e["source"], e["target"])].add(e.get("relation", "references"))
    return {k: sorted(v) for k, v in m.items()}


def _layered(dg, start, neighbors, depth):
    """BFS from `start` over `neighbors` (dg.predecessors / dg.successors), returning {node: hop}."""
    seen = {start}
    frontier = [start]
    layers: dict = {}
    hop = 0
    while frontier and (depth is None or hop < depth):
        hop += 1
        nxt = []
        for n in frontier:
            for m in neighbors(n):
                if m not in seen:
                    seen.add(m)
                    layers[m] = hop
                    nxt.append(m)
        frontier = nxt
    return layers


def _traverse(structural: dict, name: str, *, direction: str, depth) -> dict:
    matches = resolve(structural, name)
    if len(matches) != 1:
        return {"symbol": name, "kind": direction, "resolved": None,
                "candidates": [{"id": n["id"], "label": n.get("label"),
                                "source_file": n.get("source_file")} for n in matches],
                "results": [], "by_hop": {}, "count": 0}
    node = matches[0]
    nid = node["id"]
    dg = analytics.build_digraph(structural)
    meta = {n["id"]: n for n in structural.get("nodes", [])}
    rels = _relation_map(structural)
    layers = _layered(dg, nid, dg.predecessors if direction == "callers" else dg.successors, depth) \
        if nid in dg else {}
    results = []
    for mid, hop in sorted(layers.items(), key=lambda kv: (kv[1], kv[0])):
        m = meta.get(mid, {})
        item = {"id": mid, "label": m.get("label", mid),
                "source_file": m.get("source_file"), "hop": hop}
        if hop == 1:
            pair = (mid, nid) if direction == "callers" else (nid, mid)
            item["relation"] = rels.get(pair)
        results.append(item)
    by_hop: dict = defaultdict(int)
    for r in results:
        by_hop[r["hop"]] += 1
    return {"symbol": name, "kind": direction, "resolved": nid, "label": node.get("label"),
            "source_file": node.get("source_file"), "candidates": [],
            "results": results, "by_hop": dict(sorted(by_hop.items())), "count": len(results)}


def callers(structural: dict, name: str, depth: int = 1) -> dict:
    """Symbols that depend on `name` (predecessors), to `depth` hops."""
    return _traverse(structural, name, direction="callers", depth=depth)


def callees(structural: dict, name: str, depth: int = 1) -> dict:
    """Symbols that `name` depends on (successors), to `depth` hops."""
    return _traverse(structural, name, direction="callees", depth=depth)


def impact(structural: dict, name: str, depth=None) -> dict:
    """Blast radius — transitive dependents of `name` (unbounded by default). impact(depth=1) is
    exactly the direct callers."""
    r = _traverse(structural, name, direction="callers", depth=depth)
    r["kind"] = "impact"
    return r


def render(res: dict) -> str:
    """Markdown for the query result."""
    head = res.get("label") or res["symbol"]
    L = [f"# {res['kind']}: {head}", ""]
    if res["resolved"] is None and not res["candidates"]:
        return f"# {res['kind']}: {head}\n\nsymbol not found: `{res['symbol']}`\n"
    if res["candidates"]:
        L = [f"ambiguous symbol `{res['symbol']}` — {len(res['candidates'])} candidates:", ""]
        L += [f"- `{c['label']}` — {c['source_file']} ({c['id']})" for c in res["candidates"]]
        return "\n".join(L) + "\n"
    if not res["results"]:
        L.append("_(none)_")
        return "\n".join(L) + "\n"
    if res["kind"] == "impact":
        L.append(f"**{res['count']}** transitively-affected symbols "
                 f"(by hop: {', '.join(f'{h}:{c}' for h, c in res['by_hop'].items())}):")
        L.append("")
        for r in res["results"][:50]:
            L.append(f"- hop {r['hop']} · `{r['label']}` — {r['source_file']}")
    else:
        for r in res["results"]:
            rel = "/".join(r.get("relation") or [])
            L.append(f"- `{r['label']}` — {r['source_file']}" + (f"  [{rel}]" if rel else ""))
    return "\n".join(L) + "\n"
