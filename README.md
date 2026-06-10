# cg-graphify-bridge

Fuses **codegraph** (deterministic code substrate) with **graphify** (semantic / cross-domain
overlay) into one committed, queryable knowledge graph for **any** repo — joined on a stable
composite key `(file_path, qualified_name, kind, signature)` that survives line-shifting edits.

A standalone, **pipx-installed** developer tool with a hands-off freshness model:

- **CI owns the structural layer.** A GitHub Actions workflow rebuilds `structural.json` on every
  PR and pushes it onto the PR's own branch — devs never rebuild it by hand. Builds are
  **byte-deterministic** (pinned engine + `PYTHONHASHSEED`), so the loop self-terminates.
- **Devs own the semantic layer.** The doc→code overlay (`semantic.json`) is refreshed locally
  (guided, via Claude subagents) and committed alongside the change that moved the meaning.
- **Claude + git hooks keep everyone honest.** A SessionStart hook surfaces freshness; a Stop hook
  blocks ending a session on a stale/uncommitted overlay (escape hatch + fail-open); an optional
  pre-push gate covers non-Claude devs.

## Install

```bash
pipx install "cg-graphify-bridge[leiden]"      # CI / power users: Leiden community detection
pipx install cg-graphify-bridge                # base: Louvain (deterministic, lighter)
# or a pinned tag:
pipx install "git+https://github.com/evannordinpro/cg-graphify-bridge@v0.1.0#egg=cg-graphify-bridge[leiden]"
```

Runtime deps (checked by `doctor`): **node** (TS substrate), the **codegraph** CLI (other
languages), and — for TS repos — the *target repo's* `node_modules/typescript`.

## Quick start

```bash
cg-graphify-bridge doctor .                 # check runtime deps with actionable hints
cg-graphify-bridge init .                   # build + AGENTS.md + .gitattributes + CI + hooks
cg-graphify-bridge status .                 # structural + semantic freshness (+ exact refresh cmds)
# refresh the semantic overlay when docs / linked code change:
cg-graphify-bridge semantic-prep .          # → Claude fills payloads (/graphify overlay) → …
cg-graphify-bridge semantic-merge .         # … then commit graphify-out/semantic.json
```

## Committed artifact model (`graphify-out/`)

| File | Owner | Tracked |
|---|---|---|
| `structural.json` | CI (deterministic) | ✅ |
| `semantic.json` | dev (doc→code overlay) | ✅ |
| `GRAPH_REPORT.md` | CI (human-browsable) | ✅ |
| `.cg_manifest.json` | engine stamp + freshness baseline | ✅ |
| `graph.json` | lazily-materialized fused view (consumer reads this) | gitignored |

`graph.json = merge(structural, semantic)` — rebuilt on demand by the SessionStart hook,
`materialize`, or `build`. The two committed layers never produce fused-file merge conflicts;
`semantic.json` carries a union merge driver for the two-PRs-both-add-edges case.

## Layout
- `src/cg_graphify_bridge/` — `adapter` (codegraph DB → nodes/edges), `ts_substrate` (type-aware TS
  extractor), `driver` (library-composition over graphify + the layer split), `semantic`
  (doc→code overlay), `freshness` (on-demand drift), `engine` (determinism stamp), `cli`
- `src/cg_graphify_bridge/templates/graph-build.yml` — the CI workflow `init` installs
- `tests/` — pytest suite (determinism, packaging, artifact split, freshness, hooks, CI, …)
- `overlay/SKILL_overlay.md` — the `/graphify` subagent contract (overlay mode)
- `sample/` — fixture repo used by the codegraph-backed tests

## Develop

```bash
git clone git@github.com:evannordinpro/cg-graphify-bridge.git
cd cg-graphify-bridge
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,leiden]'
export CODEGRAPH_BIN=/path/to/codegraph/dist/bin/codegraph.js   # for codegraph-backed tests
pytest
```

Codegraph-dependent tests skip cleanly when `CODEGRAPH_BIN` is unset (pure-unit tests still run).
Determinism is non-negotiable: `build`/`init` re-exec under a pinned `PYTHONHASHSEED=0` so
`structural.json` is byte-identical across machines and reruns.
