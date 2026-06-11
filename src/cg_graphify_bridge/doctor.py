"""Runtime-dependency probes + tool-isolation conflict detectors (FR1b/FR3/FR4).

Split out of cli.py (the composition root keeps the parser + handlers; this module owns the
checks). Everything here is advisory and fail-open: probes never change a caller's exit code,
and one raising never suppresses the others. Stdlib-only — the doctor path must run on a bare
python3.

The bridge composes graphify/codegraph as libraries + subprocesses, never as installed agent
integrations. The detectors cover the INCOMPATIBLE behaviors we can't prevent at install time
(a user-global codegraph MCP, graphify's native-rebuild git hooks, a graphify-native
semantic.json) and warn. graphify's read/query/MCP over graph.json is COMPATIBLE and
intentionally NOT flagged.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

_GRAPHIFY_HOOK_MARK = "# graphify-hook-start"


def _codegraph_bin() -> str | None:
    env = os.environ.get("CODEGRAPH_BIN")
    if env and Path(env).exists():
        return env
    return shutil.which("codegraph")


def _mcp_servers(path: Path) -> dict:
    """The `mcpServers` map from a Claude/agent JSON config; {} on any read/parse failure."""
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    srv = data.get("mcpServers") if isinstance(data, dict) else None
    return srv if isinstance(srv, dict) else {}


def _is_codegraph_serve(name: str, entry: object) -> bool:
    """True iff an mcpServers (name, entry) launches codegraph's MCP — keyed by the server name
    `codegraph` or a command/args invoking `codegraph ... serve`."""
    if str(name).lower() == "codegraph":
        return True
    if not isinstance(entry, dict):
        return False
    cmd = str(entry.get("command", ""))
    args = [str(a) for a in (entry.get("args") or [])]
    mentions = "codegraph" in Path(cmd).name or any("codegraph" in a for a in args)
    return mentions and any(a == "serve" or a.endswith("serve") for a in args)


def _detect_codegraph_mcp(home: Path, repo: Path) -> str | None:
    """FR1(b): a codegraph MCP registration shadows the committed graph (it serves the live
    per-clone .codegraph db). The project-local case is hard-blocked by disabledMcpjsonServers
    (FR1a); the user-global case can't be — warn either way."""
    for path, label in ((home / ".claude.json", "user-global ~/.claude.json"),
                        (repo / ".mcp.json", "project .mcp.json"),
                        (repo / ".claude" / "mcp.json", "project .claude/mcp.json")):
        for name, entry in _mcp_servers(path).items():
            if _is_codegraph_serve(name, entry):
                note = ("hard-blocked in-repo by disabledMcpjsonServers" if "project" in label
                        else "NOT blockable by repo settings — it's user-global")
                return (f"codegraph MCP registered in {label} ({note}): it serves the live "
                        f".codegraph db, not the committed graph. Use the committed graph (or "
                        f"`cg-graphify-bridge serve`); `codegraph uninstall` removes it.")
    return None


def _detect_graphify_rebuild_hooks(repo: Path) -> str | None:
    """FR3: graphify's native-rebuild git hook (post-commit/post-checkout) rebuilds a
    graphify-native graph that conflicts with the committed structural.json."""
    for h in (repo / ".git" / "hooks" / "post-commit", repo / ".git" / "hooks" / "post-checkout",
              repo / ".husky" / "post-commit", repo / ".husky" / "post-checkout"):
        try:
            if h.exists() and _GRAPHIFY_HOOK_MARK in h.read_text():
                return (f"graphify native-rebuild git hook in {h.name} conflicts with the committed "
                        f"structural.json — neutralize with `export GRAPHIFY_SKIP_HOOK=1` or remove "
                        f"the hook.")
        except OSError:
            continue
    return None


def _detect_semantic_schema_clash(out: Path) -> str | None:
    """FR4: a graphify-out/semantic.json without the bridge marker layer=="semantic" is a
    graphify-NATIVE semantic.json that overwrote (or would overwrite) the doc->code overlay."""
    f = out / "semantic.json"
    try:
        if not f.exists():
            return None
        data = json.loads(f.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None  # fail-open: a parse error is not a schema-clash signal
    if isinstance(data, dict) and data.get("layer") == "semantic":
        return None
    return (f"{f} lacks the cg-graphify-bridge marker (layer:\"semantic\") — looks like a "
            f"graphify-native semantic.json that can overwrite the bridge's doc->code overlay. "
            f"Re-run `cg-graphify-bridge semantic-merge` to regenerate it.")


def _check_conflicts(repo: Path, out: Path, home: Path | None = None) -> list[str]:
    """Aggregate the advisory isolation detectors (D-B detect-and-warn). Each probe is fail-open:
    one raising never suppresses the others, and findings never change a caller's exit code."""
    home = home or Path.home()
    findings = []
    for probe in (lambda: _detect_codegraph_mcp(home, repo),
                  lambda: _detect_graphify_rebuild_hooks(repo),
                  lambda: _detect_semantic_schema_clash(out)):
        try:
            res = probe()
        except Exception:
            res = None  # fail open
        if res:
            findings.append(res)
    return findings


def doctor_report(repo: Path | None, home: Path | None = None) -> dict:
    """Probe the runtime deps the substrates need; per-dep {dep, ok, detail, hint}. Pure (no
    print/exit) so it's unit-testable. node + codegraph are global; `target typescript` is
    repo-local — the TS extractor uses the TARGET repo's typescript, not a bundled copy (R9).
    When a repo is given, also surfaces advisory tool-isolation `conflicts` (never affects `ok`)."""
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
    report = {"repo": str(repo) if repo else None, "checks": checks,
              "ok": all(c["ok"] for c in checks)}
    if repo is not None:
        report["conflicts"] = _check_conflicts(repo, repo / "graphify-out", home)
    return report
