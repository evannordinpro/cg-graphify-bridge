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
substrate; otherwise → codegraph. For Python, the bridge supplements codegraph (which resolves
same-file calls only) with a deterministic stdlib-AST pass that adds cross-module call edges —
resolved through import aliases, stamped `context: "pyast"` in the committed artifact.

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

The whole adoption, in order — each step is detailed below:

1. **Install the tool** (§2) and run `cg-graphify-bridge doctor <repo>` until it's clean.
2. **`cg-graphify-bridge init <repo>`** — builds the first structural graph + installs the CI
   workflow, agent contract, hooks, and merge driver (table below). Idempotent.
3. **Commit everything `init` generated** (the ✅ rows below) and push.
4. **Enable CI write access** — GitHub → Settings → Actions → General → Workflow permissions →
   *"Read and write permissions"* (details below). Without this the structural commit-back can't push.
5. **Opt into metrics** (recommended) — repo **variables**: `CG_INSIGHTS=true` renders the
   `GRAPH_INSIGHTS.md` showcase at the repo root on every graph build; `CG_HEALTH_ADVISORY=true`
   writes the health report to the CI run summary (never gates). See §6 "Health & benchmarks."
6. **Seed the semantic overlay** — `init` does *not* create `semantic.json`; until it exists,
   health/insights report structural metrics only and "no semantic overlay." Run
   `cg-graphify-bridge semantic-prep <repo>`, have your agent fill the payloads (with Claude Code:
   just ask it to "refresh the semantic overlay" — the committed `AGENTS.md` carries the exact
   protocol), then `cg-graphify-bridge semantic-merge <repo>` and commit
   `graphify-out/semantic.json`.
7. **Verify** — open any PR touching source: the graph-build job should push a
   `ci graph build` commit onto the PR's own branch updating `graphify-out/**` (or trigger the
   workflow manually via *Actions → graph-build → Run workflow*). Then `cg-graphify-bridge
   status <repo>` on a fresh pull reports both layers **fresh**.

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

## 5. Daily use — the local loop

**If you work with Claude Code, the loop is mostly automatic.** The committed `.claude` hooks and
`AGENTS.md` do the work: SessionStart surfaces freshness and materializes `graph.json`; the agent
consults the graph before file scans and follows the overlay-refresh protocol when needed; the Stop
hook blocks ending a session on a stale/uncommitted overlay (escape hatch:
`export CG_BRIDGE_DISABLE=1` — the gate always fails open on errors). Your part: pull regularly
(CI owns structural) and commit `graphify-out/semantic.json` when the agent refreshes it.

**Working by hand, the loop is:**

```bash
git pull                              # structural.json is CI-built — pulling IS the structural refresh
cg-graphify-bridge status .           # both layers fresh? prints the exact refresh command if not
```

- **Navigate before you edit** — the committed graph answers "what breaks if I touch this":
  ```bash
  cg-graphify-bridge callers . <symbol>     # who depends on it
  cg-graphify-bridge impact . <symbol>      # transitive blast radius (--depth N to bound)
  cg-graphify-bridge callees . <symbol>     # what it depends on
  ```
  Or read `graphify-out/graph.json` / `GRAPH_REPORT.md` directly — full guidance in
  [`using-the-graph.md`](using-the-graph.md). Missing `graph.json`? `cg-graphify-bridge
  materialize .` (the SessionStart hook also does this). For repeat-query sessions (≥10 lookups),
  `cg-graphify-bridge serve .` exposes the committed graph over graphify's MCP.
- **Check the codebase pulse occasionally** — `cg-graphify-bridge health .` (debt, cycles,
  doc-coverage, risk queue; advisory, never gates) and `insights .` (the rendered showcase).
- **Structural is CI-owned** — never rebuild it by hand; pull the latest.
- **Refresh the semantic overlay** when `status` says it's stale (you changed docs or linked code):
  ```bash
  cg-graphify-bridge semantic-prep .     # → an agent fills graphify-out/.cache/semantic/payloads/<id>.json
  cg-graphify-bridge semantic-merge .    # → then: git add graphify-out/semantic.json && commit
  ```
  With Claude Code, ask it to "refresh the semantic overlay" — it follows the committed protocol.
  The exact payload contract (composite-id targets, `target_label` fallback, no source code) is in
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
| `health <repo> [--json] [--include-tests]` | structural + semantic + combined codebase-health metrics (advisory; never gates; production-scoped by default) |
| `benchmark <repo> [--json]` | token-reduction of graph-guided retrieval vs naive file-read, per query class |
| `callers <repo> <symbol> [--depth N] [--json]` | symbols that depend on SYMBOL (over the committed graph) |
| `callees <repo> <symbol> [--depth N] [--json]` | symbols SYMBOL depends on |
| `impact <repo> <symbol> [--depth N] [--json]` | transitive blast radius if SYMBOL changes (full by default) |
| `insights <repo> [--out-file PATH]` | render the versioned showcase report (health + benchmark) as GitHub-native markdown |
| `check-semantic <repo> [--require-committed]` | exit non-zero if the overlay is stale (the Stop-hook gate) |
| `install-hook <repo>` | install the git freshness hooks |
| `hook-sessionstart` / `hook-stop` | the Claude hook entrypoints (wired by `init` into `.claude/settings.json`) |
| `merge-driver <ours> <theirs>` | the `semantic.json` union merge driver (wired by `.gitattributes`) |

Every command takes `--out <dir>` (default `graphify-out`). Reads are offline; the semantic step
runs locally via Claude subagents (no third-party LLM, no source egress).

### Health & benchmarks
`cg-graphify-bridge health <repo>` reads the committed graph (offline, no rebuild) and reports three
layers, each with the action it implies:
- **Structural** — dependency cycles (with a suggested cut), leaky communities (conductance),
  betweenness hubs, Martin Instability/Abstractness/Distance + Zone-of-Pain/Uselessness, fan-out
  smells, dead-code review queue.
- **Semantic** — doc coverage (overall / by-kind / public-API via `is_exported`), dangling links,
  orphan docs, a knowledge-debt index (shown with its components).
- **Combined** (the differentiator) — **god-node / centrality-weighted doc coverage** ("are we
  documenting what matters") and an **undocumented-load-bearing risk queue** (`centrality × (1−documented)`).

`health` is **production-scoped by default** — test files (`tests/`, `*_test.*`, `test_*`, `*.spec.*`)
are excluded from every metric (coverage denominators, centrality, cycles, the risk queue) since
codegraph indexes the whole repo; pass `--include-tests` to analyze everything.

The **dead-code queue filters dynamically-wired symbols**: a zero-reference symbol whose name
appears in the indexed sources as a *value* (argparse `set_defaults(func=…)`, callback/registry
tables, `getattr`-by-name strings, constants read as bare identifiers) is treated as an entry
point, not dead code — the JSON output lists what was dropped and the `file:line` evidence.

`cg-graphify-bridge benchmark <repo>` reports graph-guided **token reduction** vs a naive
full-file-read baseline, per query class (pinpoint vs global). Uses `tiktoken` for exact counts if
installed, else a labelled `chars/4` estimate. Both commands add `--json` for machine output.

To surface health in CI **non-blockingly**, set the repo variable **`CG_HEALTH_ADVISORY=true`** — the
workflow then writes the report to the run summary (it never gates the build). Abstractness needs the
`is_abstract` stamp the current extractor emits; a graph built by an older tool version shows a caveat
until CI rebuilds it.

### Showcase report
`cg-graphify-bridge insights <repo>` renders a beautiful, GitHub-native markdown report composing the
health + benchmark metrics — a scorecard, token-efficiency vs GraphRAG's 26–97% band, a **mermaid
quadrant** of the Martin Zone-of-Pain/Uselessness, doc-coverage gauges, undocumented hubs, and the
risk queue. It's **content-deterministic** (no timestamp/SHA) so it versions cleanly. The CI build
renders it to **`GRAPH_INSIGHTS.md`** at the repo root and commits it: **always on** in this repo;
in a consumer repo set the variable **`CG_INSIGHTS=true`** to enable it.

### Querying the graph
`cg-graphify-bridge callers|callees|impact <repo> <symbol>` navigate the committed graph offline:
`callers` = who depends on a symbol, `callees` = what it depends on, `impact` = the **transitive**
blast radius if it changes (full by default; `--depth N` to bound, output grouped by hop). You pass a
plain **name** (e.g. `build_repo`) — it resolves by label → qualified-name → suffix, and an ambiguous
name lists its candidates and exits non-zero. Unlike `health`, these traverse the **whole** graph
(tests included — a test that calls X is real impact). `--json` for machine output.

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
