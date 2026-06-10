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
If the semantic layer is stale, run the refresh protocol below, then commit `graphify-out/semantic.json`.

**Refreshing the semantic overlay (agent protocol).** The doc->code edges are produced by an AGENT
(not a script), in three steps:
1. `cg-graphify-bridge semantic-prep . --out graphify-out` — writes one task per doc under
   `graphify-out/.cache/semantic/tasks/<id>.json`, each `{doc, code_nodes}` where code_nodes are
   `{composite_id, label, file, cg_kind}` — **no source code** is included.
2. For EACH task, read its doc + code_nodes and write
   `graphify-out/.cache/semantic/payloads/<id>.json` =
   `{"nodes": [<doc/concept nodes>], "edges": [{"source": "<doc_node_id>", "target": "<composite_id>", "relation": "references|documents|..."}]}`:
   - set `target` to the **EXACT** composite id from THAT task's code_nodes — never invent ids;
   - if you know the symbol name but not its id, set `target_label` and leave `target` empty — the
     bridge resolves it by unique label or prunes + reports it (no silent dangling edges);
   - you are given identity metadata + the doc text **only** — never request or emit code bodies.
3. `cg-graphify-bridge semantic-merge . --out graphify-out` — merges the payloads into `semantic.json`
   and re-materializes the fused graph. Then `git add graphify-out/semantic.json` and commit it.
