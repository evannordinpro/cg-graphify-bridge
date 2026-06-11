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

Installed from this GitHub repo (not published to PyPI). Pin a tag for reproducibility:

```bash
# Leiden community detection (higher quality — what CI uses):
pipx install "git+https://github.com/evannordinpro/cg-graphify-bridge@v0.1.0#egg=cg-graphify-bridge[leiden]"

# base: Louvain (deterministic, lighter — no graspologic):
pipx install "git+https://github.com/evannordinpro/cg-graphify-bridge@v0.1.0"
```

Runtime deps (run `cg-graphify-bridge doctor <repo>` to check, with install hints):
**node** (the TS substrate); the **codegraph** CLI for non-TS repos — `npm i -g @colbymchenry/codegraph@0.9.9`
(or set `$CODEGRAPH_BIN`); and — for TS repos — the *target repo's* `node_modules/typescript`.

## Quick start

**Adopting a repo** (owner, once):

```bash
cg-graphify-bridge doctor .                 # check runtime deps with actionable hints
cg-graphify-bridge init .                   # build + AGENTS.md + .gitattributes + CI + hooks
# → commit what init generated, enable CI write access, seed the semantic overlay
#   (the 7-step checklist: docs/setup.md §3)
```

**Working in a repo that has it** (every dev, daily):

```bash
pipx install "git+https://github.com/evannordinpro/cg-graphify-bridge@v0.1.0"   # once per machine
cg-graphify-bridge status .                 # freshness — structural arrives via git pull (CI builds it)
cg-graphify-bridge impact . <symbol>        # blast radius before you edit (also: callers / callees)
# refresh the semantic overlay when docs / linked code change:
cg-graphify-bridge semantic-prep .          # → Claude fills payloads (per AGENTS.md) → …
cg-graphify-bridge semantic-merge .         # … then commit graphify-out/semantic.json
```

With Claude Code, the committed hooks + `AGENTS.md` automate the daily loop (freshness surfacing,
graph-first navigation, overlay refresh) — see [`docs/setup.md`](docs/setup.md) §5.

→ **Full setup** — runtime deps, the **adoption checklist** (incl. enabling CI write access +
metrics opt-ins), per-developer steps, strict-repo CI limits, command reference, troubleshooting:
**[`docs/setup.md`](docs/setup.md)**.

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
  (doc→code overlay), `freshness` (on-demand drift), `engine` (determinism stamp), `py_calls`
  (supplemental cross-module Python call edges), `health` / `benchmark` / `insights` (metrics +
  showcase report), `query` (callers/callees/impact), `analytics`, `cli`
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

## Docs
- **[`docs/setup.md`](docs/setup.md)** — complete setup for every aspect: runtime deps, install,
  adopting the tool in a repo (incl. **enabling CI write access**), per-developer setup, the CI
  strict-protection limits, a full command reference, and troubleshooting.
- **[`docs/using-the-graph.md`](docs/using-the-graph.md)** — walkthrough for human **and** agent
  operators (reading the report, the composite-id model, the freshness gate, a worked example).
- **[`docs/internals.md`](docs/internals.md)** — maintainer internals: the query engine, overlay
  label resolution, freshness fingerprints, the TS substrate's two passes, and the Python
  call-edge supplement.
- **[`AGENTS.md`](AGENTS.md)** — the terse agent contract `init` ships into every consumer:
  how to *consume* the graph **and** the step-by-step protocol to *refresh* the semantic overlay.
- **[`GRAPH_INSIGHTS.md`](GRAPH_INSIGHTS.md)** — the auto-generated, versioned showcase: token
  efficiency, the Martin Zone-of-Pain/Uselessness quadrant, doc coverage, and the risk queue for
  this very repo (rebuilt by CI each graph build).
- This repo is self-hosted — `graphify-out/` and `GRAPH_INSIGHTS.md` are live examples of the tool's own output.

## License
[Apache-2.0](LICENSE).
