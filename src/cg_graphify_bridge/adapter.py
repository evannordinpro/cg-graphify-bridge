"""codegraph SQLite -> graphify {nodes, edges} adapter.

Join key = composite(file_path, qualified_name, kind, signature): stable across
line-shifting edits, portable across machines, 99.98% unique on real data.
See docs/02-design.md (D1, D3, D4, D12-D17).
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass

_UNIT = "\x1f"

# codegraph EdgeKind (12) -> graphify relation
EDGE_RELATION = {
    "calls": "calls",
    "imports": "imports",
    "extends": "inherits",
    "implements": "inherits",
    "contains": "contains",
    "references": "references",
    "type_of": "references",
    "returns": "references",
    "instantiates": "references",
    "overrides": "references",
    "decorates": "references",
    "exports": "references",
}
PROV_CONFIDENCE = {"tree-sitter": "EXTRACTED", "heuristic": "INFERRED", "scip": "EXTRACTED"}

# kinds that are meaningful targets for semantic doc->code edges (D17)
LINKABLE_KINDS = {
    "function", "method", "class", "module", "route", "component",
    "interface", "struct", "trait", "protocol", "enum", "namespace",
}
# excluded from the analysis view: file hubs + sparsely-connected noise kinds that
# fragment communities once file/contains structure is removed (D12). On a large real-world
# repo these (imports + constants + lone interfaces) became thousands of singleton communities.
ANALYSIS_EXCLUDE_KINDS = {
    "file", "import", "constant", "variable", "property", "type_alias",
    "field", "parameter", "enum_member",
}
ANALYSIS_EXCLUDE_RELATIONS = {"contains"}


def composite_id(file_path: str, qualified_name: str, kind: str, signature: str | None) -> str:
    raw = _UNIT.join([file_path or "", qualified_name or "", kind or "", signature or ""])
    return "cg:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _is_test_path(sf: str | None) -> bool:
    sf = sf or ""
    parts = sf.split("/")
    if any(p in ("tests", "test", "__tests__", "spec", "specs") for p in parts):
        return True
    leaf = parts[-1] if parts else ""
    if leaf.startswith("test_") or leaf.endswith("_test.py"):
        return True
    # .test.* / .spec.* across TS/JS variants (the .test.tsx gap let test helpers leak in)
    return any(leaf.endswith(f".{w}.{e}")
               for w in ("test", "spec") for e in ("ts", "tsx", "js", "jsx", "mts", "cts"))


@dataclass
class AdaptResult:
    nodes: list[dict]
    edges: list[dict]
    cg_to_composite: dict
    stats: dict


def read_codegraph_db(db_path) -> tuple[list, list]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        # KD2: deterministic, content-based row order (NOT sqlite rowid order, which is
        # unstable across re-index) so the adapted node/edge order is reproducible.
        # is_abstract/is_exported/visibility exist in codegraph >=0.9.9 (Martin-metric inputs, FR0)
        # but degrade gracefully if a DB variant lacks them — select only what's present.
        cols = {row[1] for row in con.execute("PRAGMA table_info(nodes)").fetchall()}
        opt = [c for c in ("is_abstract", "is_exported", "visibility") if c in cols]
        nodes = con.execute(
            "SELECT id,kind,name,qualified_name,file_path,signature,start_line,end_line,language"
            + ("," + ",".join(opt) if opt else "")
            + " FROM nodes ORDER BY file_path, qualified_name, kind, signature, start_line, id"
        ).fetchall()
        edges = con.execute(
            "SELECT source,target,kind,provenance FROM edges "
            "ORDER BY source, target, kind, provenance"
        ).fetchall()
    finally:
        con.close()
    return nodes, edges


def adapt(db_path) -> AdaptResult:
    nrows, erows = read_codegraph_db(db_path)
    cg2comp: dict[str, str] = {}
    by_comp: dict[str, dict] = {}
    merges = 0
    for r in nrows:
        cid = composite_id(r["file_path"], r["qualified_name"], r["kind"], r["signature"])
        cg2comp[r["id"]] = cid
        if cid in by_comp:  # residual collision -> deterministic merge (D1/R9)
            merges += 1
            by_comp[cid]["metadata"]["cg_merged_ids"].append(r["id"])
            continue
        md = {
            "cg_kind": r["kind"], "origin": "codegraph",
            "qualified_name": r["qualified_name"], "signature": r["signature"],
            "language": r["language"], "start_line": r["start_line"],
            "end_line": r["end_line"], "cg_merged_ids": [],
        }
        # Martin-metric inputs (FR0) — stamped ONLY when the codegraph DB provides the column, so a
        # legacy DB's absence stays detectable (abstractness caveat) instead of silently reading False.
        rkeys = r.keys()
        if "is_abstract" in rkeys:
            md["is_abstract"] = bool(r["is_abstract"])
        if "is_exported" in rkeys:
            md["is_exported"] = bool(r["is_exported"])
        if "visibility" in rkeys:
            md["visibility"] = r["visibility"]
        by_comp[cid] = {
            "id": cid, "label": r["name"], "file_type": "code",
            "source_file": r["file_path"], "source_location": f"L{r['start_line']}",
            "metadata": md,
        }
    edges: list[dict] = []
    unmapped = 0
    for e in erows:
        s = cg2comp.get(e["source"])
        t = cg2comp.get(e["target"])
        if not s or not t:
            unmapped += 1
            continue
        edges.append({
            "source": s,
            "target": t,
            "relation": EDGE_RELATION.get(e["kind"], "references"),
            "context": e["kind"],
            "confidence": PROV_CONFIDENCE.get(e["provenance"] or "tree-sitter", "EXTRACTED"),
            "weight": 1.0,
            "source_file": "",
            "source_location": "",
        })
    stats = {
        "cg_nodes": len(nrows),
        "composite_nodes": len(by_comp),
        "merges": merges,
        "edges_in": len(erows),
        "edges_out": len(edges),
        "unmapped_edges": unmapped,
        "kind_dist": dict(Counter(n["metadata"]["cg_kind"] for n in by_comp.values())),
    }
    return AdaptResult(list(by_comp.values()), edges, cg2comp, stats)


def full_graph(res: AdaptResult) -> dict:
    """Topology/navigation view: everything, keyed by composite id (D12)."""
    return {"nodes": res.nodes, "edges": res.edges}


def from_structural(structural: dict) -> AdaptResult:
    """Reconstruct an AdaptResult from a committed structural.json layer — no DB read, no
    extraction, no clustering. Lets the semantic commands key doc->code edges against the
    CI-built deterministic composite ids by consuming the committed layer (R4/KD7), instead
    of re-extracting + re-clustering (the only place a dev would have introduced engine drift)."""
    return AdaptResult(list(structural.get("nodes", [])), list(structural.get("edges", [])),
                       {}, dict(structural.get("stats", {})))


def analysis_view(res: AdaptResult, drop_test_paths: bool = True) -> dict:
    """For cluster/god-node: drop file nodes, contains edges, test paths (D12/D14)."""
    keep_nodes, keep_ids = [], set()
    for n in res.nodes:
        if n["metadata"]["cg_kind"] in ANALYSIS_EXCLUDE_KINDS:
            continue
        if drop_test_paths and _is_test_path(n["source_file"]):
            continue
        keep_nodes.append(n)
        keep_ids.add(n["id"])
    keep_edges = [
        e for e in res.edges
        if e["relation"] not in ANALYSIS_EXCLUDE_RELATIONS
        and e["source"] in keep_ids and e["target"] in keep_ids
    ]
    return {"nodes": keep_nodes, "edges": keep_edges}


def prune_orphans(res: AdaptResult) -> AdaptResult:
    """Drop NON-file nodes with zero edges of any kind (extraction artifacts).
    File nodes are always kept for navigation (D12). Lossless for connected code:
    a node attached to nothing carries no relational signal. Returns a new AdaptResult."""
    deg: Counter = Counter()
    for e in res.edges:
        deg[e["source"]] += 1
        deg[e["target"]] += 1
    keep, dropped = [], 0
    for n in res.nodes:
        if n["metadata"].get("cg_kind") != "file" and deg[n["id"]] == 0:
            dropped += 1
            continue
        keep.append(n)
    if not dropped:
        return res
    keep_ids = {n["id"] for n in keep}
    edges = [e for e in res.edges if e["source"] in keep_ids and e["target"] in keep_ids]
    return AdaptResult(keep, edges, res.cg_to_composite, {**res.stats, "pruned_orphans": dropped})


def fold_singleton_communities(communities: dict, res: AdaptResult) -> dict:
    """Reassign size-1 communities to the dominant non-singleton community of their
    file-siblings. LOSSLESS — reassigns, never deletes a node. Collapses analysis-view
    orphans (real but unreferenced decls) into their file's locality so the community
    structure reflects code organization instead of stranding leaves."""
    id2comm = {nid: c for c, ids in communities.items() for nid in ids}
    file_children: dict = defaultdict(list)
    node_file: dict = {}
    for n in res.nodes:
        if n["id"] in id2comm:  # only clustered (analysis-view) nodes
            file_children[n["source_file"]].append(n["id"])
            node_file[n["id"]] = n["source_file"]
    sizes = Counter(id2comm.values())
    moved: dict = {}
    # phase 1: singleton -> dominant NON-singleton sibling community in the same file
    for nid, c in id2comm.items():
        if sizes[c] != 1:
            continue
        sib_comms = Counter(
            id2comm[s] for s in file_children.get(node_file.get(nid), [])
            if s != nid and sizes[id2comm[s]] > 1
        )
        if sib_comms:
            moved[nid] = sib_comms.most_common(1)[0][0]
    # phase 2: co-located leftover singletons (≥2 in one file, all still singletons) ->
    # one shared module community. Deterministic target = lowest node-id's community.
    eff = {nid: moved.get(nid, id2comm[nid]) for nid in id2comm}
    eff_sizes = Counter(eff.values())
    leftover: dict = defaultdict(list)
    for nid in id2comm:
        if eff_sizes[eff[nid]] == 1:
            leftover[node_file.get(nid)].append(nid)
    for ids in leftover.values():
        if len(ids) > 1:
            tgt_comm = id2comm[sorted(ids)[0]]
            for nid in sorted(ids)[1:]:
                moved[nid] = tgt_comm
    if not moved:
        return communities
    new = {c: [i for i in ids if i not in moved] for c, ids in communities.items()}
    for nid, c in moved.items():
        new.setdefault(c, []).append(nid)
    return {c: ids for c, ids in new.items() if ids}


def linkable_subset(res: AdaptResult, communities: dict | None = None):
    """Curated code-node list for semantic subagents (D17). Optionally per-community."""
    linkable = [
        {"id": n["id"], "label": n["label"], "file": n["source_file"],
         "cg_kind": n["metadata"]["cg_kind"]}
        for n in res.nodes
        if n["metadata"]["cg_kind"] in LINKABLE_KINDS
    ]
    if communities is None:
        return linkable
    id2comm = {i: c for c, ids in communities.items() for i in ids}
    grouped: dict = defaultdict(list)
    for item in linkable:
        grouped[id2comm.get(item["id"])].append(item)
    return dict(grouped)
