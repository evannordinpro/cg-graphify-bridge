"""Repo-adoption file writers — everything `init` installs into a consumer repo.

Split out of cli.py (the composition root keeps the parser + handlers; this module owns the
scaffolding: the AGENTS.md contract, .gitattributes, the CI workflow, the committed Claude
hooks settings, and the per-clone merge-driver config). All writers are idempotent and never
clobber pre-existing user content. Stdlib-only.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

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
- `{out_name}/structural.json` — CI-owned deterministic code graph (nodes + edges + communities). Do not hand-edit; CI rebuilds it on every PR and commits it onto the PR's own branch.
- `{out_name}/semantic.json` — dev-owned doc->code overlay. Refresh locally when you change docs or linked code, and commit it with your change-set.
- `{out_name}/GRAPH_REPORT.md` — human-browsable structural summary (god nodes, communities).
- `{out_name}/.cg_manifest.json` — engine stamp + freshness baseline.

**Derived (gitignored, local):**
- `{out_name}/graph.json` — the fused view (structural + semantic) the graph consumer reads. Lazily materialized; if absent, run `cg-graphify-bridge materialize .` (or it is rebuilt on session start).

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
3. If `{out_name}/.cache/semantic/dispatch_candidates.json` exists, review each candidate's
   `evidence` (file:line): when it is real dynamic wiring (dispatch table, callback, getattr-by-
   name), add `{{"source": <dispatch-site id>, "target": <candidate id>, "relation": "dispatches"}}`
   to any payload (`suggested_source` is precomputed). Confirmed `dispatches` edges are
   authoritative liveness for the dead-code queue and are NOT documentation coverage. A false
   positive (comment/string coincidence) gets no edge — it stays in the review queue.
4. `cg-graphify-bridge semantic-merge . --out {out_name}` — merges the payloads into `semantic.json`
   and re-materializes the fused graph. Then `git add {out_name}/semantic.json` and commit it.

**Isolation.** This graph is built by cg-graphify-bridge composing graphify + codegraph as
*libraries*. Do **not** run `graphify install`, `codegraph install`, or `graphify hook install` in
this repo — they install competing agent integrations: a codegraph **MCP** over the live `.codegraph`
db (not the committed graph) and graphify **native-rebuild git hooks**. `init` sets
`disabledMcpjsonServers: ["codegraph"]` to block a local codegraph MCP; if a graphify rebuild hook
is present, `export GRAPHIFY_SKIP_HOOK=1`. graphify's read/query is fine — `cg-graphify-bridge serve`
exposes graphify's MCP over the committed graph. `cg-graphify-bridge doctor .` surfaces these conflicts.
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
    """Wire the SessionStart/Stop hooks into the repo's .claude/settings.json AND hard-block a
    project-local codegraph MCP from loading (FR1a isolation — Claude Code honors
    `disabledMcpjsonServers`; codegraph's MCP serves the live per-clone .codegraph db and must
    never shadow the committed graph). Committed, travels to every dev, additive with the user's
    global config. Idempotent + preserves existing settings."""
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
    # FR1a: deny-list codegraph's .mcp.json MCP so a project-local `codegraph install` can't load
    # it in this repo (the committed graph is canonical). No-op unless codegraph is registered;
    # preserves pre-existing entries. A user-global codegraph MCP can't be gated here (doctor warns).
    disabled = data.get("disabledMcpjsonServers")
    if not isinstance(disabled, list):
        disabled = []
        data["disabledMcpjsonServers"] = disabled
    mcp_added = []
    if "codegraph" not in disabled:
        disabled.append("codegraph")
        mcp_added = ["codegraph"]
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, indent=2) + "\n")
    return {"settings": str(settings), "added": added, "disabled_mcp_added": mcp_added}


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
