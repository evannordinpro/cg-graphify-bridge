"""Phase 6 — PROJECT_FAQ.md: deterministic graph answers + dev-Claude narrative (KD5-KD10).

Two halves, mirroring the structural/semantic split (next_implementation.md, DEC-1..6):
- QUANTITATIVE (this module, deterministic, LLM-free — CI renders it): features = Leiden
  communities; per-feature components, cross-community neighbors (analytics
  coupling_instability KD1), inputs (exported members) / outputs (external dependencies),
  and debt-by-feature/component/type reused from health()["debt"].
- NARRATIVE (the dev's Claude, committed): what the project is + per-feature concept and
  functionality — not derivable from the graph. Flows through the same prep → payloads →
  merge shape as the semantic overlay: `faq-prep` writes tasks under <out>/.cache/faq/
  (EPHEMERAL, gitignored, never on main), the agent fills payloads, `faq-merge` commits
  them into <out>/faq.json and stamps a per-feature freshness baseline in the manifest.

Features are keyed by a rebuild-stable ANCHOR — the lexicographically smallest member
composite id — because Leiden community NUMBERS renumber across rebuilds. A narrative whose
anchor no longer exists is reported as orphaned (never silently dropped, never guessed).
Staleness is per-feature: the baseline hashes each feature's member source files, so a
narrative re-enters review only when its own feature's code changed (faq.json is stable,
not churned every build). PROJECT_FAQ.md is content-deterministic (no timestamp/SHA) so the
CI commit-back stays diff-gated.
"""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

from . import analytics, driver, freshness

_NARRATIVE_KEYS = {"name", "concept", "functionality"}
_PROJECT_KEYS = {"what", "purpose", "value"}


# ---------- quantitative half (deterministic) ----------

def feature_map(structural: dict) -> list[dict]:
    """Per-community feature facts: anchor, members (degree-ranked), neighbor communities,
    inputs (exported members = the feature's public surface), outputs (external symbols the
    feature depends on). Sorted by size desc then anchor — deterministic."""
    meta = {n["id"]: n for n in structural.get("nodes", [])}
    communities = structural.get("communities", {})
    comm_of = {m: cid for cid, members in communities.items() for m in members}
    dg = analytics.build_digraph(structural)
    coupling = analytics.coupling_instability(structural)
    up, down = defaultdict(list), defaultdict(list)
    for n in coupling["neighbors"]:
        down[n["from"]].append((n["to"], n["weight"]))      # `from` depends on `to`
        up[n["to"]].append((n["from"], n["weight"]))        # `to` is depended on by `from`
    feats = []
    for cid, members in communities.items():
        nodes = [meta[m] for m in members if m in meta]
        if not nodes:
            continue
        deg = {n["id"]: (dg.degree(n["id"]) if n["id"] in dg else 0) for n in nodes}
        ranked = sorted(nodes, key=lambda n: (-deg[n["id"]], n["id"]))
        outputs = sorted({meta[v]["label"] for m in members if m in dg
                          for v in dg.successors(m)
                          if comm_of.get(v) != cid and v in meta})
        feats.append({
            "anchor": min(m for m in members),
            "community": cid,
            "size": len(nodes),
            "members": [{"id": n["id"], "label": n["label"], "file": n.get("source_file")}
                        for n in ranked[:8]],
            "files": sorted({n.get("source_file") for n in nodes if n.get("source_file")}),
            "inputs": sorted({n["label"] for n in nodes
                              if n.get("metadata", {}).get("is_exported")}),
            "outputs": outputs[:8],
            "upstream": sorted(up.get(cid, []), key=lambda t: (-t[1], t[0]))[:5],
            "downstream": sorted(down.get(cid, []), key=lambda t: (-t[1], t[0]))[:5],
        })
    feats.sort(key=lambda f: (-f["size"], f["anchor"]))
    return feats


def _auto_name(feat: dict) -> str:
    """Display name for a narrative-less feature: dominant file stems of its top members."""
    stems = []
    for m in feat["members"][:3]:
        stem = Path(m.get("file") or "?").stem
        if stem not in stems:
            stems.append(stem)
    return " / ".join(stems[:2]) or f"feature {feat['community']}"


def _feature_hash(repo: Path, feat: dict) -> str:
    return freshness._hash_paths(Path(repo), [Path(repo) / f for f in feat["files"]])[0]


# ---------- narrative store (faq.json) ----------

def read_faq(out: Path) -> dict:
    data = driver.read_layer(out, "faq")
    return data or {"schema_version": 1, "layer": "faq", "project": {}, "features": [], "stats": {}}


def write_faq(faq: dict, out: Path) -> dict:
    data = {"schema_version": 1, "layer": "faq",
            "project": faq.get("project", {}),
            "features": sorted(faq.get("features", []), key=lambda f: f["anchor"]),
            "stats": faq.get("stats", {})}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    driver._write_json(out / "faq.json", data)
    return {"faq": str(out / "faq.json"), "features": len(data["features"])}


def faq_state(out: Path, repo: Path, structural: dict) -> dict:
    """Per-feature narrative state vs the manifest baseline: missing / stale / fresh, plus
    narratives whose anchors vanished (orphaned). Pure read — the gate and prep share it."""
    out, repo = Path(out), Path(repo)
    feats = feature_map(structural)
    faq = read_faq(out)
    by_anchor = {f["anchor"]: f for f in faq.get("features", [])}
    base = (freshness.read_manifest(out) or {}).get("faq", {}).get("features", {})
    missing, stale, fresh = [], [], []
    for feat in feats:
        if feat["anchor"] not in by_anchor:
            missing.append(feat)
        elif base.get(feat["anchor"], {}).get("hash") != _feature_hash(repo, feat):
            stale.append(feat)
        else:
            fresh.append(feat)
    anchors = {f["anchor"] for f in feats}
    orphaned = sorted(a for a in by_anchor if a not in anchors)
    return {"adopted": bool(faq.get("features") or faq.get("project")),
            "project_missing": not faq.get("project"),
            "missing": missing, "stale": stale, "fresh": fresh, "orphaned": orphaned}


# ---------- prep -> payloads -> merge (mirrors the semantic overlay loop) ----------

def prep_faq(out: Path, repo: Path, structural: dict) -> dict:
    """Write one narrative task per feature NEEDING work (missing or stale narrative) plus a
    project-level task, under <out>/.cache/faq/. Identity metadata + existing narrative only —
    no source code crosses the boundary (R7, same discipline as semantic-prep)."""
    out, repo = Path(out), Path(repo)
    state = faq_state(out, repo, structural)
    faq = read_faq(out)
    by_anchor = {f["anchor"]: f for f in faq.get("features", [])}
    base = out / ".cache" / "faq"
    if base.exists():
        shutil.rmtree(base)
    tasks_dir = base / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    readme = repo / "README.md"
    (tasks_dir / "project.json").write_text(json.dumps({
        "task": "project",
        "instruction": ("Write the project narrative: what (one paragraph: what this is), "
                        "purpose (the problem it solves), value (why it matters). Payload: "
                        '{"project": {"what", "purpose", "value"}} in payloads/project.json.'),
        "existing": faq.get("project", {}),
        "readme_head": readme.read_text(errors="ignore")[:4000] if readme.exists() else "",
    }, indent=1))
    todo = state["missing"] + state["stale"]
    for feat in todo:
        (tasks_dir / f"{feat['anchor'].replace(':', '_')}.json").write_text(json.dumps({
            "task": "feature",
            "instruction": ("Write this feature's narrative from its graph facts + your "
                            "knowledge of the code. Payload: {\"anchor\", \"name\" (short "
                            "human name), \"concept\" (what it is), \"functionality\" (what "
                            "it does)} appended to payloads/<anything>.json {\"features\": [...]}."),
            "anchor": feat["anchor"], "community": feat["community"],
            "members": feat["members"], "files": feat["files"],
            "inputs": feat["inputs"], "outputs": feat["outputs"],
            "existing": by_anchor.get(feat["anchor"], {}),
        }, indent=1))
    return {"tasks_dir": str(tasks_dir), "payloads_dir": str(base / "payloads"),
            "project_task": True, "feature_tasks": len(todo),
            "fresh": len(state["fresh"]), "orphaned": state["orphaned"]}


def merge_faq(out: Path, repo: Path, structural: dict) -> dict:
    """Merge <out>/.cache/faq/payloads/*.json into faq.json: project narrative replaces wholesale;
    feature narratives upsert by anchor (unknown anchors are reported, never merged); orphaned
    narratives (anchor gone from the graph) are dropped + reported. Stamps the per-feature
    baseline into the manifest and deletes the scratch (never-touches-main contract)."""
    out, repo = Path(out), Path(repo)
    feats = feature_map(structural)
    anchors = {f["anchor"]: f for f in feats}
    faq = read_faq(out)
    by_anchor = {f["anchor"]: f for f in faq.get("features", []) if f["anchor"] in anchors}
    dropped_orphans = sorted(f["anchor"] for f in faq.get("features", [])
                             if f["anchor"] not in anchors)
    pdir = out / ".cache" / "faq" / "payloads"
    unknown, merged = [], 0
    for pf in sorted(pdir.glob("*.json")) if pdir.exists() else []:
        try:
            p = json.loads(pf.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(p.get("project"), dict):
            faq["project"] = {k: v for k, v in p["project"].items() if k in _PROJECT_KEYS}
        for f in p.get("features", []) or []:
            a = f.get("anchor")
            if a not in anchors:
                unknown.append(a)
                continue
            entry = {"anchor": a, **{k: f[k] for k in _NARRATIVE_KEYS if f.get(k)}}
            by_anchor[a] = {**by_anchor.get(a, {}), **entry}
            merged += 1
    faq["features"] = list(by_anchor.values())
    faq["stats"] = {"features": len(by_anchor), "merged": merged,
                    "unknown_anchors": sorted(set(a for a in unknown if a)),
                    "dropped_orphans": dropped_orphans}
    written = write_faq(faq, out)
    m = freshness.read_manifest(out) or {}
    # baseline carries the FILE LISTS too, so the pre-push/Stop gates can recompute staleness
    # with freshness alone (stdlib, no graph/networkx) — the bare-python3 hook discipline
    m["faq"] = {"features": {f["anchor"]: {"hash": _feature_hash(repo, f), "files": f["files"]}
                             for f in feats}}
    (Path(out) / freshness.MANIFEST).write_text(json.dumps(m, indent=2))
    if (out / ".cache" / "faq").exists():
        shutil.rmtree(out / ".cache" / "faq")
    return {**written, **faq["stats"]}


# ---------- render (deterministic, LLM-free — what CI runs) ----------

def render_faq(out: Path, repo: Path, structural: dict, health_report: dict | None = None) -> str:
    """PROJECT_FAQ.md: committed narrative + freshly computed quantitative facts. Content-
    deterministic — no timestamps, sorted everywhere — so the CI commit-back is diff-gated."""
    out, repo = Path(out), Path(repo)
    feats = feature_map(structural)
    faq = read_faq(out)
    by_anchor = {f["anchor"]: f for f in faq.get("features", [])}
    names = {f["community"]: (by_anchor.get(f["anchor"], {}).get("name") or _auto_name(f))
             for f in feats}
    proj = faq.get("project", {})
    L = [f"# 📒 PROJECT_FAQ — {Path(repo).resolve().name}", "",
         "_Deterministic graph facts + committed narrative "
         "([how this file is produced](docs/setup.md))._", "",
         "## What is this project?", ""]
    if proj:
        for k in ("what", "purpose", "value"):
            if proj.get(k):
                L += [f"**{k.capitalize()}.** {proj[k]}", ""]
    else:
        L += ["_(narrative pending — run `cg-graphify-bridge faq-prep`, fill the payloads, "
              "then `faq-merge`)_", ""]
    L += ["## What are the features?", ""]
    for feat in feats:
        n = by_anchor.get(feat["anchor"], {})
        L.append(f"### {names[feat['community']]} — {feat['size']} components "
                 f"(community {feat['community']})")
        L.append("")
        if n.get("concept"):
            L += [n["concept"], ""]
        if n.get("functionality"):
            L += [n["functionality"], ""]
        if not n:
            L += ["_(narrative pending)_", ""]
        L.append("- **Key components:** " +
                 ", ".join(f"`{m['label']}`" for m in feat["members"][:6]))
        if feat["upstream"]:
            L.append("- **Used by:** " +
                     ", ".join(f"{names.get(c, c)} ({w})" for c, w in feat["upstream"]))
        if feat["downstream"]:
            L.append("- **Depends on:** " +
                     ", ".join(f"{names.get(c, c)} ({w})" for c, w in feat["downstream"]))
        if feat["inputs"]:
            L.append("- **Public surface:** " + ", ".join(f"`{i}`" for i in feat["inputs"][:8]))
        if feat["outputs"]:
            L.append("- **External dependencies:** " +
                     ", ".join(f"`{o}`" for o in feat["outputs"][:6]))
        L.append("")
    if health_report:
        d = health_report["debt"]
        L += ["## Where is the technical debt?", "",
              f"**Score {d['score']}** (0 = clean → 1 = heavy) · " +
              " · ".join(f"{k}: {v}" for k, v in d["by_type"].items()), ""]
        if d["by_feature"]:
            L += ["| Feature | Debt items |", "|---|--:|"]
            L += [f"| {names.get(r['feature'], r['feature'])} | {r['debt_items']} |"
                  for r in d["by_feature"][:8]]
            L.append("")
        if d["by_component"]:
            L += ["| Component | Debt items |", "|---|--:|"]
            L += [f"| `{r['component']}` | {r['debt_items']} |" for r in d["by_component"][:8]]
            L.append("")
    L += ["---", "",
          "_Generated by [cg-graphify-bridge](https://github.com/evannordinpro/cg-graphify-bridge) "
          "from the committed knowledge graph. Quantitative facts are rebuilt by CI each graph "
          "build; the narrative lives in `graphify-out/faq.json` and is refreshed by the dev's "
          "agent only when the relevant feature's code changes._"]
    return "\n".join(L) + "\n"
