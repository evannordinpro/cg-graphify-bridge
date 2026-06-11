"""Compose graphify's value-add over the adapted codegraph graph.

build_from_json -> cluster (apply mapping onto nodes, D16) -> god_nodes / surprising
-> write the two committed layers (structural.json + semantic.json) and lazily materialize
the fused graphify-out/graph.json (gitignored local cache). No edits to graphify source
(library composition, D5).

KD7 (artifact split): the committed artifact is two layers — structural.json (CI-owned,
deterministic) and semantic.json (dev-owned overlay). graph.json is the *fused* view, derived
on demand by materialize() and gitignored; the CLAUDE.md consumer reads it but it is never
committed. write_artifact() is retained as a back-compat shim over the split writers.
"""
from __future__ import annotations

import json
from pathlib import Path

from graphify import analyze, build, cluster

from . import adapter
from .engine import SCHEMA_VERSION

# The library surface external consumers may call (the dead-code entry-point filter excludes
# exported symbols — `load_fused` & co. have no in-repo callers BY DESIGN, not by rot).
__all__ = ["apply_communities", "build_fused", "write_structural", "write_semantic",
           "write_artifact", "materialize", "load_fused", "read_layer", "degree_graph"]


def apply_communities(G, communities: dict) -> None:
    """cluster.cluster() returns {cid:[node_ids]} but does NOT mutate G (D16)."""
    for cid, node_ids in communities.items():
        for nid in node_ids:
            if nid in G.nodes:
                G.nodes[nid]["community"] = cid


def build_fused(db_path=None, *, res=None, resolution: float = 1.0,
                exclude_hubs_percentile: float | None = 95.0,
                prune_orphans: bool = False, fold_singletons: bool = False) -> dict:
    # res may be supplied directly (e.g. the TS type-aware substrate) — substrate-agnostic
    if res is None:
        res = adapter.adapt(db_path)
    if prune_orphans:
        res = adapter.prune_orphans(res)  # drop zero-edge non-file artifacts (lossless)
    av = adapter.analysis_view(res)
    G = build.build_from_json({"nodes": av["nodes"], "edges": av["edges"]}, directed=False)
    communities = cluster.cluster(G, resolution=resolution,
                                  exclude_hubs_percentile=exclude_hubs_percentile)
    if fold_singletons:
        communities = adapter.fold_singleton_communities(communities, res)  # reassign, never delete
    apply_communities(G, communities)
    gods = analyze.god_nodes(G, top_n=15)
    surprising = analyze.surprising_connections(G, communities=communities, top_n=10)
    return {
        "graph": G,
        "communities": communities,
        "god_nodes": gods,
        "surprising": surprising,
        "adapt": res,
    }


# ---------- serialization primitives (deterministic) ----------

def _write_json(path: Path, data: dict) -> None:
    # sort_keys + trailing newline = byte-stable committed layers (R5)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


_GITIGNORE_MARK = "# cg-graphify-bridge: fused graph + caches are LOCAL (lazily materialized)"


def _write_gitignore(outdir: Path) -> None:
    """Ignore the derived/local artifacts so only the layers get committed (R8/D2). Idempotent:
    leaves any pre-existing .gitignore intact, appends our block once."""
    p = outdir / ".gitignore"
    existing = p.read_text() if p.exists() else ""
    if _GITIGNORE_MARK in existing:
        return
    block = (f"{_GITIGNORE_MARK}\n"
             "# Commit the layers (structural.json, semantic.json, manifest.json, GRAPH_REPORT.md).\n"
             "graph.json\n"
             ".cache/\n")
    p.write_text((existing.rstrip("\n") + "\n\n" + block) if existing.strip() else block)


def _build_fg(structural: dict, semantic: dict | None):
    """Reconstruct the fused directed graph from the layers. This replays the EXACT node/edge
    insertion + attribute logic the pre-split writer used, so materialize() is byte-identical
    to direct fusion (KD7 parity)."""
    import networkx as nx

    communities = structural.get("communities", {})
    id2comm = {nid: cid for cid, ids in communities.items() for nid in ids}
    god_ids = {g["id"] for g in structural.get("god_nodes", [])}

    FG = nx.DiGraph()  # directed -> preserves codegraph call direction (D15)
    # KD1: deterministic insertion order (node_link_data emits graph order) -> nodes by id,
    # edges by (source,target,relation) (also pins the DiGraph parallel-edge collapse winner).
    for n in sorted(structural["nodes"], key=lambda n: n["id"]):
        attrs = {k: v for k, v in n.items() if k != "id"}
        attrs["community"] = id2comm.get(n["id"])
        attrs["god_node"] = n["id"] in god_ids
        FG.add_node(n["id"], **attrs)
    for e in sorted(structural["edges"], key=lambda e: (e["source"], e["target"], e["relation"])):
        FG.add_edge(e["source"], e["target"], relation=e["relation"], context=e["context"],
                    confidence=e["confidence"], weight=e["weight"])

    if semantic:
        for n in sorted(semantic.get("semantic_nodes", []), key=lambda n: n["id"]):
            attrs = {k: v for k, v in n.items() if k != "id"}
            attrs.setdefault("file_type", "document")
            FG.add_node(n["id"], **attrs)
        for e in sorted(semantic.get("semantic_edges", []),
                        key=lambda e: (e.get("source", ""), e.get("target", ""), e.get("relation", ""))):
            FG.add_edge(e["source"], e["target"], relation=e.get("relation", "references"),
                        context=e.get("context", "semantic"),
                        confidence=e.get("confidence", "INFERRED"), weight=e.get("weight", 1.0))
    return FG


def _write_graph_json(FG, path: Path) -> None:
    from networkx.readwrite import json_graph
    # edges="edges" pins the array key (version-independent); sort_keys stabilizes per-object
    # key order; trailing newline for clean diffs -> graph.json is byte-deterministic.
    path.write_text(json.dumps(json_graph.node_link_data(FG, edges="edges"), indent=2,
                               sort_keys=True, ensure_ascii=False) + "\n")


def _write_report(structural: dict, outdir: Path) -> Path:
    """GRAPH_REPORT.md — structural-derived, committed, human-browsable (ODQ-C). Structural only
    (no semantic section): the committed report is CI-owned + deterministic; semantic lives in
    the materialized fused view. KD4 stable ordering (degree ties by id; surprising by score)."""
    nodes = structural["nodes"]
    edges = structural["edges"]
    communities = structural.get("communities", {})
    n_nodes = len(nodes)
    # DiGraph collapses parallel edges -> the fused edge count is distinct (source,target) pairs
    n_edges = len({(e["source"], e["target"]) for e in edges})
    lines = [
        "# Fused Graph Report (codegraph substrate + graphify overlay)",
        "",
        f"- nodes: {n_nodes}  edges: {n_edges}  communities: {len(communities)}",
        f"- adapter stats: {structural.get('stats', {})}",
        "",
        "## God nodes",
        "",
    ]
    gods_sorted = sorted(structural.get("god_nodes", []),
                         key=lambda g: (-(g.get("degree") or 0), str(g.get("id"))))
    lines += [f"- **{g.get('label')}** (degree {g.get('degree')}) `{g.get('id')}`" for g in gods_sorted]
    lines += ["", "## Surprising connections", ""]
    surprising_sorted = sorted(
        structural.get("surprising", [])[:10],
        key=lambda s: (-(s.get("_score") or 0), str(s.get("source")), str(s.get("target"))))
    lines += [f"- {s.get('source')} ↔ {s.get('target')}" for s in surprising_sorted]
    rep = outdir / "GRAPH_REPORT.md"
    rep.write_text("\n".join(lines) + "\n")
    return rep


# ---------- layer readers ----------

def degree_graph(structural: dict):
    """Build an UNDIRECTED, UNCLUSTERED graph from the structural layer's edges, purely for
    degree-based ranking of curated nodes in semantic-prep. Deliberately does NOT call
    cluster.cluster — re-clustering on a dev box is the one drift source R4/KD7 removes; the
    committed structural layer already carries CI's communities. `contains` edges are skipped
    to mirror the analysis-view ranking semantics."""
    import networkx as nx
    G = nx.Graph()
    G.add_nodes_from(n["id"] for n in structural.get("nodes", []))
    for e in structural.get("edges", []):
        if e.get("relation") == "contains":
            continue
        G.add_edge(e["source"], e["target"])
    return G


def read_layer(outdir, name: str) -> dict | None:
    """Read + schema-validate a committed layer ('structural' | 'semantic'). Returns None when
    absent (callers decide if that's fatal). Raises SystemExit when the file is corrupt or its
    schema_version is unsupported — a malformed layer is rejected, never silently consumed (R10)."""
    p = Path(outdir) / f"{name}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise SystemExit(f"cg-graphify-bridge: {name}.json is corrupt ({e}); "
                         f"rebuild with `cg-graphify-bridge build <repo>`.") from e
    sv = data.get("schema_version") if isinstance(data, dict) else None
    if sv != SCHEMA_VERSION:
        raise SystemExit(
            f"cg-graphify-bridge: {name}.json schema_version={sv!r} but this tool supports "
            f"{SCHEMA_VERSION}. Rebuild with `cg-graphify-bridge build <repo>`.")
    return data


def _file_read_fallback(outdir: Path) -> dict:
    """Last-resort consumer read when materialization fails: return whatever raw layer content
    is parseable so navigation degrades gracefully instead of hard-blocking (R10). Never raises."""
    fused = {"nodes": [], "edges": [], "directed": True, "degraded": True}
    for name, nk, ek in (("structural", "nodes", "edges"),
                         ("semantic", "semantic_nodes", "semantic_edges")):
        p = Path(outdir) / f"{name}.json"
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if isinstance(data, dict):
            fused["nodes"] += data.get(nk, [])
            fused["edges"] += data.get(ek, [])
    return fused


def load_fused(outdir) -> dict:
    """Consumer entry (the CLAUDE.md graph.json reader / future `query`): return the fused
    node-link graph dict. Prefers the materialized graph.json cache; (re)materializes from the
    committed layers when the cache is missing or corrupt; if structural itself is unreadable,
    degrades to a best-effort file read so a consumer never hard-blocks (R10)."""
    outdir = Path(outdir)
    gj = outdir / "graph.json"
    if gj.exists():
        try:
            return json.loads(gj.read_text())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            pass  # corrupt cache -> rebuild from the committed layers below
    try:
        materialize(outdir)
        return json.loads((outdir / "graph.json").read_text())
    except SystemExit:
        return _file_read_fallback(outdir)


# ---------- split writers + lazy fused materialization (KD7) ----------

def write_structural(fused: dict, outdir) -> dict:
    """Write the committed structural layer (structural.json) + GRAPH_REPORT.md + .gitignore.
    structural.json is a lossless mirror of `fused` minus the live graph object, so materialize()
    can replay the exact fused graph. Does NOT write graph.json (that's lazily materialized)."""
    res = fused["adapt"]
    data = {
        "schema_version": SCHEMA_VERSION,
        "layer": "structural",
        "nodes": sorted(res.nodes, key=lambda n: n["id"]),
        "edges": sorted(res.edges, key=lambda e: (e["source"], e["target"], e["relation"])),
        "communities": fused["communities"],
        "god_nodes": fused["god_nodes"],
        "surprising": fused.get("surprising", [])[:10],
        "stats": res.stats,
    }
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    _write_json(outdir / "structural.json", data)
    rep = _write_report(data, outdir)
    _write_gitignore(outdir)
    return {"structural": str(outdir / "structural.json"), "report": str(rep),
            "nodes": len(data["nodes"]), "edges": len(data["edges"])}


def write_semantic(semantic: dict, outdir) -> dict:
    """Write the committed semantic layer (semantic.json) — the dev-owned doc->code overlay,
    independent of structural so it never triggers a structural rebuild/merge war (R8)."""
    data = {
        "schema_version": SCHEMA_VERSION,
        "layer": "semantic",
        "semantic_nodes": sorted(semantic.get("semantic_nodes", []), key=lambda n: n["id"]),
        "semantic_edges": sorted(semantic.get("semantic_edges", []),
                                 key=lambda e: (e.get("source", ""), e.get("target", ""),
                                                e.get("relation", ""))),
        "stats": semantic.get("stats", {}),
    }
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    _write_json(outdir / "semantic.json", data)
    return {"semantic": str(outdir / "semantic.json"),
            "semantic_nodes": len(data["semantic_nodes"]),
            "semantic_edges": len(data["semantic_edges"])}


def materialize(outdir) -> dict:
    """Lazily fuse the committed layers into graphify-out/graph.json (gitignored local cache).
    graph.json = merge(structural.json, semantic.json) — the FULL composite-keyed directed graph
    the CLAUDE.md consumer reads. Tolerates a missing semantic layer (R10); requires structural."""
    outdir = Path(outdir)
    structural = read_layer(outdir, "structural")
    if structural is None:
        raise SystemExit("cg-graphify-bridge: no structural.json to materialize — run `build` first")
    semantic = read_layer(outdir, "semantic")
    FG = _build_fg(structural, semantic)
    gj = outdir / "graph.json"
    _write_graph_json(FG, gj)
    return {"graph_json": str(gj), "nodes": FG.number_of_nodes(), "edges": FG.number_of_edges(),
            "semantic_edges": len(semantic.get("semantic_edges", [])) if semantic else 0}


def write_artifact(fused: dict, outdir, semantic: dict | None = None) -> dict:
    """Back-compat shim (pre-split callers + tests): emit the split layers, then materialize the
    fused graph.json so legacy consumers still find graph.json + GRAPH_REPORT.md. New code should
    call write_structural / write_semantic / materialize directly (KD7)."""
    s = write_structural(fused, outdir)
    if semantic:
        write_semantic(semantic, outdir)
    m = materialize(outdir)
    return {"graph_json": m["graph_json"], "report": s["report"], "nodes": m["nodes"],
            "edges": m["edges"], "semantic_edges": m["semantic_edges"]}
