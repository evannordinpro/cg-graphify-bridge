# Setup — getting every part of cg-graphify-bridge working

End-to-end setup for both **a repo owner adopting the tool** and **a developer joining a repo that
already uses it**. For *consuming* the graph once it exists, see
[`using-the-graph.md`](using-the-graph.md) and the repo's generated `AGENTS.md`.

---

## 1. Runtime prerequisites

`cg-graphify-bridge doctor <repo>` checks all of these and prints install hints — run it first.

| Dependency | Needed for | Install |
|---|---|---|
| **Python 3.10+ / pipx** | the tool itself | `python -m pip install --user pipx` |
| **node** (≥20; CI uses 24) | the TypeScript substrate | https://nodejs.org |
| **codegraph CLI** | non-TS repos (Python/Go/Rust/…) | `npm i -g @colbymchenry/codegraph@0.9.9` (or set `$CODEGRAPH_BIN`) |
| target repo's **typescript** | TS repos only | run the repo's package install (`npm ci`) so `node_modules/typescript` exists |

The extractor auto-routes: a repo with a `tsconfig` + real `.ts` sources → the type-aware TS
substrate; otherwise → codegraph.

## 2. Install the tool

Installed from this GitHub repo, pinned to a tag (not on PyPI):

```bash
# Leiden community detection (higher quality — what CI uses):
pipx install "git+https://github.com/evannordinpro/cg-graphify-bridge@v0.1.0#egg=cg-graphify-bridge[leiden]"
# or base (Louvain — deterministic, lighter, no graspologic):
pipx install "git+https://github.com/evannordinpro/cg-graphify-bridge@v0.1.0"
```

Verify: `cg-graphify-bridge doctor .`

## 3. Adopt the tool in a repo (one-time, by the repo owner)

```bash
cg-graphify-bridge init <repo>     # idempotent
```

`init` builds the first structural graph and installs everything a consumer needs:

| Created / configured | What it is | Committed? |
|---|---|---|
| `graphify-out/{structural.json, GRAPH_REPORT.md, .cg_manifest.json, .gitignore}` | the structural layer + engine/substrate stamp; gitignores the fused `graph.json` + `.cache/` | ✅ commit |
| `AGENTS.md` | the agent contract — how to consume **and** refresh the graph | ✅ commit |
| `.gitattributes` | declares the `semantic.json` union merge driver | ✅ commit |
| `.github/workflows/graph-build.yml` | the CI that rebuilds structural on PRs (build-on-PR-branch) | ✅ commit |
| `.claude/settings.json` | SessionStart/Stop hooks (added, your other settings preserved) | ✅ commit |
| local `git config merge.cg-semantic.*` | the merge-driver definition (per-clone — see §4) | not committed |
| git `post-commit/merge/checkout` + `pre-push` hooks | freshness reminders (`.git/hooks`, or husky if present) | not committed |

Then **commit the generated files** and **enable CI write access** (required for the commit-back):

- **GitHub → Settings → Actions → General → Workflow permissions → "Read and write permissions."**
  The workflow declares `contents: write`; if your org enforces read-only, the structural
  commit-back can't push (it fails loudly with guidance). No PAT or bot is needed — just the
  built-in `GITHUB_TOKEN`.
- The workflow installs the tool with `pipx install "…@v0.1.0…"`. Adjust the tag/source in
  `graph-build.yml` if you track a different version.
- **Engine:** CI installs the `[leiden]` extra → the committed graph is **Leiden-built**, and that
  engine is stamped in `.cg_manifest.json`. CI is the **sole structural builder**; the engine +
  substrate stamps make a mismatched local rebuild fail loudly rather than churn the artifact.
  Devs never rebuild structural by hand.

### CI on repos with strict protection
Build-on-PR-branch pushes structural onto the PR's own (unprotected) branch, so it merges with the
code in one reviewed PR. It works on review-only protection with no extra setup. It **cannot** push
under: required status checks with *"require branches up to date"* (a `GITHUB_TOKEN` commit doesn't
re-trigger checks → the bot SHA blocks merge), **required signed commits**, or a **read-only
`GITHUB_TOKEN`**. For those repos: exclude the graph job from the "up to date" rule, or build
structural locally and commit it in the PR. The workflow header documents this; the push step fails
with an actionable message.

## 4. Per-developer setup (each clone)

A developer who clones a repo that already uses the tool does **not** run `init` (that's the owner's
one-time step; re-running it rebuilds structural, which only CI should do). Each dev just:

```bash
pipx install "git+https://github.com/evannordinpro/cg-graphify-bridge@v0.1.0"   # so the command is on PATH
```

That alone makes the committed `.claude` SessionStart/Stop hooks work. Optional extras:

```bash
# universal git freshness/pre-push hooks (skip if you rely on the Claude hooks):
cg-graphify-bridge install-hook .
# activate the semantic.json union merge driver locally (only matters when resolving a conflict):
git config merge.cg-semantic.driver "cg-graphify-bridge merge-driver %A %B"
```

## 5. Daily use

```bash
cg-graphify-bridge status .          # structural + semantic freshness (+ exact refresh command)
```

- **Consume the graph:** read `graphify-out/graph.json` (or `GRAPH_REPORT.md`); full guidance in
  [`using-the-graph.md`](using-the-graph.md) and `AGENTS.md`. If `graph.json` is missing,
  `cg-graphify-bridge materialize .` rebuilds it (the SessionStart hook also does).
- **Structural** is CI-owned — never rebuild it by hand; pull the latest.
- **Refresh the semantic overlay** when `status` says it's stale (you changed docs or linked code):
  ```bash
  cg-graphify-bridge semantic-prep .     # → an agent fills graphify-out/.cache/semantic/payloads/<id>.json
  cg-graphify-bridge semantic-merge .    # → then: git add graphify-out/semantic.json && commit
  ```
  The exact payload protocol (composite-id targets, `target_label` fallback, no source code) is in
  `AGENTS.md` §"Refreshing the semantic overlay."

## 6. Command reference

| Command | Purpose |
|---|---|
| `doctor [repo]` | check runtime deps + print install hints |
| `init <repo>` | one-time repo adoption (build + AGENTS.md + .gitattributes + CI + hooks + merge driver) |
| `build <repo>` | (re)build the structural layer — normally CI-only |
| `status <repo>` | report structural + semantic freshness + the exact refresh command |
| `semantic-prep <repo>` / `semantic-merge <repo>` | the dev-owned doc→code overlay refresh |
| `materialize <repo>` | rebuild the gitignored fused `graph.json` from the committed layers |
| `serve <repo>` | (opt-in) launch graphify's MCP over the **committed** graph for repeat-query (≥10/session) workflows — never auto-installed |
| `check-semantic <repo> [--require-committed]` | exit non-zero if the overlay is stale (the Stop-hook gate) |
| `install-hook <repo>` | install the git freshness hooks |
| `hook-sessionstart` / `hook-stop` | the Claude hook entrypoints (wired by `init` into `.claude/settings.json`) |
| `merge-driver <ours> <theirs>` | the `semantic.json` union merge driver (wired by `.gitattributes`) |

Every command takes `--out <dir>` (default `graphify-out`). Reads are offline; the semantic step
runs locally via Claude subagents (no third-party LLM, no source egress).

## 7. Isolation — don't let graphify/codegraph installers interfere

The bridge composes **graphify** and **codegraph** as *libraries + subprocesses* — it does **not**
use their agent-integration installers. In a bridge repo, do **not** run:

- **`codegraph install` / `codegraph serve`** — registers a codegraph **MCP server** that serves the
  *live, per-clone `.codegraph` db* (often stale or absent on a fresh clone), which would shadow the
  committed graph. `init` writes `disabledMcpjsonServers: ["codegraph"]` into `.claude/settings.json`
  to hard-block a **project-local** codegraph MCP; a **user-global** one (in `~/.claude.json`) can't
  be blocked by repo settings — `doctor` warns, and `codegraph uninstall` removes it.
- **`graphify install` / `graphify hook install`** — installs graphify's CLAUDE.md section, PreToolUse
  nudges, and **native-rebuild git hooks** (`# graphify-hook-start`) that rebuild a graphify-native
  graph conflicting with the committed `structural.json`. If one is present, `export GRAPHIFY_SKIP_HOOK=1`
  neutralizes the rebuild; `doctor` warns.

graphify's **read/query is compatible** (it reads the bridge's `graph.json`) and is *not* blocked — in
fact **`cg-graphify-bridge serve`** launches graphify's MCP over the *committed* graph for repeat-query
(≥10/session) workflows. Run `cg-graphify-bridge doctor <repo>` any time to surface the conflicts above.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `codegraph CLI not found` | `npm i -g @colbymchenry/codegraph@0.9.9` (or set `$CODEGRAPH_BIN`); `doctor` confirms |
| `engine mismatch … exits non-zero` | the committed graph was built by a different engine — install `[leiden]` to match CI, or let CI rebuild; don't commit a base/Louvain rebuild over a Leiden artifact |
| `⚠ substrate drift` warning | your codegraph/typescript version differs from the committed stamp — extraction may differ; align versions (CI's pinned version is canonical) |
| `no structural.json … run build first` | pull the CI-built layer, or (owner) `cg-graphify-bridge build .` |
| CI: "structural commit-back rejected" | branch protection / signed commits / read-only token — see §3 "strict protection" |
| Claude hooks do nothing | the tool isn't on PATH in that environment — `pipx install` it |
| `doctor` warns "codegraph MCP registered…" | a `codegraph install` ran — it shadows the committed graph; `codegraph uninstall`, or rely on the in-repo `disabledMcpjsonServers` block (local) |
| `doctor`/`status` warns "graphify native-rebuild git hook" / "semantic.json lacks layer" | graphify's installer ran in this repo — `export GRAPHIFY_SKIP_HOOK=1` and re-run `cg-graphify-bridge semantic-merge`; see §7 |

Determinism note: `build`/`init` re-exec under a pinned `PYTHONHASHSEED=0`, the clustering engine
and codegraph version are stamped, and CI is the single authoritative builder — so `structural.json`
is byte-stable across machines and reruns for a fixed source + engine + substrate version.
