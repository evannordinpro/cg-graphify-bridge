"""Git-hook installers + Claude-hook gate helpers.

Split out of cli.py (the composition root keeps the parser + the hook-sessionstart/hook-stop
HANDLERS; this module owns hook installation and the shared gate predicates). Stdlib-only —
the git freshness hook invokes `status` on a bare python3, and these run in that same path.
Phase 6's CLAUDECODE-aware faq gate clones from here (next_implementation.md KD8).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

_HOOK_MARK = "# cg-graphify-bridge freshness hook"
_PREPUSH_MARK = "# cg-graphify-bridge semantic pre-push gate"


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


def install_prepush_hook(repo: Path, out_name: str, *, write_husky: bool = False) -> dict:
    """Optional universal (non-Claude) gate: a git pre-push that fails when the semantic overlay
    is stale, with `git push --no-verify` as the escape (mirrors the repo's branch-name pre-push).
    Phase 6 (KD8/DEC-1): also gates a stale PROJECT_FAQ narrative, CLAUDECODE-aware — a Claude
    push fails with the imperative (Claude sees the failure and runs the faq loop); a human push
    soft-warns only (DEC-5). check-faq itself fails open and exits 0 on un-adopted repos.
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
        f'if [ -n "$CG" ]; then\n'
        f'  if [ "$CLAUDECODE" = "1" ]; then\n'
        f'    $CG check-faq "$R"{out_flag} || exit 1\n'
        f'  else\n'
        f'    $CG check-faq "$R"{out_flag} --quiet || echo "cg-graphify-bridge (warning): '
        f'PROJECT_FAQ narrative is stale — cg-graphify-bridge faq-prep / faq-merge when convenient"\n'
        f'  fi\n'
        f'fi\n'
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


# ---------- Claude-hook gate helpers (the handlers live in cli.py) ----------
# Both honor the escape hatch and FAIL OPEN — a guard that errors must never brick a session.

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
