# Using the graph — a walkthrough for human & agent operators

This repo is **self-hosted**: `cg-graphify-bridge` was run on its own source, so `graphify-out/`
is a live, worked example of the tool's output. This doc explains how to *consume* that output —
the same way any repo's `graphify-out/` should be used.

> The numbers/symbols below are from this repo's actual graph (507 code nodes, 23 communities,
> 32 doc→code edges). Rebuild it any time with `cg-graphify-bridge build .` + the semantic steps.

## What's in `graphify-out/`

| File | What it is | Owner | Committed? |
|---|---|---|---|
| `structural.json` | The deterministic code graph — nodes (functions/classes/files) + edges (calls/imports/contains/inherits), keyed by a line-independent **composite id** `cg:<hash(file,qualified_name,kind,signature)>`, plus community assignments + god nodes. | CI (rebuilt on every PR) | ✅ |
| `semantic.json` | The **doc→code overlay** — concept/doc nodes + edges from documentation to the code symbols they describe. | the dev who changed the meaning | ✅ |
| `GRAPH_REPORT.md` | Human-browsable summary: god nodes (highest-degree symbols), communities, surprising connections. | derived from structural | ✅ |
| `.cg_manifest.json` | Engine stamp (`engine`, dep versions, `schema_version`) + the freshness baseline (source + doc/linked-file hashes). | build / merge | ✅ |
| `graph.json` | The **fused** view = `structural ∪ semantic`. The node-link JSON consumers actually read. Rebuilt on demand. | — | **gitignored** (lazy cache) |

Pull the repo → you have the graph. No build needed to *consume* it. If `graph.json` is missing,
regenerate it with `cg-graphify-bridge materialize .` (the SessionStart hook also does this).

## Human operators

1. **Orient from `GRAPH_REPORT.md`.** Its *god nodes* are the architecturally central symbols — for
   this repo: `materialize`, `write_structural`, `build_repo`, `_adapt_repo`, `source_hash`,
   `AdaptResult`, `compute_status`, the hook handlers. Start there, not a cold file scan.
2. **Check freshness before trusting it:**
   ```
   cg-graphify-bridge status .
   ```
   It reports each layer (`fresh` / `stale` / `unbuilt`) and, when stale, prints the **exact**
   command to refresh. A code edit that isn't referenced by any doc shows *structural* stale but
   leaves *semantic* fresh — no busywork.
3. **Refresh the overlay when you change docs or linked code** (status tells you to):
   ```
   cg-graphify-bridge semantic-prep .    # → have Claude fill the doc→code payloads → …
   cg-graphify-bridge semantic-merge .   # … then: git add graphify-out/semantic.json
   ```

## Agent operators

The graph is your **primary code-context lookup** — consult it *before* grepping or reading files
for "where is X", "how does Y work", "what touches Z".

1. **Read `graphify-out/graph.json` first.** It's node-link JSON: `nodes[]` (each has `id`, `label`,
   `source_file`, `community`, `god_node`, `metadata.cg_kind`) and `edges[]` (`source`, `target`,
   `relation`). Resolve a symbol → find its node → follow edges. Example:
   ```python
   import json
   g = json.load(open("graphify-out/graph.json"))
   byid = {n["id"]: n for n in g["nodes"]}
   # what does build_repo depend on / call?
   bid = next(n["id"] for n in g["nodes"] if n["label"] == "build_repo")
   for e in g["edges"]:
       if e["source"] == bid:
           print(e["relation"], "->", byid[e["target"]]["label"])
   ```
   (If the `graphify` CLI is installed, `graphify query "<question>"` works on this `graphify-out/`.)
2. **Composite ids are stable across edits.** `cg:<hash(file,qualified_name,kind,signature)>` does
   **not** encode line numbers, so an id survives a pure line-shift — safe to reference in notes,
   memory, or doc→code edges; it still resolves after the code moves.
3. **Two layers, two questions.** *Structural* answers "how is the code wired" (calls/imports/
   inheritance, communities). *Semantic* answers "what does the documentation say about this symbol"
   — e.g., in this repo the README has a doc→code edge to `build_repo`, `materialize`,
   `composite_id`, `_pin_hashseed_for`, …, so an agent can jump from a concept in the docs straight
   to the implementing symbol.
4. **Gate on freshness.** If `cg-graphify-bridge status .` says a layer is stale, treat the graph as
   a point-in-time artifact: prefer it for navigation but confirm against the file before relying on
   a specific detail, and refresh if you changed the relevant docs/code.
5. **Never block on it.** A missing/corrupt layer degrades to file reads (`load_fused` falls back) —
   the graph is an accelerator, not a dependency.

## Worked example — "how does `build` produce the committed artifact?"

Following the graph from the `build_repo` god node:
`build_repo` → `_adapt_repo` (routes to `adapt` / `adapt_ts` by substrate) → `driver.build_fused`
(cluster + god nodes) → `write_structural` (commits `structural.json` + report + gitignore) →
`materialize` (fuses the lazy `graph.json`). The README's doc→code edges point at exactly these
symbols, so the prose and the implementation stay linked.

## Freshness & ownership (why it stays current with little effort)

- **CI owns `structural.json`** — `.github/workflows/graph-build.yml` rebuilds it on every PR and
  pushes it onto the PR branch (deterministic, so the loop self-terminates). Devs never rebuild it.
- **Devs own `semantic.json`** — refreshed locally (guided by `status`) and committed with the change
  that moved the meaning.
- **Hooks keep everyone honest** — the repo-shipped `.claude` SessionStart hook surfaces staleness +
  materializes the fused cache; the Stop hook blocks ending a session on a stale/uncommitted overlay
  (escape hatch: `CG_BRIDGE_DISABLE=1`); an optional git `pre-push` covers non-Claude devs.
- **The contract for agents** lives in `AGENTS.md` (the terse version of §"Agent operators" above).
