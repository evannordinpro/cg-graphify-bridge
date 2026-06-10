"""Type-aware TypeScript substrate ingest.

Runs the TS-compiler-API extractor (ts_substrate_js/extract.cjs — the mechanism
scip-typescript is built on) and turns its output into the same AdaptResult the
codegraph adapter produces, so the fusion/driver path is substrate-agnostic.
Cross-file resolution is type-aware (alias-following) → ~2.4x denser than tree-sitter.
"""
from __future__ import annotations

import json
import subprocess
from collections import Counter
from importlib.resources import as_file, files
from pathlib import Path

from .adapter import AdaptResult, composite_id

# TS extractor edge kinds -> graphify relations
TS_EDGE_RELATION = {
    "calls": "calls", "references": "references",
    "extends": "inherits", "implements": "inherits", "contains": "contains",
}


def _extractor_resource():
    """Locate the bundled extractor INSIDE the installed package (KD5).

    The old ``__file__/parents[2]`` lookup resolved to a repo-root sibling dir, which
    exists only in a source checkout — after a pipx install ``parents[2]`` points into
    site-packages and the file is gone. ``importlib.resources`` resolves the packaged
    data file in every install shape (editable, wheel, zipapp)."""
    return files("cg_graphify_bridge.ts_substrate_js").joinpath("extract.cjs")


def _run(ext: str, repo, scopes: list[str]) -> dict:
    r = subprocess.run(["node", ext, str(repo), ",".join(scopes)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ts-substrate extractor failed (rc={r.returncode}):\n{(r.stderr or '')[-600:]}")
    return json.loads(r.stdout)


def run_extractor(repo, scopes: list[str], extractor: Path | None = None) -> dict:
    if extractor is not None:  # explicit override (tests / pinned path)
        return _run(str(extractor), repo, scopes)
    # as_file yields a real on-disk path (no-op for filesystem installs; extracts for zips)
    with as_file(_extractor_resource()) as ext:
        return _run(str(ext), repo, scopes)


def adapt_ts(repo, scopes: list[str]) -> AdaptResult:
    data = run_extractor(repo, scopes)
    local2comp: dict[int, str] = {}
    by_comp: dict[str, dict] = {}
    merges = 0
    for n in data["nodes"]:
        cid = composite_id(n["file_path"], n["qualified_name"], n["kind"], n.get("signature"))
        local2comp[n["id"]] = cid
        if cid in by_comp:
            merges += 1
            by_comp[cid]["metadata"]["cg_merged_ids"].append(n["id"])
            continue
        by_comp[cid] = {
            "id": cid, "label": n["name"], "file_type": "code",
            "source_file": n["file_path"], "source_location": f"L{n['line']}",
            "metadata": {"cg_kind": n["kind"], "origin": "ts-substrate",
                         "qualified_name": n["qualified_name"], "signature": n.get("signature"),
                         "language": "typescript", "start_line": n["line"], "cg_merged_ids": []},
        }
    edges: list[dict] = []
    unmapped = 0
    for e in data["edges"]:
        s, t = local2comp.get(e["source"]), local2comp.get(e["target"])
        if not s or not t:
            unmapped += 1
            continue
        edges.append({"source": s, "target": t, "relation": TS_EDGE_RELATION.get(e["kind"], "references"),
                      "context": e["kind"], "confidence": "EXTRACTED", "weight": 1.0,
                      "source_file": "", "source_location": ""})
    stats = {
        "substrate": "ts-typechecker", "raw_nodes": len(data["nodes"]),
        "composite_nodes": len(by_comp), "merges": merges,
        "edges_in": len(data["edges"]), "edges_out": len(edges), "unmapped_edges": unmapped,
        "kind_dist": dict(Counter(n["metadata"]["cg_kind"] for n in by_comp.values())),
    }
    return AdaptResult(list(by_comp.values()), edges, local2comp, stats)
