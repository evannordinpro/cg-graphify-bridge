# 📒 PROJECT_FAQ — cg-graphify-bridge

_Deterministic graph facts + committed narrative ([how this file is produced](docs/setup.md))._

## What is this project?

**What.** cg-graphify-bridge fuses codegraph (a deterministic code substrate) with graphify (a semantic, cross-domain overlay) into one committed, queryable knowledge graph for any repository, joined on a line-shift-stable composite id.

**Purpose.** Code knowledge graphs rot: local indexes drift, rebuilds churn artifacts, and documentation links break silently. The bridge makes the graph a versioned, byte-deterministic artifact — CI owns the structural layer, developers (via their agents) own the doc-to-code and narrative layers, and freshness gates keep every layer honest with near-zero manual effort.

**Value.** Agents and humans navigate by graph instead of cold file scans (~96% less context per question), architecture and documentation health are continuously measured (insights, debt, risk queues), and the whole thing survives clones, rebuilds, and refactors because every artifact is committed and deterministic.

## What are the features?

### CLI dispatch & freshness status — 23 components (community 2)

The argparse composition root plus the status/freshness surface.

main wires every subcommand; compute_status reports per-layer freshness (structural = source hash vs build baseline, semantic = docs+linked files vs merge baseline) with exact refresh commands; the Stop hook blocks ending a session on a stale or uncommitted layer, fail-open with an escape hatch.

- **Key components:** `resolve`, `main`, `write_manifest`, `compute_status`, `_hook_stop`, `_hook_sessionstart`
- **Used by:** Build orchestration & engine guard (3), Insights & benchmark showcase (2), Repo adoption scaffolding (2), Semantic overlay machinery (2), Graph query engine (2)
- **Depends on:** Layer IO & health core (4), Insights & benchmark showcase (2), Semantic overlay machinery (2), Doctor & isolation checks (2), Graph query engine (2)
- **External dependencies:** `MANIFEST`, `SCAN_EXT`, `SKIP_DIRS`, `STALE`, `_COMMON_SCOPES`, `_PREPUSH_MARK`

### Layer IO & health core — 20 components (community 0)

The shared core: committed-layer reading, fused materialization, and the health pass.

read_layer validates schema and rejects corrupt layers loudly; materialize fuses the committed layers into the gitignored graph.json consumers read; health computes the structural/semantic/combined metrics with the layered dead-code tiers (dispatches edges, triage verdicts, dynamic_refs heuristic).

- **Key components:** `AdaptResult`, `health`, `materialize`, `read_layer`, `dynamic_refs`, `prep_tasks`
- **Used by:** Semantic overlay machinery (5), Graph fusion & curation (4), CLI dispatch & freshness status (4), Substrate adapters & id model (4), Insights & benchmark showcase (2)
- **Depends on:** Doc-coverage metrics (2), Structural analytics (2), Committed-layer writers (2), CLI dispatch & freshness status (1), Technical-debt assessment (1)
- **Public surface:** `AdaptResult`, `degree_graph`, `from_structural`, `materialize`, `read_layer`
- **External dependencies:** `LINKABLE_KINDS`, `SCHEMA_VERSION`, `_COMMENT_MARKERS`, `_DOC_EXCLUDE_DIRS`, `_TEST_DIRS`, `_build_fg`

### Insights & benchmark showcase — 17 components (community 1)

GRAPH_INSIGHTS.md rendering plus the token-reduction benchmark.

Composes health and benchmark into a content-deterministic, GitHub-native report (mermaid quadrant, debt scorecard, coverage gauges); benchmark measures graph-guided retrieval vs naive full-file reads per query class.

- **Key components:** `render_markdown`, `build_insights`, `benchmark`, `_insights`, `row`, `_tokenizer`
- **Used by:** CLI dispatch & freshness status (2)
- **Depends on:** Layer IO & health core (2), CLI dispatch & freshness status (2)
- **External dependencies:** `_GLOSSARY`, `health`, `read_layer`, `resolve`

### Substrate adapters & id model — 15 components (community 3)

codegraph/TS output → graphify nodes/edges, keyed by the composite id.

The composite id hashes (file, qualified_name, kind, signature) so it survives line-shifting edits; adapt maps the codegraph SQLite db, adapt_ts the TS extractor, and py_calls.enrich supplements Python cross-module call and value-reference edges.

- **Key components:** `adapt`, `enrich`, `composite_id`, `_adapt_repo`, `adapt_ts`, `read_codegraph_db`
- **Used by:** Graph fusion & curation (1), Build orchestration & engine guard (1)
- **Depends on:** Layer IO & health core (4), Doctor & isolation checks (1)
- **Public surface:** `adapt`, `composite_id`, `read_codegraph_db`
- **External dependencies:** `AdaptResult`, `EDGE_RELATION`, `PROV_CONFIDENCE`, `TS_EDGE_RELATION`, `_CALL_KINDS`, `_REF_KINDS`

### Structural analytics — 13 components (community 4)

The pure, offline metric spine over the committed structural layer.

One digraph builder feeds centrality, cycles (with suggested cuts), conductance, Martin coupling/instability with the cross-community neighbor map, abstractness/distance, fan-out, and the dead-code review queue with its entry-point filter.

- **Key components:** `analyze`, `abstractness_distance`, `centrality`, `build_digraph`, `dead_code`, `cycles`
- **Used by:** Layer IO & health core (2), Graph query engine (1)
- **External dependencies:** `_CONTAINMENT`, `_TYPE_KINDS`

### Semantic overlay machinery — 12 components (community 5)

The dev-owned doc→code layer: prep → agent payloads → merge.

prep_tasks writes per-doc tasks (identity metadata only, never source); merge_semantic validates every edge endpoint, resolves target_label by unique normalized label, and prunes ambiguity rather than guessing; the baseline stamp makes doc/linked-code edits surface as staleness.

- **Key components:** `merge_semantic`, `write_semantic_freshness`, `_semantic_merge`, `_label_index`, `semantic_baseline`, `merge_payloads`
- **Used by:** CLI dispatch & freshness status (2), Layer IO & health core (1)
- **Depends on:** Layer IO & health core (5), CLI dispatch & freshness status (2), Committed-layer writers (1)
- **External dependencies:** `AdaptResult`, `MANIFEST`, `SKIP_DIRS`, `_STEM_KINDS`, `_load_structural`, `materialize`

### Doctor & isolation checks — 11 components (community 6)

Runtime-dependency probes and tool-isolation conflict detectors.

Verifies node/codegraph/typescript availability with actionable hints, and warns when a codegraph MCP, graphify rebuild hook, or schema clash would shadow the committed graph. Advisory and fail-open — findings never change an exit code.

- **Key components:** `_check_conflicts`, `_substrate_version`, `_detect_codegraph_mcp`, `doctor_report`, `_codegraph_bin`, `_detect_graphify_rebuild_hooks`
- **Used by:** CLI dispatch & freshness status (2), Build orchestration & engine guard (1), Substrate adapters & id model (1)
- **Depends on:** CLI dispatch & freshness status (1)
- **External dependencies:** `_GRAPHIFY_HOOK_MARK`, `resolve`

### TS substrate — declaration pass — 11 components (community 13)

Pass 1 of the type-aware TypeScript extractor.

Walks each source file with a scope stack emitting one node per declaration (qualified by file and nesting), stamping the Martin-metric inputs (is_abstract, is_exported) from modifier flags.

- **Key components:** `visit`, `isExportedOf`, `modOf`, `isAbstractOf`, `lineOf`, `walk`
- **Depends on:** TS substrate — reference pass (2)
- **External dependencies:** `containerId`, `rel`

### Graph query engine — 9 components (community 7)

Offline callers/callees/impact navigation over the committed graph.

Resolves a human-typed name (label → qualified name → suffix, ambiguity surfaced), then BFS-traverses the dependency digraph by hop, annotating direct hits with their concrete relations. Works on a fresh clone with no index — unlike codegraph's own live-db query.

- **Key components:** `_query_cmd`, `_traverse`, `callers`, `impact`, `callees`, `_relation_map`
- **Used by:** CLI dispatch & freshness status (2)
- **Depends on:** CLI dispatch & freshness status (2), Layer IO & health core (1), Structural analytics (1)
- **External dependencies:** `build_digraph`, `read_layer`, `resolve`

### Committed-layer writers — 8 components (community 8)

Deterministic serialization of the two committed layers.

write_structural/write_semantic emit byte-stable JSON (sorted keys, stable ordering), plus GRAPH_REPORT.md and the gitignore block that keeps derived caches local.

- **Key components:** `write_structural`, `write_semantic`, `write_artifact`, `_write_json`, `_write_gitignore`, `_write_graph_json`
- **Used by:** Layer IO & health core (2), Build orchestration & engine guard (1), Semantic overlay machinery (1)
- **Depends on:** Layer IO & health core (1)
- **Public surface:** `write_artifact`, `write_semantic`, `write_structural`
- **External dependencies:** `SCHEMA_VERSION`, `_GITIGNORE_MARK`, `materialize`

### Python value-reference extraction — 7 components (community 9)

The visitor that turns value-position uses into structural edges.

Calls resolve through import aliases; bare names, kwarg function refs, and constant chain roots become `references` edges — the reason argparse handlers and module constants no longer look dead.

- **Key components:** `_root_ref`, `visit_Call`, `_shadowed`, `_dotted`, `visit_Attribute`, `visit_Name`

### Graph fusion & curation — 7 components (community 10)

Library composition over graphify: cluster, fold, curate.

build_fused clusters the analysis view and computes god nodes; singleton folding keeps community structure meaningful; linkable_subset curates the node list handed to overlay agents.

- **Key components:** `build_fused`, `analysis_view`, `fold_singleton_communities`, `linkable_subset`, `prune_orphans`, `_is_test_path`
- **Used by:** Build orchestration & engine guard (1)
- **Depends on:** Layer IO & health core (4), Substrate adapters & id model (1)
- **Public surface:** `analysis_view`, `apply_communities`, `build_fused`, `fold_singleton_communities`, `linkable_subset`, `prune_orphans`
- **External dependencies:** `ANALYSIS_EXCLUDE_KINDS`, `ANALYSIS_EXCLUDE_RELATIONS`, `AdaptResult`, `LINKABLE_KINDS`, `adapt`

### Build orchestration & engine guard — 6 components (community 11)

The build path and the determinism guards around it.

build_repo routes to the right substrate, re-execs under a pinned PYTHONHASHSEED, stamps engine/substrate versions, and refuses to overwrite a graph built by a different clustering engine — CI stays the single authoritative builder.

- **Key components:** `detect_engine`, `build_repo`, `check_engine_compat`, `check_substrate_drift`, `_ver`, `_installed`
- **Used by:** Repo adoption scaffolding (1), CLI dispatch & freshness status (1)
- **Depends on:** CLI dispatch & freshness status (3), Graph fusion & curation (1), Substrate adapters & id model (1), Doctor & isolation checks (1), Committed-layer writers (1)
- **External dependencies:** `SCHEMA_VERSION`, `_adapt_repo`, `_default_scopes`, `_substrate_version`, `build_fused`, `read_manifest`

### Repo adoption scaffolding — 4 components (community 12)

Everything `init` wires into a consumer repo's Claude/git config.

Writes the SessionStart/Stop hooks into committed .claude/settings.json, hard-blocks a project-local codegraph MCP, and registers the per-clone semantic union merge driver. Idempotent; preserves pre-existing user settings.

- **Key components:** `_init`, `configure_merge_driver`, `write_claude_hooks`, `_resolve_hook_cmd`
- **Used by:** CLI dispatch & freshness status (1)
- **Depends on:** CLI dispatch & freshness status (2), Contract-file writers (2), Build orchestration & engine guard (1), CI workflow scaffolding (1), Git freshness hooks (1)
- **External dependencies:** `_write_agents_md`, `_write_gitattributes`, `build_repo`, `install_freshness_hooks`, `install_prepush_hook`, `resolve`

### Sample fixture — auth — 4 components (community 14)

Test fixture: the AuthService half of the sample repo.

Exists so codegraph-backed tests and the overlay protocol have a tiny real codebase with documented symbols to link against.

- **Key components:** `process`, `login`, `process_helper`, `AuthService`

### Doc-coverage metrics — 4 components (community 15)

The semantic and combined halves of health.

Doc coverage overall/by-kind/public-API, dangling links and orphan docs, god-node and centrality-weighted coverage, dark subsystems, and the undocumented-load-bearing risk queue — 'are we documenting what matters'.

- **Key components:** `semantic_health`, `combined_health`, `_documented_targets`, `_code_nodes`
- **Used by:** Layer IO & health core (2)

### Semantic union merge driver — 3 components (community 16)

The git merge driver for two branches that both extended the overlay.

Unions semantic_nodes by id and edges by (source, target, relation), deterministically sorted — two PRs adding doc→code edges merge without conflict; over-inclusion is pruned as dangling at the next merge.

- **Key components:** `_merge_driver`, `ekey`, `_load`
- **Used by:** CLI dispatch & freshness status (1)
- **External dependencies:** `SCHEMA_VERSION`

### Sample fixture — billing — 3 components (community 17)

Test fixture: the BillingService half of the sample repo.

Paired with the auth fixture to give cross-module edges and doc links a stable target.

- **Key components:** `process`, `charge`, `BillingService`

### Python import resolution — 3 components (community 18)

The alias tables behind the Python edge supplement.

Resolves relative imports against the importing file's package and absolute imports by unique path-suffix match — ambiguity never guesses; `from x import name` is itself recorded as a reference.

- **Key components:** `_resolve_module`, `visit_Import`, `visit_ImportFrom`

### TS substrate — reference pass — 3 components (community 19)

Pass 2 of the TypeScript extractor: type-checker-resolved references.

Every identifier resolves through the compiler's symbol table (alias-following) back to a pass-1 declaration — dense, import-proof cross-file calls/references plus heritage edges.

- **Key components:** `rel`, `emitFile`, `containerId`
- **Used by:** TS substrate — declaration pass (2)

### Contract-file writers — 3 components (community 20)

AGENTS.md and .gitattributes scaffolding.

Marker-based idempotent appends ship the agent contract and the semantic merge-driver declaration into consumer repos without ever clobbering existing content.

- **Key components:** `_write_agents_md`, `_write_gitattributes`, `_append_once`
- **Used by:** Repo adoption scaffolding (2)
- **External dependencies:** `_AGENTS_MARK`, `_GITATTR_MARK`

### CI workflow scaffolding — 2 components (community 21)

Installs the build-on-PR-branch GitHub Actions workflow.

Ships the template that rebuilds structural on every PR and commits it onto the PR's own branch (diff-gated, loop-safe), with opt-in insights/FAQ renders; never clobbers a customized workflow.

- **Key components:** `write_ci_workflow`, `_read_template`
- **Used by:** Repo adoption scaffolding (1)
- **External dependencies:** `files`

### Git freshness hooks — 2 components (community 22)

The universal (non-Claude) freshness reminders.

Installs post-commit/merge/checkout hooks that recompute the source hash and drop a stale marker on drift — husky-aware, never blocking, portable across clones.

- **Key components:** `install_freshness_hooks`, `_install_hook`
- **Used by:** Repo adoption scaffolding (1), CLI dispatch & freshness status (1)
- **Depends on:** CLI dispatch & freshness status (1)
- **External dependencies:** `_HOOK_MARK`, `resolve`

### Technical-debt assessment — 2 components (community 23)

The transparent 0–1 debt roll-up.

Aggregates existing signals (cycles, zone-of-pain, god-objects, fan-out, dead code, dangling links) into ranked by-type/by-feature/by-component breakdowns with per-type score contributions — never an opaque number.

- **Key components:** `debt_assessment`, `_add`
- **Used by:** Layer IO & health core (1)
- **External dependencies:** `_DEBT_SAT`, `_DEBT_WEIGHTS`

### Health report rendering — 2 components (community 24)

The human-readable markdown render of the health pass.

Formats structural/semantic/combined findings with the actions they imply, matching the GRAPH_REPORT conventions.

- **Key components:** `_health`, `render_report`
- **Used by:** CLI dispatch & freshness status (1)
- **Depends on:** Layer IO & health core (1), CLI dispatch & freshness status (1)
- **External dependencies:** `health`, `resolve`

### Python scope shadowing — 2 components (community 25)

The conservatism guard for bare-name resolution.

Collects params and assignment targets per function scope (global/nonlocal un-shadow) so a local variable never mis-resolves to a module-level symbol — no guessing.

- **Key components:** `_local_names`, `_scoped`

### Consumer read & degradation — 2 components (community 26)

The never-block read path for graph consumers.

load_fused prefers the materialized graph.json, re-materializes from committed layers when missing or corrupt, and degrades to best-effort raw-layer reads — the graph is an accelerator, never a dependency.

- **Key components:** `load_fused`, `_file_read_fallback`
- **Depends on:** Layer IO & health core (1)
- **Public surface:** `load_fused`
- **External dependencies:** `materialize`

## Where is the technical debt?

**Score 0.311** (0 = clean → 1 = heavy) · god-object: 14 · high-fan-out: 7 · zone-of-pain: 3

| Feature | Debt items |
|---|--:|
| Layer IO & health core | 7 |
| CLI dispatch & freshness status | 3 |
| Build orchestration & engine guard | 2 |
| Repo adoption scaffolding | 2 |
| Substrate adapters & id model | 2 |
| TS substrate — declaration pass | 1 |
| Sample fixture — auth | 1 |
| Sample fixture — billing | 1 |

| Component | Debt items |
|---|--:|
| `src/cg_graphify_bridge/cli.py` | 11 |
| `src/cg_graphify_bridge/health.py` | 2 |
| `src/cg_graphify_bridge/semantic.py` | 2 |
| `src/cg_graphify_bridge/adapter.py` | 1 |
| `src/cg_graphify_bridge/driver.py` | 1 |
| `src/cg_graphify_bridge/engine.py` | 1 |
| `src/cg_graphify_bridge/py_calls.py` | 1 |
| `src/cg_graphify_bridge/query.py` | 1 |

---

_Generated by [cg-graphify-bridge](https://github.com/evannordinpro/cg-graphify-bridge) from the committed knowledge graph. Quantitative facts are rebuilt by CI each graph build; the narrative lives in `graphify-out/faq.json` and is refreshed by the dev's agent only when the relevant feature's code changes._
