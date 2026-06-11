# 📒 PROJECT_FAQ — cg-graphify-bridge

_Deterministic graph facts + committed narrative ([how this file is produced](docs/setup.md))._

## What is this project?

**What.** cg-graphify-bridge fuses codegraph (a deterministic code substrate) with graphify (a semantic, cross-domain overlay) into one committed, queryable knowledge graph for any repository, joined on a line-shift-stable composite id.

**Purpose.** Code knowledge graphs rot: local indexes drift, rebuilds churn artifacts, and documentation links break silently. The bridge makes the graph a versioned, byte-deterministic artifact — CI owns the structural layer, developers (via their agents) own the doc-to-code and narrative layers, and freshness gates keep every layer honest with near-zero manual effort.

**Value.** Agents and humans navigate by graph instead of cold file scans (~96% less context per question), architecture and documentation health are continuously measured (insights, debt, risk queues), and the whole thing survives clones, rebuilds, and refactors because every artifact is committed and deterministic.

## What are the features?

### CLI dispatch & freshness status — 28 components (community 1)

The argparse composition root plus the status/freshness surface.

main wires every subcommand; compute_status reports per-layer freshness (structural = source hash vs build baseline, semantic = docs+linked files vs merge baseline) with exact refresh commands; the Stop hook blocks ending a session on a stale or uncommitted layer, fail-open with an escape hatch.

- **Key components:** `main`, `write_manifest`, `compute_status`, `_hook_stop`, `_hook_sessionstart`, `_status`
- **Used by:** engine / cli (2), PROJECT_FAQ machinery (2), Repo adoption scaffolding (1)
- **Depends on:** PROJECT_FAQ machinery (14), driver (3), Insights & benchmark showcase (2), Doctor & isolation checks (2), engine / cli (1)
- **External dependencies:** `MANIFEST`, `SCAN_EXT`, `SKIP_DIRS`, `STALE`, `_COMMON_SCOPES`, `_PREPUSH_MARK`

### Substrate adapters & id model — 23 components (community 0)

codegraph/TS output → graphify nodes/edges, keyed by the composite id.

The composite id hashes (file, qualified_name, kind, signature) so it survives line-shifting edits; adapt maps the codegraph SQLite db, adapt_ts the TS extractor, and py_calls.enrich supplements Python cross-module call and value-reference edges.

- **Key components:** `AdaptResult`, `adapt`, `enrich`, `build_fused`, `analysis_view`, `composite_id`
- **Used by:** Layer IO & health core (5), engine / cli (2), PROJECT_FAQ machinery (1)
- **Depends on:** Layer IO & health core (1), Doctor & isolation checks (1)
- **Public surface:** `AdaptResult`, `adapt`, `analysis_view`, `apply_communities`, `build_fused`, `composite_id`, `fold_singleton_communities`, `linkable_subset`
- **External dependencies:** `ANALYSIS_EXCLUDE_KINDS`, `ANALYSIS_EXCLUDE_RELATIONS`, `EDGE_RELATION`, `LINKABLE_KINDS`, `PROV_CONFIDENCE`, `TS_EDGE_RELATION`

### Insights & benchmark showcase — 18 components (community 2)

GRAPH_INSIGHTS.md rendering plus the token-reduction benchmark.

Composes health and benchmark into a content-deterministic, GitHub-native report (mermaid quadrant, debt scorecard, coverage gauges); benchmark measures graph-guided retrieval vs naive full-file reads per query class.

- **Key components:** `render_markdown`, `build_insights`, `read_layer`, `benchmark`, `_insights`, `row`
- **Used by:** CLI dispatch & freshness status (2), PROJECT_FAQ machinery (2), health (1), Graph query engine (1), driver (1)
- **Depends on:** PROJECT_FAQ machinery (2), health (1)
- **Public surface:** `read_layer`
- **External dependencies:** `SCHEMA_VERSION`, `_GLOSSARY`, `health`, `resolve`

### PROJECT_FAQ machinery — 18 components (community 3)

The Phase 6 narrative layer: deterministic feature facts + dev-owned prose.

feature_map derives features from Leiden communities (members, neighbors, public surfaces, external deps); prep_faq/merge_faq run the agent narrative loop into committed faq.json with per-feature staleness and anchor remapping across re-clusters; render_faq emits the content-deterministic PROJECT_FAQ.md that CI commits.

- **Key components:** `resolve`, `merge_faq`, `read_manifest`, `write_semantic_freshness`, `faq_state`, `_semantic_merge`
- **Used by:** CLI dispatch & freshness status (14), Insights & benchmark showcase (2), Layer IO & health core (2), Graph query engine (2), engine / cli (1)
- **Depends on:** driver (3), CLI dispatch & freshness status (2), Insights & benchmark showcase (2), Structural analytics (2), Substrate adapters & id model (1)
- **Public surface:** `from_structural`
- **External dependencies:** `AdaptResult`, `MANIFEST`, `_NARRATIVE_KEYS`, `_PROJECT_KEYS`, `_hash_paths`, `build_digraph`

### Layer IO & health core — 16 components (community 4)

The shared core: committed-layer reading, fused materialization, and the health pass.

read_layer validates schema and rejects corrupt layers loudly; materialize fuses the committed layers into the gitignored graph.json consumers read; health computes the structural/semantic/combined metrics with the layered dead-code tiers (dispatches edges, triage verdicts, dynamic_refs heuristic).

- **Key components:** `merge_semantic`, `dynamic_refs`, `prep_tasks`, `_label_index`, `_semantic_prep`, `dispatch_candidates`
- **Used by:** health (2), Substrate adapters & id model (1), CLI dispatch & freshness status (1), PROJECT_FAQ machinery (1)
- **Depends on:** Substrate adapters & id model (5), PROJECT_FAQ machinery (2), Structural analytics (1)
- **Public surface:** `degree_graph`
- **External dependencies:** `AdaptResult`, `LINKABLE_KINDS`, `_COMMENT_MARKERS`, `_DOC_EXCLUDE_DIRS`, `_STEM_KINDS`, `_TEST_DIRS`

### Structural analytics — 13 components (community 6)

The pure, offline metric spine over the committed structural layer.

One digraph builder feeds centrality, cycles (with suggested cuts), conductance, Martin coupling/instability with the cross-community neighbor map, abstractness/distance, fan-out, and the dead-code review queue with its entry-point filter.

- **Key components:** `build_digraph`, `analyze`, `abstractness_distance`, `centrality`, `dead_code`, `coupling_instability`
- **Used by:** PROJECT_FAQ machinery (2), health (1), Layer IO & health core (1), Graph query engine (1)
- **External dependencies:** `_CONTAINMENT`, `_TYPE_KINDS`

### Doctor & isolation checks — 11 components (community 5)

Runtime-dependency probes and tool-isolation conflict detectors.

Verifies node/codegraph/typescript availability with actionable hints, and warns when a codegraph MCP, graphify rebuild hook, or schema clash would shadow the committed graph. Advisory and fail-open — findings never change an exit code.

- **Key components:** `_check_conflicts`, `_substrate_version`, `_detect_codegraph_mcp`, `doctor_report`, `_codegraph_bin`, `_detect_graphify_rebuild_hooks`
- **Used by:** CLI dispatch & freshness status (2), Substrate adapters & id model (1), engine / cli (1)
- **Depends on:** PROJECT_FAQ machinery (1)
- **External dependencies:** `_GRAPHIFY_HOOK_MARK`, `resolve`

### TS substrate — declaration pass — 11 components (community 13)

Pass 1 of the type-aware TypeScript extractor.

Walks each source file with a scope stack emitting one node per declaration (qualified by file and nesting), stamping the Martin-metric inputs (is_abstract, is_exported) from modifier flags.

- **Key components:** `visit`, `isExportedOf`, `modOf`, `isAbstractOf`, `lineOf`, `walk`
- **Depends on:** TS substrate — reference pass (2)
- **External dependencies:** `containerId`, `rel`

### driver — 10 components (community 8)

_(narrative pending)_

- **Key components:** `write_structural`, `write_semantic`, `materialize`, `write_artifact`, `write_faq`, `_write_json`
- **Used by:** CLI dispatch & freshness status (3), PROJECT_FAQ machinery (3), engine / cli (1), Consumer read & degradation (1)
- **Depends on:** Insights & benchmark showcase (1)
- **Public surface:** `materialize`, `write_artifact`, `write_semantic`, `write_structural`
- **External dependencies:** `SCHEMA_VERSION`, `_GITIGNORE_MARK`, `read_layer`

### Graph query engine — 9 components (community 7)

Offline callers/callees/impact navigation over the committed graph.

Resolves a human-typed name (label → qualified name → suffix, ambiguity surfaced), then BFS-traverses the dependency digraph by hop, annotating direct hits with their concrete relations. Works on a fresh clone with no index — unlike codegraph's own live-db query.

- **Key components:** `_query_cmd`, `_traverse`, `callers`, `impact`, `callees`, `_relation_map`
- **Used by:** CLI dispatch & freshness status (1), PROJECT_FAQ machinery (1)
- **Depends on:** PROJECT_FAQ machinery (2), Insights & benchmark showcase (1), Structural analytics (1)
- **External dependencies:** `build_digraph`, `read_layer`, `resolve`

### health — 8 components (community 11)

_(narrative pending)_

- **Key components:** `health`, `semantic_health`, `combined_health`, `_documented_targets`, `_code_nodes`, `knowledge_debt`
- **Used by:** Insights & benchmark showcase (1), Health report rendering (1), PROJECT_FAQ machinery (1)
- **Depends on:** Layer IO & health core (2), Insights & benchmark showcase (1), Technical-debt assessment (1), Structural analytics (1)
- **External dependencies:** `analyze`, `debt_assessment`, `dynamic_refs`, `read_layer`, `source_scope`

### Python value-reference extraction — 7 components (community 9)

The visitor that turns value-position uses into structural edges.

Calls resolve through import aliases; bare names, kwarg function refs, and constant chain roots become `references` edges — the reason argparse handlers and module constants no longer look dead.

- **Key components:** `_root_ref`, `visit_Call`, `_shadowed`, `_dotted`, `visit_Attribute`, `visit_Name`

### engine / cli — 6 components (community 10)

_(narrative pending)_

- **Key components:** `detect_engine`, `build_repo`, `check_engine_compat`, `check_substrate_drift`, `_ver`, `_installed`
- **Used by:** CLI dispatch & freshness status (1), Repo adoption scaffolding (1)
- **Depends on:** Substrate adapters & id model (2), CLI dispatch & freshness status (2), PROJECT_FAQ machinery (1), Doctor & isolation checks (1), driver (1)
- **External dependencies:** `SCHEMA_VERSION`, `_adapt_repo`, `_default_scopes`, `_substrate_version`, `build_fused`, `read_manifest`

### Repo adoption scaffolding — 4 components (community 12)

Everything `init` wires into a consumer repo's Claude/git config.

Writes the SessionStart/Stop hooks into committed .claude/settings.json, hard-blocks a project-local codegraph MCP, and registers the per-clone semantic union merge driver. Idempotent; preserves pre-existing user settings.

- **Key components:** `_init`, `configure_merge_driver`, `write_claude_hooks`, `_resolve_hook_cmd`
- **Used by:** CLI dispatch & freshness status (1)
- **Depends on:** Contract-file writers (2), CLI dispatch & freshness status (1), engine / cli (1), CI workflow scaffolding (1), Git freshness hooks (1)
- **External dependencies:** `_write_agents_md`, `_write_gitattributes`, `build_repo`, `install_freshness_hooks`, `install_prepush_hook`, `resolve`

### Sample fixture — auth — 4 components (community 14)

Test fixture: the AuthService half of the sample repo.

Exists so codegraph-backed tests and the overlay protocol have a tiny real codebase with documented symbols to link against.

- **Key components:** `process`, `login`, `process_helper`, `AuthService`

### Semantic union merge driver — 3 components (community 15)

The git merge driver for two branches that both extended the overlay.

Unions semantic_nodes by id and edges by (source, target, relation), deterministically sorted — two PRs adding doc→code edges merge without conflict; over-inclusion is pruned as dangling at the next merge.

- **Key components:** `_merge_driver`, `ekey`, `_load`
- **Used by:** CLI dispatch & freshness status (1)
- **External dependencies:** `SCHEMA_VERSION`

### Sample fixture — billing — 3 components (community 16)

Test fixture: the BillingService half of the sample repo.

Paired with the auth fixture to give cross-module edges and doc links a stable target.

- **Key components:** `process`, `charge`, `BillingService`

### Python import resolution — 3 components (community 17)

The alias tables behind the Python edge supplement.

Resolves relative imports against the importing file's package and absolute imports by unique path-suffix match — ambiguity never guesses; `from x import name` is itself recorded as a reference.

- **Key components:** `_resolve_module`, `visit_Import`, `visit_ImportFrom`

### TS substrate — reference pass — 3 components (community 18)

Pass 2 of the TypeScript extractor: type-checker-resolved references.

Every identifier resolves through the compiler's symbol table (alias-following) back to a pass-1 declaration — dense, import-proof cross-file calls/references plus heritage edges.

- **Key components:** `rel`, `emitFile`, `containerId`
- **Used by:** TS substrate — declaration pass (2)

### Contract-file writers — 3 components (community 19)

AGENTS.md and .gitattributes scaffolding.

Marker-based idempotent appends ship the agent contract and the semantic merge-driver declaration into consumer repos without ever clobbering existing content.

- **Key components:** `_write_agents_md`, `_write_gitattributes`, `_append_once`
- **Used by:** Repo adoption scaffolding (2)
- **External dependencies:** `_AGENTS_MARK`, `_GITATTR_MARK`

### CI workflow scaffolding — 2 components (community 20)

Installs the build-on-PR-branch GitHub Actions workflow.

Ships the template that rebuilds structural on every PR and commits it onto the PR's own branch (diff-gated, loop-safe), with opt-in insights/FAQ renders; never clobbers a customized workflow.

- **Key components:** `write_ci_workflow`, `_read_template`
- **Used by:** Repo adoption scaffolding (1)
- **External dependencies:** `files`

### Git freshness hooks — 2 components (community 21)

The universal (non-Claude) freshness reminders.

Installs post-commit/merge/checkout hooks that recompute the source hash and drop a stale marker on drift — husky-aware, never blocking, portable across clones.

- **Key components:** `install_freshness_hooks`, `_install_hook`
- **Used by:** CLI dispatch & freshness status (1), Repo adoption scaffolding (1)
- **Depends on:** PROJECT_FAQ machinery (1)
- **External dependencies:** `_HOOK_MARK`, `resolve`

### Technical-debt assessment — 2 components (community 22)

The transparent 0–1 debt roll-up.

Aggregates existing signals (cycles, zone-of-pain, god-objects, fan-out, dead code, dangling links) into ranked by-type/by-feature/by-component breakdowns with per-type score contributions — never an opaque number.

- **Key components:** `debt_assessment`, `_add`
- **Used by:** health (1)
- **External dependencies:** `_DEBT_SAT`, `_DEBT_WEIGHTS`

### Health report rendering — 2 components (community 23)

The human-readable markdown render of the health pass.

Formats structural/semantic/combined findings with the actions they imply, matching the GRAPH_REPORT conventions.

- **Key components:** `_health`, `render_report`
- **Used by:** CLI dispatch & freshness status (1)
- **Depends on:** health (1), PROJECT_FAQ machinery (1)
- **External dependencies:** `health`, `resolve`

### Python scope shadowing — 2 components (community 24)

The conservatism guard for bare-name resolution.

Collects params and assignment targets per function scope (global/nonlocal un-shadow) so a local variable never mis-resolves to a module-level symbol — no guessing.

- **Key components:** `_local_names`, `_scoped`

### Consumer read & degradation — 2 components (community 25)

The never-block read path for graph consumers.

load_fused prefers the materialized graph.json, re-materializes from committed layers when missing or corrupt, and degrades to best-effort raw-layer reads — the graph is an accelerator, never a dependency.

- **Key components:** `load_fused`, `_file_read_fallback`
- **Depends on:** driver (1)
- **Public surface:** `load_fused`
- **External dependencies:** `materialize`

## Where is the technical debt?

**Score 0.3123** (0 = clean → 1 = heavy) · god-object: 12 · high-fan-out: 8 · zone-of-pain: 3

| Feature | Debt items |
|---|--:|
| Substrate adapters & id model | 4 |
| PROJECT_FAQ machinery | 3 |
| CLI dispatch & freshness status | 2 |
| engine / cli | 2 |
| health | 2 |
| Repo adoption scaffolding | 2 |
| TS substrate — declaration pass | 1 |
| Sample fixture — auth | 1 |

| Component | Debt items |
|---|--:|
| `src/cg_graphify_bridge/cli.py` | 10 |
| `src/cg_graphify_bridge/health.py` | 2 |
| `src/cg_graphify_bridge/adapter.py` | 1 |
| `src/cg_graphify_bridge/driver.py` | 1 |
| `src/cg_graphify_bridge/engine.py` | 1 |
| `src/cg_graphify_bridge/faq.py` | 1 |
| `src/cg_graphify_bridge/py_calls.py` | 1 |
| `src/cg_graphify_bridge/query.py` | 1 |

---

_Generated by [cg-graphify-bridge](https://github.com/evannordinpro/cg-graphify-bridge) from the committed knowledge graph. Quantitative facts are rebuilt by CI each graph build; the narrative lives in `graphify-out/faq.json` and is refreshed by the dev's agent only when the relevant feature's code changes._
