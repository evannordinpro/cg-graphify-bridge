"""Semantic overlay: merge subagent-produced doc->code edges, keyed by composite ids.

The /graphify subagent path is the runtime extractor (contract in
overlay/SKILL_overlay.md). This module owns the deterministic halves: prep
(context -> per-doc tasks) and merge (payloads -> fused graph). Claude subagents
fill payloads between prep and merge — no /tmp, no third-party LLM (R4, R7, D6, D17).
"""
from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from .adapter import LINKABLE_KINDS, AdaptResult, linkable_subset

_DOC_EXCLUDE_DIRS = {"node_modules", "dist", "build", ".git", ".codegraph", ".venv",
                     ".claude", "graphify-out", "graphify-out-cgbridge",
                     ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache"}
_STEM_KINDS = {"file", "module", "namespace"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _stem_norm(label: str) -> str:
    return _norm(Path(label).stem)


def build_subagent_context(res: AdaptResult, communities: dict | None = None,
                           docs: list[str] | None = None) -> dict:
    """Identity metadata + doc text only — NEVER source (R7)."""
    return {
        "instruction": (
            "For each doc->code relationship, set edge.target to the EXACT composite id "
            "from code_nodes. If unsure of the id, set target_label to the symbol name and "
            "leave target empty; never invent ids; you are given no source code."
        ),
        "code_nodes": linkable_subset(res, communities=communities),
        "docs": docs or [],
    }


def _label_index(res: AdaptResult) -> dict[str, list[str]]:
    """label -> [composite ids]. File/module/namespace nodes are ALSO indexed by their
    extension-stripped stem so doc refs like `translationAnalysisFixPlanDD` resolve to the
    file node `translationAnalysisFixPlanDD.ts` (task 5)."""
    idx: dict[str, list[str]] = defaultdict(list)
    for n in res.nodes:
        idx[_norm(n["label"])].append(n["id"])
        if n.get("metadata", {}).get("cg_kind") in _STEM_KINDS:
            stem = _stem_norm(n["label"])
            if stem:
                idx[stem].append(n["id"])
    return idx


def merge_semantic(payload: dict, res: AdaptResult, label_index: dict | None = None) -> dict:
    """Validate + merge subagent output. A target that isn't a known id is resolved by
    UNIQUE label match (incl. file/module stem) or pruned + reported (no silent dangling)."""
    code_ids = {n["id"] for n in res.nodes}
    idx = label_index if label_index is not None else _label_index(res)
    sem_nodes = payload.get("nodes", [])
    valid = code_ids | {n["id"] for n in sem_nodes}
    kept, dangling, fallback = [], [], 0
    for e in payload.get("edges", []):
        if e.get("target") in valid:
            kept.append(e)
            continue
        cands = list(dict.fromkeys(idx.get(_norm(e.get("target_label") or e.get("target") or ""), [])))
        if len(cands) == 1:
            kept.append({**e, "target": cands[0],
                         "context": (e.get("context", "") + ";label-fallback").lstrip(";")})
            fallback += 1
        else:
            dangling.append(e)
    return {
        "semantic_nodes": sem_nodes, "semantic_edges": kept, "dangling": dangling,
        "fallback_resolved": fallback,
        "stats": {"in_edges": len(payload.get("edges", [])), "kept": len(kept),
                  "dangling": len(dangling), "fallback": fallback},
    }


# ---------- scaling: prep tasks (context) + merge payloads ----------

def discover_docs(repo: Path, out_dirname: str) -> list[Path]:
    out = []
    for p in sorted(repo.rglob("*.md")):
        if set(p.parts) & _DOC_EXCLUDE_DIRS or out_dirname in p.parts:
            continue
        out.append(p)
    return out


def curated_nodes(res: AdaptResult, fused: dict, max_nodes: int) -> list[dict]:
    """Linkable code nodes ranked by degree (the architecturally central symbols)."""
    G = fused["graph"]
    linkable = [n for n in res.nodes if n["metadata"]["cg_kind"] in LINKABLE_KINDS]
    deg = {nid: G.degree(nid) for nid in G.nodes}
    linkable.sort(key=lambda n: deg.get(n["id"], 0), reverse=True)
    return [{"id": n["id"], "label": n["label"], "file": n["source_file"],
             "kind": n["metadata"]["cg_kind"]} for n in linkable[:max_nodes]]


def prep_tasks(res: AdaptResult, fused: dict, repo: Path, out: Path, max_nodes: int = 600,
               max_docs: int | None = None, doc_filter: str | None = None) -> dict:
    """Write one subagent task ({doc, code_nodes}) per doc into <out>/.cache/semantic/tasks/."""
    nodes = curated_nodes(res, fused, max_nodes)
    docs = discover_docs(repo, out.name)
    if doc_filter:
        docs = [d for d in docs if doc_filter in str(d)]
    if max_docs:
        docs = docs[:max_docs]
    base = out / ".cache" / "semantic"
    if base.exists():
        shutil.rmtree(base)
    tasks_dir = base / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, doc in enumerate(docs):
        tid = f"{i:03d}"
        rel = str(doc.relative_to(repo))
        (tasks_dir / f"{tid}.json").write_text(json.dumps({
            "task_id": tid, "doc_path": rel, "doc_node_id": "doc:" + _norm(rel),
            "doc": doc.read_text(errors="ignore")[:8000], "code_nodes": nodes,
        }))
        manifest.append({"task_id": tid, "doc_path": rel})
    (base / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return {"tasks": manifest, "tasks_dir": tasks_dir,
            "payloads_dir": base / "payloads", "code_nodes": len(nodes)}


def merge_payloads(res: AdaptResult, out: Path) -> dict:
    """Merge all <out>/.cache/semantic/payloads/*.json into one semantic overlay."""
    pdir = out / ".cache" / "semantic" / "payloads"
    idx = _label_index(res)
    nodes_by_id: dict[str, dict] = {}
    edges: list[dict] = []
    kept = dangling = fallback = 0
    payloads = sorted(pdir.glob("*.json")) if pdir.exists() else []
    for pf in payloads:
        m = merge_semantic(json.loads(pf.read_text()), res, label_index=idx)
        for n in m["semantic_nodes"]:
            nodes_by_id[n["id"]] = n
        edges += m["semantic_edges"]
        kept += len(m["semantic_edges"])
        dangling += len(m["dangling"])
        fallback += m["fallback_resolved"]
    return {"semantic_nodes": list(nodes_by_id.values()), "semantic_edges": edges,
            "stats": {"payloads": len(payloads), "kept": kept,
                      "dangling": dangling, "fallback": fallback}}
