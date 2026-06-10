<!-- cg-graphify-bridge:graph-consumption-contract -->
## Knowledge graph (`graphify-out/`)

This repo ships a committed code knowledge graph built by **cg-graphify-bridge**. Consult it
*before* broad file scans for "where is X / how does Y work / what touches Z".

**Committed layers:**
- `graphify-out/structural.json` — CI-owned deterministic code graph (nodes + edges + communities). Do not hand-edit; CI rebuilds it on merge to the default branch.
- `graphify-out/semantic.json` — dev-owned doc->code overlay. Refresh locally when you change docs or linked code, and commit it with your change-set.
- `graphify-out/GRAPH_REPORT.md` — human-browsable structural summary (god nodes, communities).
- `graphify-out/.cg_manifest.json` — engine stamp + freshness baseline.

**Derived (gitignored, local):**
- `graphify-out/graph.json` — the fused view (structural + semantic) the graph consumer reads. Lazily materialized; if absent, run `cg-graphify-bridge build .` (or it is rebuilt on session start).

**Check freshness before relying on the graph:**
```
cg-graphify-bridge status . --out graphify-out
```
If the semantic layer is stale, that prints the exact `semantic-prep` -> (Claude fills payloads) -> `semantic-merge` commands; run them and commit `graphify-out/semantic.json`.
