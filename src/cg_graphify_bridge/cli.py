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


def _codegraph_bin() -> str | None:
    env = os.environ.get("CODEGRAPH_BIN")
    if env and Path(env).exists():
        return env
    return shutil.which("codegraph")


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


def _scopes_of(args: argparse.Namespace, repo: Path) -> list[str]:
    return [s.strip() for s in args.scopes.split(",") if s.strip()] if getattr(args, "scopes", None) \
        else _default_scopes(repo)


def _adapt_repo(repo: Path, substrate: str, scopes: list[str], *, build_index: bool):
    """Route to the right substrate -> (AdaptResult, resolved_substrate). Shared by build and
    the semantic commands so doc->code edges key against the SAME node set the graph activates
    on. TS re-runs the type-checker extractor; codegraph indexes (build) or requires a prior build."""
    sub = substrate if substrate != "auto" else _detect_substrate(repo, scopes)
    if sub == "ts":
        from . import ts_substrate
        return ts_substrate.adapt_ts(repo, scopes), sub
    from . import adapter
    db = _index(repo) if build_index else _require_db(repo)
    return adapter.adapt(db), sub


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
    payload = {"repo": str(repo), "out_dir": str(out), **st, "advice": advice}
    if not args.quiet:
        print(json.dumps(payload, indent=2))
    return payload


_HOOK_MARK = "# cg-graphify-bridge freshness hook"


def install_freshness_hooks(repo: Path, out_name: str, *, src: str | None = None,
                            write_husky: bool = False) -> dict:
    """Install (or report) the git post-commit/merge/checkout freshness hooks. Returns an info
    dict (no printing) so both `install-hook` and `init` can use it. Raises SystemExit if not
    a git repo."""
    try:  # worktree-aware + honors core.hooksPath
        hp = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
                            capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise SystemExit(f"not a git repo (or git unavailable): {repo}") from e
    hooks_dir = Path(hp) if Path(hp).is_absolute() else (repo / hp)
    # Portable: resolve the repo root at hook runtime via `git rev-parse`, so the committed line
    # works on every clone. `|| true` => never blocks a git op. Default uses the pipx-installed
    # `cg-graphify-bridge` on PATH; `--src` overrides to a `python3 -m` form for unusual setups.
    if src:
        cmd = (f'PYTHONPATH="{src}" python3 -m cg_graphify_bridge status '
               f'"$(git rev-parse --show-toplevel)" --out "{out_name}" --check --quiet || true')
    else:
        cmd = (f'cg-graphify-bridge status "$(git rev-parse --show-toplevel)" '
               f'--out "{out_name}" --check --quiet || true')
    hooks = ("post-commit", "post-merge", "post-checkout")

    # Husky: core.hooksPath -> .husky/_ is GENERATED (regenerated on npm install) and the durable
    # hooks under .husky/ are committed config. Never silently rewrite that — report the snippet
    # to add unless the caller explicitly opts in with write_husky.
    if ".husky" in hooks_dir.parts:
        husky_root = hooks_dir.parent if hooks_dir.name == "_" else hooks_dir
        if not write_husky:
            return {"repo": str(repo), "detected": "husky (core.hooksPath=.husky/_)",
                    "action": "no files written — .husky/ is committed config you own",
                    "to_install": {"append_to_each": [str(husky_root / h) for h in hooks], "line": cmd},
                    "or_opt_in": "re-run with --write-husky (creates .husky/<hook>; commit them yourself)",
                    "note": "drops <out>/.cg_stale on source drift; a later `build` consumes it"}
        target_dir = husky_root
    else:
        target_dir = hooks_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    block = f"\n{_HOOK_MARK}\n{cmd}\n"
    installed, skipped = [], []
    for name in hooks:
        f = target_dir / name
        existing = f.read_text() if f.exists() else ""
        if _HOOK_MARK in existing:
            skipped.append(name)
            continue
        body = existing if existing.startswith("#!") else "#!/usr/bin/env sh\n" + existing
        f.write_text(body.rstrip("\n") + block)
        f.chmod(0o755)
        installed.append(name)
    return {"repo": str(repo), "hooks_dir": str(target_dir), "installed": installed,
            "already_present": skipped, "interpreter": "python3 (PATH)", "pythonpath": src,
            "note": "drops <out>/.cg_stale on source drift; `build` consumes it."}


def _install_hook(args: argparse.Namespace) -> None:
    info = install_freshness_hooks(Path(args.repo).resolve(), args.out,
                                   src=args.src, write_husky=args.write_husky)
    print(json.dumps(info, indent=2))


_PREPUSH_MARK = "# cg-graphify-bridge semantic pre-push gate"


def install_prepush_hook(repo: Path, out_name: str, *, write_husky: bool = False) -> dict:
    """Optional universal (non-Claude) gate: a git pre-push that fails when the semantic overlay
    is stale, with `git push --no-verify` as the escape (mirrors the repo's branch-name pre-push).
    Husky-aware: reports the snippet rather than rewriting committed .husky/ unless write_husky."""
    try:
        hp = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
                            capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise SystemExit(f"not a git repo (or git unavailable): {repo}") from e
    hooks_dir = Path(hp) if Path(hp).is_absolute() else (repo / hp)
    out_flag = f" --out {out_name}" if out_name != "graphify-out" else ""
    block = (
        f"\n{_PREPUSH_MARK}\n"
        f'R="$(git rev-parse --show-toplevel)"\n'
        f'if command -v cg-graphify-bridge >/dev/null 2>&1; then CG="cg-graphify-bridge"; '
        f'else CG=""; fi\n'
        f'if [ -n "$CG" ]; then $CG check-semantic "$R"{out_flag} --quiet || '
        f'{{ echo "cg-graphify-bridge: semantic overlay is stale — refresh + commit semantic.json '
        f'(see: cg-graphify-bridge status), or push with --no-verify"; exit 1; }}; fi\n'
    )
    if ".husky" in hooks_dir.parts:
        husky_root = hooks_dir.parent if hooks_dir.name == "_" else hooks_dir
        if not write_husky:
            return {"detected": "husky", "action": "no file written — .husky/ is committed config",
                    "to_install": {"file": str(husky_root / "pre-push"), "append": block.strip()},
                    "or_opt_in": "re-run init with husky opt-in / append the snippet yourself"}
        target = husky_root
    else:
        target = hooks_dir
    target.mkdir(parents=True, exist_ok=True)
    f = target / "pre-push"
    existing = f.read_text() if f.exists() else ""
    if _PREPUSH_MARK in existing:
        return {"pre_push": str(f), "action": "already present"}
    body = existing if existing.startswith("#!") else "#!/usr/bin/env sh\n" + existing
    f.write_text(body.rstrip("\n") + block)
    f.chmod(0o755)
    return {"pre_push": str(f), "action": "installed"}


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
                               max_nodes=args.max_nodes, max_docs=args.max_docs, doc_filter=args.filter)
    print(json.dumps({"tasks": len(info["tasks"]), "code_nodes": info["code_nodes"],
                      "tasks_dir": str(info["tasks_dir"]), "payloads_dir": str(info["payloads_dir"]),
                      "consumed": "structural.json (no re-cluster)",
                      "next": "for each tasks/<id>.json a subagent reads {doc, code_nodes} and writes "
                              "payloads/<id>.json {nodes,edges}; then run `semantic-merge`."},
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


def doctor_report(repo: Path | None) -> dict:
    """Probe the runtime deps the substrates need; per-dep {dep, ok, detail, hint}. Pure (no
    print/exit) so it's unit-testable. node + codegraph are global; `target typescript` is
    repo-local — the TS extractor uses the TARGET repo's typescript, not a bundled copy (R9)."""
    checks = []
    node = shutil.which("node")
    nodev = None
    if node:
        try:
            nodev = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
        except OSError:
            pass
    checks.append({"dep": "node", "ok": bool(node), "detail": nodev or "not found",
                   "hint": None if node else "install Node.js (nodejs.org) — required for the TS substrate"})
    cg = _codegraph_bin()
    checks.append({"dep": "codegraph", "ok": bool(cg), "detail": cg or "not found",
                   "hint": None if cg else "npm i -g @colbymchenry/codegraph (or set $CODEGRAPH_BIN) — for non-TS repos"})
    if repo is not None:
        tsdir = repo / "node_modules" / "typescript"
        ok = tsdir.is_dir()
        checks.append({"dep": "target typescript", "ok": ok, "detail": str(tsdir) if ok else "absent",
                       "hint": None if ok else f"install deps in {repo} "
                                               f"(the TS extractor uses the target repo's typescript)"})
    return {"repo": str(repo) if repo else None, "checks": checks,
            "ok": all(c["ok"] for c in checks)}


def _doctor(args: argparse.Namespace) -> None:
    repo = Path(args.repo).resolve() if args.repo else None
    rep = doctor_report(repo)
    print(json.dumps(rep, indent=2))
    if args.strict and not rep["ok"]:
        raise SystemExit(1)


_AGENTS_MARK = "<!-- cg-graphify-bridge:graph-consumption-contract -->"
_GITATTR_MARK = "# cg-graphify-bridge: semantic.json union/rebuild merge driver"


def _append_once(path: Path, marker: str, block: str) -> Path:
    """Idempotently append `block` (which contains `marker`) — never duplicate, never clobber
    pre-existing content."""
    existing = path.read_text() if path.exists() else ""
    if marker in existing:
        return path
    path.write_text((existing.rstrip("\n") + "\n\n" + block) if existing.strip() else block)
    return path


def _write_agents_md(repo: Path, out_name: str) -> Path:
    block = f"""{_AGENTS_MARK}
## Knowledge graph (`{out_name}/`)

This repo ships a committed code knowledge graph built by **cg-graphify-bridge**. Consult it
*before* broad file scans for "where is X / how does Y work / what touches Z".

**Committed layers:**
- `{out_name}/structural.json` — CI-owned deterministic code graph (nodes + edges + communities). Do not hand-edit; CI rebuilds it on merge to the default branch.
- `{out_name}/semantic.json` — dev-owned doc->code overlay. Refresh locally when you change docs or linked code, and commit it with your change-set.
- `{out_name}/GRAPH_REPORT.md` — human-browsable structural summary (god nodes, communities).
- `{out_name}/.cg_manifest.json` — engine stamp + freshness baseline.

**Derived (gitignored, local):**
- `{out_name}/graph.json` — the fused view (structural + semantic) the graph consumer reads. Lazily materialized; if absent, run `cg-graphify-bridge build .` (or it is rebuilt on session start).

**Check freshness before relying on the graph:**
```
cg-graphify-bridge status . --out {out_name}
```
If the semantic layer is stale, run the refresh protocol below, then commit `{out_name}/semantic.json`.

**Refreshing the semantic overlay (agent protocol).** The doc->code edges are produced by an AGENT
(not a script), in three steps:
1. `cg-graphify-bridge semantic-prep . --out {out_name}` — writes one task per doc under
   `{out_name}/.cache/semantic/tasks/<id>.json`, each `{{doc, code_nodes}}` where code_nodes are
   `{{composite_id, label, file, cg_kind}}` — **no source code** is included.
2. For EACH task, read its doc + code_nodes and write
   `{out_name}/.cache/semantic/payloads/<id>.json` =
   `{{"nodes": [<doc/concept nodes>], "edges": [{{"source": "<doc_node_id>", "target": "<composite_id>", "relation": "references|documents|..."}}]}}`:
   - set `target` to the **EXACT** composite id from THAT task's code_nodes — never invent ids;
   - if you know the symbol name but not its id, set `target_label` and leave `target` empty — the
     bridge resolves it by unique label or prunes + reports it (no silent dangling edges);
   - you are given identity metadata + the doc text **only** — never request or emit code bodies.
3. `cg-graphify-bridge semantic-merge . --out {out_name}` — merges the payloads into `semantic.json`
   and re-materializes the fused graph. Then `git add {out_name}/semantic.json` and commit it.
"""
    return _append_once(repo / "AGENTS.md", _AGENTS_MARK, block)


def _write_gitattributes(repo: Path, out_name: str) -> Path:
    block = (f"{_GITATTR_MARK}\n"
             f"{out_name}/semantic.json merge=cg-semantic\n")
    return _append_once(repo / ".gitattributes", _GITATTR_MARK, block)


def _read_template(name: str) -> str:
    from importlib.resources import files
    return files("cg_graphify_bridge.templates").joinpath(name).read_text()


def write_ci_workflow(repo: Path) -> dict:
    """Install the build-on-PR-branch GitHub Actions workflow (KD13). Idempotent: never clobber
    an existing graph-build.yml (a repo may have customized the install line / trigger paths)."""
    dest = repo / ".github" / "workflows" / "graph-build.yml"
    if dest.exists():
        return {"path": str(dest), "action": "exists (left as-is)"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_read_template("graph-build.yml"))
    return {"path": str(dest), "action": "installed"}


def _resolve_hook_cmd(sub: str, out_name: str) -> str:
    """The command committed into .claude/settings.json for a hook subcommand — the pipx-installed
    `cg-graphify-bridge` on PATH (every consumer installs the tool)."""
    flag = f" --out {out_name}" if out_name != "graphify-out" else ""
    return f"cg-graphify-bridge {sub}{flag}"


def write_claude_hooks(repo: Path, out_name: str) -> dict:
    """Wire the SessionStart/Stop hooks into the repo's .claude/settings.json (committed, travels
    to every dev — additive with the user's global config). Idempotent + preserves existing
    settings: only adds an entry when no cg-graphify-bridge hook for that event is present."""
    settings = repo / ".claude" / "settings.json"
    data: dict = {}
    if settings.exists():
        try:
            data = json.loads(settings.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    hooks = data.setdefault("hooks", {})
    added = []
    for event, sub in (("SessionStart", "hook-sessionstart"), ("Stop", "hook-stop")):
        entries = hooks.setdefault(event, [])
        if any("cg_graphify_bridge" in json.dumps(e) or "cg-graphify-bridge" in json.dumps(e)
               for e in entries):
            continue  # already wired
        entries.append({"hooks": [{"type": "command", "command": _resolve_hook_cmd(sub, out_name)}]})
        added.append(event)
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, indent=2) + "\n")
    return {"settings": str(settings), "added": added}


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


def configure_merge_driver(repo: Path, out_name: str) -> dict:
    """Register the cg-semantic merge driver in the repo's LOCAL git config (the .gitattributes
    `merge=cg-semantic` line is committed; the driver definition is per-clone, so init sets it).
    Best-effort — returns a skip note when git is unavailable."""
    driver_cmd = _resolve_hook_cmd("merge-driver", out_name).replace(
        " merge-driver", " merge-driver %A %B")
    try:
        subprocess.run(["git", "-C", str(repo), "config", "merge.cg-semantic.name",
                        "cg-graphify-bridge semantic-overlay union"], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "config", "merge.cg-semantic.driver", driver_cmd],
                       check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return {"configured": False, "note": f"git unavailable: {e}"}
    return {"configured": True, "driver": driver_cmd}


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


# ---------- Claude hooks (in-process subcommands; .claude/settings.json wires them) ----------
# Thin: SessionStart surfaces freshness, Stop gates on a stale/uncommitted overlay. Both honor
# the escape hatch and FAIL OPEN — a guard that errors must never brick a session (R7/R10).

def _hook_disabled() -> bool:
    return bool(os.environ.get("CG_BRIDGE_DISABLE")) or \
        (Path.home() / ".claude" / "state" / "cg-bridge" / "OFF").exists()


def _hook_repo() -> Path:
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except (OSError, FileNotFoundError):
        pass
    return Path.cwd()


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
        if not (stale or uncommitted):
            return  # allow stop
        reason = ("the semantic overlay is stale — docs or linked code changed since the last merge"
                  if stale else "semantic.json has uncommitted changes (refreshed but not committed)")
        cmd = _refresh_cmds(repo, args.out, False, True)["semantic"]
        msg = (f"cg-graphify-bridge: {reason}. Refresh the overlay and commit it before ending:\n{cmd}\n"
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
