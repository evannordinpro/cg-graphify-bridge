"""Freshness / drift detection for the fused graph.

`build` writes <out>/.cg_manifest.json (a content hash of the in-scope sources).
A git hook (post-commit/post-merge/post-checkout, installed by `install-hook`) calls
`status --check`, which recomputes the hash and drops <out>/.cg_stale on drift — the
same marker-then-consume model the graphify mandate uses. A later `build` consumes the
marker. No egress; pure local filesystem.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

SCAN_EXT = (".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs")
SKIP_DIRS = {
    "node_modules", "dist", "build", ".git", ".codegraph", ".venv", ".claude",
    "graphify-out", "graphify-out-cgbridge", "__pycache__", ".cache",
}
MANIFEST = ".cg_manifest.json"
STALE = ".cg_stale"


def _iter_sources(repo: Path, scopes: list[str]):
    for s in scopes:
        base = repo / s
        if base.is_file():
            yield base
            continue
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in SCAN_EXT:
                continue
            if SKIP_DIRS & set(p.parts) or p.name.endswith(".d.ts"):
                continue
            yield p


def source_hash(repo, scopes: list[str]) -> tuple[str, int]:
    """Deterministic content hash over (relpath, size, bytes) of in-scope sources.
    Content-based (not mtime) so it is stable across checkouts — same discipline as graphify."""
    repo = Path(repo)
    h = hashlib.sha256()
    n = 0
    for p in _iter_sources(repo, scopes):
        rel = p.relative_to(repo).as_posix()
        st = p.stat()
        h.update(rel.encode()); h.update(b"\0")
        h.update(str(st.st_size).encode()); h.update(b"\0")
        h.update(p.read_bytes()); h.update(b"\0")
        n += 1
    return h.hexdigest(), n


def read_manifest(out) -> dict | None:
    """Return the parsed manifest, or None if absent/corrupt (callers treat None as 'fresh repo')."""
    mpath = Path(out) / MANIFEST
    if not mpath.exists():
        return None
    try:
        return json.loads(mpath.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_manifest(out, repo, scopes: list[str], *, engine_stamp: dict | None = None) -> dict:
    """Write the freshness manifest. `engine_stamp` (from engine.detect_engine(), KD14) is
    merged in by the build path so the committed artifact records {engine, graphifyy,
    graspologic, networkx, schema_version}; staleness callers ignore the extra keys.

    The `semantic` baseline (stamped by semantic-merge) is PRESERVED across structural rebuilds:
    a code-only rebuild must not reset semantic freshness — if a *linked* file changed, the
    preserved baseline is exactly what surfaces that as semantic-stale on the next status."""
    out = Path(out)
    digest, n = source_hash(repo, scopes)
    payload = {"hash": digest, "files": n, "scopes": scopes}
    if engine_stamp:
        payload.update(engine_stamp)
    prior = read_manifest(out)
    if prior and "semantic" in prior:
        payload["semantic"] = prior["semantic"]
    (out / MANIFEST).write_text(json.dumps(payload, indent=2))
    (out / STALE).unlink(missing_ok=True)  # building consumes any pending drift marker
    return payload


def check_stale(out, repo, scopes: list[str] | None = None) -> dict:
    """Recompute the hash vs the manifest; drop/clear the .cg_stale marker. Returns status."""
    out = Path(out)
    mpath = out / MANIFEST
    if not mpath.exists():
        return {"state": "unbuilt", "stale": None}
    m = json.loads(mpath.read_text())
    scopes = scopes or m.get("scopes") or ["."]
    digest, n = source_hash(repo, scopes)
    stale = digest != m.get("hash")
    sp = out / STALE
    if stale:
        sp.write_text(json.dumps({"manifest_hash": m.get("hash"), "current_hash": digest,
                                  "files": n, "scopes": scopes}, indent=2))
    else:
        sp.unlink(missing_ok=True)
    return {"state": "stale" if stale else "fresh", "stale": stale,
            "files": n, "scopes": scopes, "marker": str(sp) if stale else None}


# ---------- semantic freshness (computed on demand, no markers — KD9/R4) ----------
# "semantic stale" = a doc OR a *linked* source file (the source_file of a node currently
# targeted by a semantic edge) changed since the last semantic-merge. A code-only edit to a
# NON-linked file leaves both fingerprints unchanged -> semantic stays fresh (the inverse of
# graphify's code_only test). Stays stdlib-only: reads the committed layers via json, never
# imports the heavy driver/graphify, so the bare-python3 hook path keeps working.

def _read_json(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _iter_docs(repo: Path, skip_dirnames: set[str]):
    """All *.md under repo, pruning vendored/build/tool dirs during the walk (fast on big repos
    with huge node_modules — we never descend into excluded dirs)."""
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in skip_dirnames and not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                yield Path(root) / f


def _hash_paths(repo: Path, paths) -> tuple[str, int]:
    """Deterministic content hash over (relpath, size, bytes) of the given files (sorted)."""
    h = hashlib.sha256()
    n = 0
    for p in sorted({str(x) for x in paths}):
        fp = Path(p)
        if not fp.is_file():
            continue
        try:
            rel = fp.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            rel = fp.name
        st = fp.stat()
        h.update(rel.encode()); h.update(b"\0")
        h.update(str(st.st_size).encode()); h.update(b"\0")
        h.update(fp.read_bytes()); h.update(b"\0")
        n += 1
    return h.hexdigest(), n


def linked_files(out: Path, repo: Path) -> set[Path]:
    """Source files that semantic edges point at = source_file of each structural node currently
    targeted by a semantic edge. These are the code files whose change invalidates the overlay."""
    structural = _read_json(out / "structural.json") or {}
    semantic = _read_json(out / "semantic.json") or {}
    by_id = {n["id"]: n for n in structural.get("nodes", [])}
    linked: set[Path] = set()
    for e in semantic.get("semantic_edges", []):
        node = by_id.get(e.get("target"))
        if node and node.get("source_file"):
            linked.add(repo / node["source_file"])
    return linked


def semantic_baseline(out, repo) -> dict:
    """Content fingerprint of the semantic INPUTS (all docs + linked source files), computed NOW.
    Stamped by semantic-merge; recomputed + compared by status/check-semantic."""
    out = Path(out); repo = Path(repo)
    skip = SKIP_DIRS | {out.name}
    docs_hash, ndocs = _hash_paths(repo, _iter_docs(repo, skip))
    linked_hash, nlinked = _hash_paths(repo, linked_files(out, repo))
    return {"docs_hash": docs_hash, "docs_count": ndocs,
            "linked_hash": linked_hash, "linked_count": nlinked}


def write_semantic_freshness(out, repo) -> dict:
    """Stamp the semantic baseline into the manifest under `semantic`, PRESERVING structural
    fields. Called after semantic-merge writes semantic.json."""
    out = Path(out)
    base = semantic_baseline(out, repo)
    m = read_manifest(out) or {}
    m["semantic"] = base
    (out / MANIFEST).write_text(json.dumps(m, indent=2))
    return base


def compute_status(out, repo, scopes: list[str] | None = None) -> dict:
    """Pure, on-demand freshness of BOTH layers (no marker reads/writes). structural = code drift
    vs the hash captured at build; semantic = doc/linked drift vs the baseline captured at merge."""
    out = Path(out); repo = Path(repo)
    m = read_manifest(out)
    if m is None:
        return {"state": "unbuilt", "structural": {"state": "unbuilt"}, "semantic": {"state": "unbuilt"}}
    scopes = scopes or m.get("scopes") or ["."]
    cur_hash, nfiles = source_hash(repo, scopes)
    structural = {"state": "stale" if cur_hash != m.get("hash") else "fresh",
                  "files": nfiles, "scopes": scopes}
    sem_base = m.get("semantic")
    if not sem_base:
        semantic = {"state": "unbuilt"}  # no semantic layer merged yet
    else:
        cur = semantic_baseline(out, repo)
        stale = (cur["docs_hash"] != sem_base.get("docs_hash")
                 or cur["linked_hash"] != sem_base.get("linked_hash"))
        semantic = {"state": "stale" if stale else "fresh",
                    "docs_count": cur["docs_count"], "linked_count": cur["linked_count"]}
    return {"state": "ok", "structural": structural, "semantic": semantic}


def is_uncommitted(repo, path) -> bool:
    """True if `path` has uncommitted changes or is untracked (git porcelain). Fail-safe: returns
    False when git is unavailable — inability to check must never become a hard block (R10)."""
    repo = Path(repo)
    try:
        rel = str(Path(path).resolve().relative_to(repo.resolve()))
    except ValueError:
        rel = str(path)
    try:
        r = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", rel],
                           capture_output=True, text=True)
    except (OSError, FileNotFoundError):
        return False
    return bool(r.stdout.strip())
