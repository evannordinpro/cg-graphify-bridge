"""cg-graphify-bridge CLI.

  build          codegraph-index REPO + structural fuse -> graphify-out/
  semantic-prep  write per-doc subagent context tasks under <out>/.cache/semantic/
  semantic-merge merge subagent payloads -> fused graph (doc->code overlay) + clean scratch

Structural fusion is local (no egress). The semantic step runs via Claude subagents
(the /graphify overlay path) that fill payloads between prep and merge — no /tmp.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# NOTE: `driver` (graphify/networkx) is imported lazily inside the build/semantic
# commands so the lightweight `status` / `install-hook` commands — which the git
# freshness hook invokes — run on a bare python3 with no heavy deps.
# The split modules below are stdlib-only, so importing them keeps that property.
# They are re-exported here (cli.<name>) as the package's historical surface; new
# code should import doctor/hooks/scaffold directly.
from .doctor import (  # noqa: F401
    _check_conflicts,
    _codegraph_bin,
    _detect_codegraph_mcp,
    _detect_graphify_rebuild_hooks,
    _detect_semantic_schema_clash,
    doctor_report,
)
from .hooks import (  # noqa: F401
    _PREPUSH_MARK,
    _hook_disabled,
    _hook_repo,
    install_freshness_hooks,
    install_prepush_hook,
)
from .scaffold import (  # noqa: F401
    _AGENTS_MARK,
    _GITATTR_MARK,
    _append_once,
    _read_template,
    _resolve_hook_cmd,
    _write_agents_md,
    _write_gitattributes,
    configure_merge_driver,
    write_ci_workflow,
    write_claude_hooks,
)


def _substrate_version(substrate: str, repo: Path) -> str | None:
    """Version of the EXTRACTION substrate, for the manifest stamp + drift detection (R6).
    TS -> the target repo's typescript; else -> the codegraph CLI (`codegraph --version`).
    Best-effort: returns None if it can't be determined (drift check then skips)."""
    if substrate == "ts":
        try:
            pj = json.loads((repo / "node_modules" / "typescript" / "package.json").read_text())
            return f"typescript@{pj.get('version')}" if pj.get("version") else None
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
    binp = _codegraph_bin()
    if not binp:
        return None
    try:
        base = ["node", binp] if binp.endswith(".js") else [binp]
        r = subprocess.run(base + ["--version"], capture_output=True, text=True, timeout=15)
        ver = (r.stdout or "").strip().splitlines()[0].strip() if r.returncode == 0 and r.stdout else None
        return f"codegraph@{ver}" if ver else None
    except (OSError, subprocess.SubprocessError):
        return None


def _index(repo: Path) -> Path:
    binp = _codegraph_bin()
    if not binp:
        raise SystemExit("codegraph CLI not found — `npm i -g @colbymchenry/codegraph` (or set $CODEGRAPH_BIN)")
    cgdir = repo / ".codegraph"
    base = ["node", binp] if binp.endswith(".js") else [binp]
    sub = ["index"] if cgdir.exists() else ["init", "-i"]
    r = subprocess.run(base + sub, cwd=str(repo), stdin=subprocess.DEVNULL,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"codegraph index failed (rc={r.returncode}):\n{(r.stderr or r.stdout)[-500:]}")
    db = cgdir / "codegraph.db"
    if not db.exists():
        raise SystemExit(f"codegraph produced no DB at {db}")
    return db


def _require_db(repo: Path) -> Path:
    db = repo / ".codegraph" / "codegraph.db"
    if not db.exists():
        raise SystemExit("no codegraph index — run `cg-graphify-bridge build <repo>` first")
    return db


_COMMON_SCOPES = ["apps", "services", "packages", "infra"]


def _default_scopes(repo: Path) -> list[str]:
    present = [d for d in _COMMON_SCOPES if (repo / d).is_dir()]
    if present:
        return present
    if (repo / "src").is_dir():
        return ["src"]
    return ["."]


def _has_ts_sources(base: Path) -> bool:
    for p in base.rglob("*.ts"):
        if "node_modules" not in p.parts and not p.name.endswith(".d.ts"):
            return True
    return False


def _detect_substrate(repo: Path, scopes: list[str]) -> str:
    """auto → 'ts' when a tsconfig + real .ts/.tsx sources exist; else 'codegraph'."""
    has_tsconfig = (repo / "tsconfig.base.json").exists() or (repo / "tsconfig.json").exists()
    if has_tsconfig and any(_has_ts_sources(repo / s) for s in scopes if (repo / s).is_dir()):
        return "ts"
    return "codegraph"


def _adapt_repo(repo: Path, substrate: str, scopes: list[str], *, build_index: bool):
    """Route to the right substrate -> (AdaptResult, resolved_substrate). Shared by build and
    the semantic commands so doc->code edges key against the SAME node set the graph activates
    on. TS re-runs the type-checker extractor; codegraph indexes (build) or requires a prior build."""
    sub = substrate if substrate != "auto" else _detect_substrate(repo, scopes)
    if sub == "ts":
        from . import ts_substrate
        return ts_substrate.adapt_ts(repo, scopes), sub
    from . import adapter, py_calls
    db = _index(repo) if build_index else _require_db(repo)
    # codegraph resolves same-file Python calls only — supplement cross-module call edges
    # (deterministic stdlib-ast pass; no-op for non-Python node sets)
    return py_calls.enrich(repo, adapter.adapt(db)), sub


def build_repo(repo: Path, out_name: str, *, substrate: str = "auto", scopes: str | None = None,
               prune_orphans: bool = False, no_fold: bool = False, activate: bool = False) -> dict:
    """Build the structural layer for `repo` -> <repo>/<out_name>/. Shared by the `build` and
    `init` commands. Returns a result dict (no printing)."""
    from . import driver, engine, freshness
    out = repo / out_name
    prior = freshness.read_manifest(out)
    # KD14: refuse to overwrite a graph built by a different clustering engine (would flip
    # community ids + churn the committed artifact). Fail fast — before any indexing work.
    engine.check_engine_compat(prior)
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()] if scopes else _default_scopes(repo)
    res, sub = _adapt_repo(repo, substrate, scope_list, build_index=True)
    sub_version = _substrate_version(sub, repo)
    drift = engine.check_substrate_drift(prior, sub, sub_version)
    if drift:  # advisory, not fatal — substrate version drift MAY change extraction (R5/R6)
        print(f"⚠ {drift}", file=sys.stderr)
    fused = driver.build_fused(res=res, prune_orphans=prune_orphans, fold_singletons=not no_fold)
    written = driver.write_artifact(fused, out)
    stamp = {**engine.detect_engine(), "substrate": sub, "substrate_version": sub_version}
    manifest = freshness.write_manifest(out, repo, scope_list, engine_stamp=stamp)
    if activate:
        (out / ".cg_overlay").write_text(f"{sub}-substrate overlay — built by cg-graphify-bridge\n")
    return {**written, "out_dir": str(out), "substrate": sub, "substrate_version": sub_version,
            "scopes": scope_list, "engine": manifest.get("engine"),
            "schema_version": manifest.get("schema_version"),
            "communities": len(fused["communities"]), "god_nodes": len(fused["god_nodes"]),
            "overlay_activated": bool(activate), "manifest_files": manifest["files"],
            "adapter_stats": fused["adapt"].stats}


def _build(args: argparse.Namespace) -> None:
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        raise SystemExit(f"not a directory: {repo}")
    print(json.dumps(build_repo(repo, args.out, substrate=args.substrate, scopes=args.scopes,
                                prune_orphans=args.prune_orphans, no_fold=args.no_fold,
                                activate=args.activate), indent=2, default=str))


def _refresh_cmds(repo: Path, out_name: str, structural_stale: bool, semantic_stale: bool) -> dict:
    """The exact, copy-pasteable commands to make each layer fresh again (R4 'tell them exactly
    what to run'). Structural is CI-owned -> pull; semantic is dev-owned -> prep/merge/commit."""
    advice = {}
    if structural_stale:
        advice["structural"] = (f"git pull   # CI rebuilds structural.json on the default branch; "
                                 f"or locally: cg-graphify-bridge build {repo} --out {out_name}")
    if semantic_stale:
        advice["semantic"] = (
            f"cg-graphify-bridge semantic-prep {repo} --out {out_name}"
            f"   # then have Claude fill payloads (/graphify overlay), then:   "
            f"cg-graphify-bridge semantic-merge {repo} --out {out_name}"
            f"   # then: git add {out_name}/semantic.json")
    return advice


def _status(args: argparse.Namespace) -> dict:
    from . import freshness
    repo = Path(args.repo).resolve()
    out = repo / args.out
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()] if args.scopes else None
    st = freshness.compute_status(out, repo, scopes)
    if args.check:  # legacy git-hook compatibility: also refresh the .cg_stale structural marker
        freshness.check_stale(out, repo, scopes)
    advice = _refresh_cmds(repo, args.out,
                           st.get("structural", {}).get("state") == "stale",
                           st.get("semantic", {}).get("state") == "stale")
    # FR4: flag a graphify-native semantic.json squatting on the bridge's committed overlay path.
    warnings = [w for w in (_detect_semantic_schema_clash(out),) if w]
    payload = {"repo": str(repo), "out_dir": str(out), **st, "advice": advice, "warnings": warnings}
    if not args.quiet:
        print(json.dumps(payload, indent=2))
    return payload


def _install_hook(args: argparse.Namespace) -> None:
    info = install_freshness_hooks(Path(args.repo).resolve(), args.out,
                                   src=args.src, write_husky=args.write_husky)
    print(json.dumps(info, indent=2))


def _load_structural(out: Path) -> tuple:
    """Read the committed structural layer + reconstruct an AdaptResult from it (R4/KD7).
    The semantic commands consume this instead of re-extracting + re-clustering, so doc->code
    edges key against the CI-built composite ids and a dev never runs community detection."""
    from . import adapter, driver
    structural = driver.read_layer(out, "structural")
    if structural is None:
        raise SystemExit(
            f"no structural.json in {out} — pull the CI-built structural layer (new branches "
            f"inherit it from the default branch) or run `cg-graphify-bridge build {out.parent}` first.")
    return structural, adapter.from_structural(structural)


def _semantic_prep(args: argparse.Namespace) -> None:
    from . import driver, semantic
    repo = Path(args.repo).resolve()
    out = repo / args.out
    structural, res = _load_structural(out)
    # degree ranking only — NO build_fused / cluster.cluster (R4: consume committed communities)
    info = semantic.prep_tasks(res, {"graph": driver.degree_graph(structural)}, repo, out,
                               max_nodes=args.max_nodes, max_docs=args.max_docs, doc_filter=args.filter,
                               structural=structural)
    print(json.dumps({"tasks": len(info["tasks"]), "code_nodes": info["code_nodes"],
                      "dispatch_candidates": info["dispatch_candidates"],
                      "tasks_dir": str(info["tasks_dir"]), "payloads_dir": str(info["payloads_dir"]),
                      "consumed": "structural.json (no re-cluster)",
                      "next": "for each tasks/<id>.json a subagent reads {doc, code_nodes} and writes "
                              "payloads/<id>.json {nodes,edges}; review dispatch_candidates.json and "
                              "confirm real dynamic wiring as `dispatches` edges; then run `semantic-merge`."},
                     indent=2))


def _semantic_merge(args: argparse.Namespace) -> None:
    from . import driver, freshness, semantic
    repo = Path(args.repo).resolve()
    out = repo / args.out
    _, res = _load_structural(out)
    combined = semantic.merge_payloads(res, out)        # edges keyed to structural composite ids
    written = driver.write_semantic(combined, out)      # commit the dev-owned semantic layer
    materialized = driver.materialize(out)              # refresh the local (gitignored) fused graph.json
    base = freshness.write_semantic_freshness(out, repo)  # KD9: stamp the doc/linked-file baseline
    if args.activate:
        (out / ".cg_overlay").write_text("semantic overlay — cg-graphify-bridge\n")
    if not args.keep_scratch:
        shutil.rmtree(out / ".cache" / "semantic", ignore_errors=True)
    print(json.dumps({**combined["stats"], **written, **materialized, "out_dir": str(out),
                      "consumed": "structural.json (no re-cluster)",
                      "semantic_baseline": {"docs": base["docs_count"], "linked": base["linked_count"]},
                      "overlay_activated": bool(args.activate)}, indent=2, default=str))


def _check_semantic(args: argparse.Namespace) -> None:
    """Exit non-zero when the semantic overlay is behind the docs/linked code (R4/R7). With
    --require-committed (the Stop-hook gate) ALSO block when semantic.json has uncommitted
    changes — i.e. refreshed but not yet committed with the change-set. Fresh+committed -> 0."""
    from . import freshness
    repo = Path(args.repo).resolve()
    out = repo / args.out
    sem = freshness.compute_status(out, repo).get("semantic", {})
    stale = sem.get("state") == "stale"
    uncommitted = (args.require_committed and (out / "semantic.json").exists()
                   and freshness.is_uncommitted(repo, out / "semantic.json"))
    blocked = stale or uncommitted
    reason = ("semantic overlay is stale — docs or linked code changed since the last merge"
              if stale else
              "semantic.json has uncommitted changes — commit it with your change-set"
              if uncommitted else None)
    advice = _refresh_cmds(repo, args.out, False, True)["semantic"] if blocked else None
    if not args.quiet:
        print(json.dumps({"repo": str(repo), "semantic": sem.get("state"), "blocked": blocked,
                          "reason": reason, "refresh": advice}, indent=2))
    if blocked:
        raise SystemExit(1)


def _doctor(args: argparse.Namespace) -> None:
    repo = Path(args.repo).resolve() if args.repo else None
    rep = doctor_report(repo)
    print(json.dumps(rep, indent=2))
    if args.strict and not rep["ok"]:
        raise SystemExit(1)


def _merge_driver(args: argparse.Namespace) -> None:
    """git merge driver for semantic.json: UNION both branches' overlays (R8/KD10). Two PRs that
    each added doc->code edges merge cleanly — nodes deduped by id, edges by (source,target,
    relation), deterministically sorted. Result written to OURS (%A); exit 0 = resolved. A
    union is over-inclusive by design; any edge to code one branch removed is pruned as dangling
    at the next semantic-merge/materialize."""
    from .engine import SCHEMA_VERSION

    def _load(p):
        try:
            return json.loads(Path(p).read_text())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {}

    a, b = _load(args.ours), _load(args.theirs)
    nodes = {n["id"]: n for n in a.get("semantic_nodes", [])}
    nodes.update({n["id"]: n for n in b.get("semantic_nodes", [])})

    def ekey(e):
        return (e.get("source", ""), e.get("target", ""), e.get("relation", ""))
    edges = {ekey(e): e for e in a.get("semantic_edges", [])}
    edges.update({ekey(e): e for e in b.get("semantic_edges", [])})
    merged = {
        "schema_version": a.get("schema_version") or b.get("schema_version") or SCHEMA_VERSION,
        "layer": "semantic",
        "semantic_nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "semantic_edges": sorted(edges.values(), key=ekey),
        "stats": {"merged": "union", "nodes": len(nodes), "edges": len(edges)},
    }
    Path(args.ours).write_text(json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    # exit 0 -> git treats the conflict as resolved


def _init(args: argparse.Namespace) -> None:
    """One-shot repo setup (KD9/KD10/KD12/KD13): first build (structural + gitignore + engine
    stamp), AGENTS.md graph-consumption contract, semantic.json merge-driver (.gitattributes +
    git config), the build-on-PR-branch CI workflow, the Claude SessionStart/Stop hooks, and the
    git freshness hooks (best-effort). Idempotent."""
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        raise SystemExit(f"not a directory: {repo}")
    built = build_repo(repo, args.out, substrate=args.substrate, scopes=args.scopes)
    agents = _write_agents_md(repo, args.out)
    gattr = _write_gitattributes(repo, args.out)
    ci = write_ci_workflow(repo)
    claude = write_claude_hooks(repo, args.out)
    merge_drv = configure_merge_driver(repo, args.out)
    try:
        hooks = install_freshness_hooks(repo, args.out)
    except SystemExit as e:  # not a git repo etc. — never fatal for init
        hooks = {"skipped": str(e)}
    try:
        prepush = install_prepush_hook(repo, args.out)
    except SystemExit as e:
        prepush = {"skipped": str(e)}
    print(json.dumps({"initialized": str(repo), "built": built, "agents_md": str(agents),
                      "gitattributes": str(gattr), "merge_driver": merge_drv, "ci_workflow": ci,
                      "claude_hooks": claude, "git_hooks": hooks, "pre_push": prepush},
                     indent=2, default=str))


def _materialize(args: argparse.Namespace) -> None:
    from . import driver
    repo = Path(args.repo).resolve()
    print(json.dumps(driver.materialize(repo / args.out), indent=2, default=str))


def _serve(args: argparse.Namespace) -> None:
    """Opt-in (FR6): launch graphify's MCP server OVER THE COMMITTED graph (materialize the fused
    graph.json first if absent). Never auto-installed/registered — run on demand for repeat-query
    (≥10/session) graph workflows. Serves the bridge's committed graph.json, NOT codegraph's live db."""
    from . import driver
    repo = Path(args.repo).resolve()
    out = repo / args.out
    graph = out / "graph.json"
    if not graph.exists():
        if not (out / "structural.json").exists():
            raise SystemExit(f"no committed graph in {out} — run `cg-graphify-bridge build {repo}` first")
        driver.materialize(out)
    try:
        from graphify import serve as gserve
    except ImportError as e:  # graphify is a hard dep — should never happen on a real install
        raise SystemExit(f"graphify not importable — reinstall cg-graphify-bridge ({e})")
    gserve.serve(str(graph))


def _health(args: argparse.Namespace) -> None:
    """Structural + semantic + combined health metrics over the committed graph (advisory)."""
    from . import health as _h
    repo = Path(args.repo).resolve()
    res = _h.health(repo / args.out, include_tests=args.include_tests, repo=repo)
    print(json.dumps(res, indent=2, default=str) if args.json else _h.render_report(res))


def _benchmark(args: argparse.Namespace) -> None:
    """Token-reduction of graph-guided retrieval vs a naive file-read baseline, per query class."""
    from . import benchmark as _b
    repo = Path(args.repo).resolve()
    res = _b.benchmark(repo / args.out, repo)
    print(json.dumps(res, indent=2, default=str) if args.json else _b.render_report(res))


def _query_cmd(args: argparse.Namespace) -> None:
    """callers / callees / impact over the committed graph. Ambiguous or unknown symbol exits 2."""
    from . import driver
    from . import query as _q
    repo = Path(args.repo).resolve()
    structural = driver.read_layer(repo / args.out, "structural")
    if structural is None:
        raise SystemExit(f"no structural.json in {repo / args.out} — build the graph first (or pull it)")
    fn = {"callers": _q.callers, "callees": _q.callees, "impact": _q.impact}[args.cmd]
    res = fn(structural, args.symbol, depth=args.depth)
    print(json.dumps(res, indent=2, default=str) if args.json else _q.render(res))
    if res["candidates"] or res["resolved"] is None:   # ambiguous / not found -> non-zero
        raise SystemExit(2)


def _insights(args: argparse.Namespace) -> None:
    """Render the versioned showcase report (health + benchmark) as GitHub-native markdown."""
    from . import insights as _i
    repo = Path(args.repo).resolve()
    md = _i.render_markdown(_i.build_insights(repo / args.out, repo))
    if args.out_file:
        dest = Path(args.out_file)
        dest = dest if dest.is_absolute() else repo / dest
        dest.write_text(md)
        print(f"wrote {dest}")
    else:
        print(md)


# ---------- Phase 6: PROJECT_FAQ (quantitative facts + dev-Claude narrative) ----------

def _faq_prep(args: argparse.Namespace) -> None:
    from . import faq
    repo = Path(args.repo).resolve()
    out = repo / args.out
    structural, _ = _load_structural(out)
    info = faq.prep_faq(out, repo, structural)
    print(json.dumps({**info, "consumed": "structural.json (no re-cluster)",
                      "next": "fill payloads/project.json + per-feature narrative payloads, "
                              "then run `faq-merge`."}, indent=2))


def _faq_merge(args: argparse.Namespace) -> None:
    from . import faq
    repo = Path(args.repo).resolve()
    out = repo / args.out
    structural, _ = _load_structural(out)
    info = faq.merge_faq(out, repo, structural)
    print(json.dumps({**info, "next": f"git add {args.out}/faq.json  # then commit; "
                                      "CI renders PROJECT_FAQ.md from it"}, indent=2))


def _faq_render(args: argparse.Namespace) -> None:
    from . import faq, health as _h
    repo = Path(args.repo).resolve()
    out = repo / args.out
    structural, _ = _load_structural(out)
    md = faq.render_faq(out, repo, structural, _h.health(out, repo=repo))
    if args.out_file:
        dest = Path(args.out_file)
        dest = dest if dest.is_absolute() else repo / dest
        dest.write_text(md)
        print(f"wrote {dest}")
    else:
        print(md)


def _check_faq(args: argparse.Namespace) -> None:
    """The KD8 gate predicate: exit non-zero ONLY when a stamped FAQ baseline says a feature's
    narrative went stale. Fail-open by construction: un-adopted repos (no baseline), the escape
    hatch, and any internal error all exit 0 — a guard error must never brick a push/session."""
    try:
        from . import freshness
        if _hook_disabled():
            raise SystemExit(0)
        repo = Path(args.repo).resolve()
        st = freshness.faq_status(repo / args.out, repo)
        if st["state"] != "stale":
            raise SystemExit(0)
        if not args.quiet:
            print(f"cg-graphify-bridge: PROJECT_FAQ narrative is stale for "
                  f"{len(st['stale_features'])} feature(s) — run `cg-graphify-bridge faq-prep "
                  f"{repo}` → fill the payloads → `cg-graphify-bridge faq-merge {repo}`, "
                  f"commit {args.out}/faq.json, then re-push.")
        raise SystemExit(1)
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)  # fail open


# ---------- Claude hooks (in-process subcommands; .claude/settings.json wires them) ----------
# Thin: SessionStart surfaces freshness, Stop gates on a stale/uncommitted overlay. Both honor
# the escape hatch and FAIL OPEN — a guard that errors must never brick a session (R7/R10).

def _hook_sessionstart(args: argparse.Namespace) -> None:
    if _hook_disabled():
        return
    try:
        from . import driver, freshness
        repo = _hook_repo()
        out = repo / args.out
        # materialize the gitignored fused cache if missing (the consumer reads graph.json)
        if (out / "structural.json").exists() and not (out / "graph.json").exists():
            try:
                driver.materialize(out)
            except Exception:
                pass
        st = freshness.compute_status(out, repo)
        advice = _refresh_cmds(repo, args.out,
                               st.get("structural", {}).get("state") == "stale",
                               st.get("semantic", {}).get("state") == "stale")
        if not advice:
            return  # fresh -> silent
        msg = "cg-graphify-bridge — graph freshness:\n" + \
            "\n".join(f"  • {k}: {v}" for k, v in advice.items())
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                  "additionalContext": msg}}))
    except Exception:
        return  # fail open


def _hook_stop(args: argparse.Namespace) -> None:
    if _hook_disabled():
        return
    try:
        from . import freshness
        repo = _hook_repo()
        out = repo / args.out
        sem = freshness.compute_status(out, repo).get("semantic", {})
        stale = sem.get("state") == "stale"
        uncommitted = (out / "semantic.json").exists() and \
            freshness.is_uncommitted(repo, out / "semantic.json")
        faq_stale = freshness.faq_status(out, repo).get("state") == "stale"
        if not (stale or uncommitted or faq_stale):
            return  # allow stop
        if stale or uncommitted:
            reason = ("the semantic overlay is stale — docs or linked code changed since the last merge"
                      if stale else "semantic.json has uncommitted changes (refreshed but not committed)")
            cmd = _refresh_cmds(repo, args.out, False, True)["semantic"]
        else:
            reason = "the PROJECT_FAQ narrative is stale — a feature's code changed since faq-merge"
            cmd = (f"cg-graphify-bridge faq-prep {repo}   # fill the payloads, then: "
                   f"cg-graphify-bridge faq-merge {repo}   # then: git add {args.out}/faq.json")
        msg = (f"cg-graphify-bridge: {reason}. Refresh and commit it before ending:\n{cmd}\n"
               f"(escape: `export CG_BRIDGE_DISABLE=1` or `touch ~/.claude/state/cg-bridge/OFF`)")
        print(json.dumps({"decision": "block", "reason": msg}))
    except Exception:
        return  # fail open


def _pin_hashseed_for(cmd: str) -> None:
    """Clustering tie-breaking (networkx Louvain / graspologic Leiden) is sensitive to Python's
    hash randomization: an unpinned PYTHONHASHSEED makes the partition — and thus structural.json
    — vary run-to-run, defeating the committed-artifact determinism contract (R5). For the commands
    that cluster, re-exec ONCE under a fixed seed (the RNG seed alone is not enough; set-iteration
    order inside the algorithm must also be pinned). Empirically: any fixed seed -> identical bytes.
    Non-clustering commands (status/check-semantic/doctor/semantic-*) are left untouched — no exec
    overhead on the frequently-invoked hook path."""
    if cmd in ("build", "init") and os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        argv = [sys.executable, "-m", "cg_graphify_bridge", *sys.argv[1:]]
        if os.name == "nt":  # Windows execv doesn't replace the process — spawn + propagate rc
            raise SystemExit(subprocess.run(argv).returncode)
        os.execv(sys.executable, argv)


def main() -> None:
    if len(sys.argv) > 1:
        _pin_hashseed_for(sys.argv[1])
    p = argparse.ArgumentParser(prog="cg-graphify-bridge")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="index REPO (ts type-checker or codegraph) + fuse -> graphify-out/")
    b.add_argument("repo")
    b.add_argument("--out", default="graphify-out", help="output dir, relative to REPO")
    b.add_argument("--substrate", choices=["auto", "ts", "codegraph"], default="auto",
                   help="auto routes TS repos to the type-aware substrate, else codegraph")
    b.add_argument("--scopes", default=None,
                   help="comma-separated dirs to scan (default: apps,services,packages,infra | src | .)")
    b.add_argument("--prune-orphans", action="store_true",
                   help="drop non-file nodes with zero edges (extraction artifacts)")
    b.add_argument("--no-fold", action="store_true",
                   help="disable folding singleton communities into their file locality")
    b.add_argument("--activate", action="store_true",
                   help="drop <out>/.cg_overlay to activate overlay mode")
    b.set_defaults(func=_build)

    st = sub.add_parser("status", help="report structural + semantic freshness + exact refresh commands")
    st.add_argument("repo")
    st.add_argument("--out", default="graphify-out")
    st.add_argument("--scopes", default=None)
    st.add_argument("--check", action="store_true", help="also refresh the .cg_stale structural marker (git-hook compat)")
    st.add_argument("--quiet", action="store_true")
    st.set_defaults(func=_status)

    cs = sub.add_parser("check-semantic", help="exit non-zero if the semantic overlay is stale (Stop-hook gate)")
    cs.add_argument("repo")
    cs.add_argument("--out", default="graphify-out")
    cs.add_argument("--require-committed", action="store_true",
                    help="also fail if semantic.json has uncommitted changes (refreshed but not committed)")
    cs.add_argument("--quiet", action="store_true")
    cs.set_defaults(func=_check_semantic)

    dr = sub.add_parser("doctor", help="check runtime deps (node, codegraph, target typescript)")
    dr.add_argument("repo", nargs="?", default=None)
    dr.add_argument("--strict", action="store_true", help="exit non-zero if any dep is missing")
    dr.set_defaults(func=_doctor)

    ini = sub.add_parser("init", help="set up a repo: build + AGENTS.md + .gitattributes + CI + git hooks")
    ini.add_argument("repo")
    ini.add_argument("--out", default="graphify-out")
    ini.add_argument("--substrate", choices=["auto", "ts", "codegraph"], default="auto")
    ini.add_argument("--scopes", default=None)
    ini.set_defaults(func=_init)

    mz = sub.add_parser("materialize", help="(re)build the gitignored fused graph.json from the committed layers")
    mz.add_argument("repo")
    mz.add_argument("--out", default="graphify-out")
    mz.set_defaults(func=_materialize)

    sv = sub.add_parser("serve", help="opt-in: launch graphify's MCP over the COMMITTED graph (never auto-installed)")
    sv.add_argument("repo")
    sv.add_argument("--out", default="graphify-out")
    sv.set_defaults(func=_serve)

    hl = sub.add_parser("health", help="structural + semantic + combined codebase-health metrics (advisory)")
    hl.add_argument("repo")
    hl.add_argument("--out", default="graphify-out")
    hl.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of the report")
    hl.add_argument("--include-tests", action="store_true",
                    help="include test files (default: production code only)")
    hl.set_defaults(func=_health)

    bm = sub.add_parser("benchmark", help="token-reduction of graph-guided retrieval vs naive file-read (per query class)")
    bm.add_argument("repo")
    bm.add_argument("--out", default="graphify-out")
    bm.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of the report")
    bm.set_defaults(func=_benchmark)

    # Navigation over the committed graph (callers/callees/impact) — analytics digraph spine.
    for _name, _ddepth, _help in (
        ("callers", 1, "symbols that depend on SYMBOL (committed graph)"),
        ("callees", 1, "symbols SYMBOL depends on (committed graph)"),
        ("impact", None, "transitive blast radius if SYMBOL changes (committed graph)")):
        q = sub.add_parser(_name, help=_help)
        q.add_argument("repo")
        q.add_argument("symbol")
        q.add_argument("--out", default="graphify-out")
        q.add_argument("--depth", type=int, default=_ddepth,
                       help="hops to traverse" + (" (default: unbounded)" if _ddepth is None
                                                  else f" (default: {_ddepth})"))
        q.add_argument("--json", action="store_true")
        q.set_defaults(func=_query_cmd)

    ins = sub.add_parser("insights", help="render the versioned showcase report (health + benchmark) as markdown")
    ins.add_argument("repo")
    ins.add_argument("--out", default="graphify-out")
    ins.add_argument("--out-file", default=None, help="write markdown to this path (default: stdout)")
    ins.set_defaults(func=_insights)

    fp = sub.add_parser("faq-prep", help="write per-feature narrative tasks under <out>/.cache/faq/")
    fp.add_argument("repo")
    fp.add_argument("--out", default="graphify-out")
    fp.set_defaults(func=_faq_prep)

    fm = sub.add_parser("faq-merge", help="merge narrative payloads -> faq.json + stamp the per-feature baseline")
    fm.add_argument("repo")
    fm.add_argument("--out", default="graphify-out")
    fm.set_defaults(func=_faq_merge)

    fr = sub.add_parser("faq-render", help="render PROJECT_FAQ.md (deterministic; what CI runs)")
    fr.add_argument("repo")
    fr.add_argument("--out", default="graphify-out")
    fr.add_argument("--out-file", default=None, help="write markdown to this path (default: stdout)")
    fr.set_defaults(func=_faq_render)

    cf = sub.add_parser("check-faq", help="exit non-zero if the FAQ narrative is stale (the KD8 gate; fail-open)")
    cf.add_argument("repo")
    cf.add_argument("--out", default="graphify-out")
    cf.add_argument("--quiet", action="store_true")
    cf.set_defaults(func=_check_faq)

    hs = sub.add_parser("hook-sessionstart", help="Claude SessionStart hook: surface freshness + materialize")
    hs.add_argument("--out", default="graphify-out")
    hs.set_defaults(func=_hook_sessionstart)

    hp = sub.add_parser("hook-stop", help="Claude Stop hook: block on a stale/uncommitted semantic overlay")
    hp.add_argument("--out", default="graphify-out")
    hp.set_defaults(func=_hook_stop)

    md = sub.add_parser("merge-driver", help="git merge driver: union two semantic.json overlays")
    md.add_argument("ours")     # %A — result is written here
    md.add_argument("theirs")   # %B
    md.set_defaults(func=_merge_driver)

    ih = sub.add_parser("install-hook", help="install git post-commit/merge/checkout freshness hooks")
    ih.add_argument("repo")
    ih.add_argument("--out", default="graphify-out")
    ih.add_argument("--src", default=None,
                    help="PYTHONPATH src to bake into the hook (default: the cg-graphify-bridge command on PATH)")
    ih.add_argument("--write-husky", action="store_true",
                    help="for husky repos: actually create .husky/<hook> (committed — commit them yourself)")
    ih.set_defaults(func=_install_hook)

    def _substrate_flags(parser):
        # MUST match the activated `build` so doc->code edges key against the same node set
        parser.add_argument("--substrate", choices=["auto", "ts", "codegraph"], default="auto")
        parser.add_argument("--scopes", default=None,
                            help="comma-separated dirs (default: apps,services,packages,infra | src | .)")
        parser.add_argument("--prune-orphans", action="store_true")
        parser.add_argument("--no-fold", action="store_true")

    pp = sub.add_parser("semantic-prep", help="write per-doc subagent context tasks")
    pp.add_argument("repo")
    pp.add_argument("--out", default="graphify-out")
    pp.add_argument("--max-nodes", type=int, default=600, help="curated code nodes per task")
    pp.add_argument("--max-docs", type=int, default=None)
    pp.add_argument("--filter", default=None, help="only docs whose path contains this substring")
    _substrate_flags(pp)
    pp.set_defaults(func=_semantic_prep)

    pm = sub.add_parser("semantic-merge", help="merge subagent payloads -> fused graph")
    pm.add_argument("repo")
    pm.add_argument("--out", default="graphify-out")
    pm.add_argument("--activate", action="store_true")
    pm.add_argument("--keep-scratch", action="store_true", help="keep <out>/.cache/semantic/")
    _substrate_flags(pm)
    pm.set_defaults(func=_semantic_merge)

    args = p.parse_args()
    args.func(args)
