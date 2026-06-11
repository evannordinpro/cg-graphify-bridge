# Internals — how the load-bearing pieces work

Maintainer-facing companion to [`setup.md`](setup.md) (operating the tool) and
[`using-the-graph.md`](using-the-graph.md) (consuming its output). This doc covers the
implementation internals the user docs never need to mention — the symbols the graph's own
risk queue ranks as central-but-undocumented. Organized by subsystem.

## Query engine (`query.py`)

All three commands (`callers` / `callees` / `impact`) are one engine, `_traverse`, behind three
thin wrappers:

- **`resolve(structural, name)`** turns a human-typed name into node(s) with strict precedence:
  exact `label` → exact `qualified_name` → suffix match on either. It returns **all** matches at
  the first tier that hits — ambiguity is surfaced to the caller (the CLI lists candidates and
  exits non-zero), never silently picked. The inner `srt` helper sorts every tier by node id so
  candidate order is deterministic across runs.
- **`_traverse(structural, name, direction, depth)`** resolves the name (bailing out with the
  candidate list unless exactly one match), builds the dependency digraph via
  `analytics.build_digraph` (edge source→target = "source depends on target"; `contains` edges
  excluded), then runs `_layered` — a plain BFS over `dg.predecessors` (callers/impact) or
  `dg.successors` (callees) that records each node's hop distance. Hop-1 results are annotated
  with their concrete relations (`calls` / `imports` / …) via `_relation_map`; deeper hops are
  reachability, not a specific edge. `impact` is just `callers` with `depth=None` (unbounded).
- Results are sorted `(hop, id)` — byte-stable output for a fixed graph.

The module exists because codegraph's own query is locked to the live `.codegraph` db; this one
runs offline over the **committed** `structural.json`, so it works on a fresh clone with no index.

## Label resolution in the overlay merge (`semantic.py`)

When a semantic payload edge has no exact composite id, `merge_semantic` resolves its
`target_label` through `_label_index`:

- **`_norm(s)`** is the normalizer everything is keyed by: lowercase, strip every
  non-alphanumeric (`Adapt_Result` ≡ `adaptresult`). Doc prose is messy; this makes label
  matching case/punctuation-proof.
- `_label_index` maps `_norm(label)` → `[composite ids]`, and **also** indexes
  file/module/namespace nodes by their extension-stripped stem (`_stem_norm`), so a doc
  mentioning `billing.ts` resolves to that file node.
- **The consequence to remember:** a function whose name equals its file's stem (`health` in
  `health.py`, `materialize`, `adapt`, …) is **ambiguous by construction** — the index holds both
  the function and the file stem. Such edges are pruned (reported, never guessed); pin them with
  the exact composite id in the payload. The merge prunes rather than guesses because a wrong
  doc→code edge is worse than a missing one.
- The prep task files are the egress boundary: agents get identity metadata only
  (`{id, label, file, kind}` — `curated_nodes` for degree-ranked task lists, `linkable_subset`
  for the kind-filtered contract surface) plus doc text — **never source code** (R7).
- **`dispatch_candidates`** turns the dead-code heuristic into curated graph data: it re-runs
  `health.dynamic_refs` over the production scope, attributes each evidence line to its
  enclosing declaration (`py_calls._caller_of` over node line spans), and writes the candidate
  list for the agent to confirm as code→code `dispatches` edges. `merge_semantic` validates the
  *source* of every edge too (a payload semantic node or an existing code id) so a dispatch
  site can't be invented; `health` treats confirmed targets as authoritatively live and
  `_documented_targets` excludes the relation from coverage.

## Freshness fingerprints (`freshness.py`)

Both layers' staleness reduce to content hashes compared against baselines stamped at
build/merge time:

- **`_iter_sources(repo, scopes)`** defines what "in-scope source" means everywhere: walk each
  scope, keep `SCAN_EXT` suffixes (`.ts .tsx .js .jsx .py .go .rs`), prune `SKIP_DIRS`
  (node_modules, graphify-out, .venv, …) and `.d.ts`. Sorted walk → deterministic iteration.
- **`source_hash(repo, scopes)`** is the structural fingerprint: sha256 over
  `(relpath, size, bytes)` of every in-scope file — content-based, not mtime, so it's stable
  across checkouts and machines. `build` stamps it into `.cg_manifest.json`; `status` recomputes
  and compares.
- **`semantic_baseline(out, repo)`** is the overlay's fingerprint, two hashes: all `*.md` docs
  (`_iter_docs`), and the **linked** source files — `linked_files` maps each semantic edge's
  target node to its `source_file`. The split is the point: editing a code file no semantic edge
  touches leaves the overlay fresh (no busywork); editing a *linked* file or any doc stales it.
  Stamped by `semantic-merge` (`write_semantic_freshness`), preserved across structural rebuilds
  by `write_manifest`.
- The git-hook path (`check_stale`) is marker-based (`.cg_stale` dropped on drift, consumed by
  the next build) and deliberately stdlib-only so a bare-`python3` hook works without the
  package's heavy deps.

## TS substrate (`ts_substrate_js/extract.cjs`)

The type-aware extractor for TS repos — the reason TS doesn't need the `py_calls` supplement:

- **`files` / `walk`** collect `.ts/.tsx` sources under the scopes with entries **sorted**
  (readdir returns inode order; KD3) so node ids are machine-independent. **`rel`** keys
  everything by repo-relative path — composite ids must not embed absolute paths.
- **Pass 1 (`visit`, declarations):** walks each source file with a scope stack, emitting one
  node per declaration with `qualified_name = file::Outer.Inner.name`, plus `contains` edges.
  Arrow/function-expression `const f = () => …` declarations are normalized to `function` nodes.
  **`modOf`** reads combined modifier flags to stamp the Martin-metric inputs: `is_abstract`
  (interfaces by definition, else the `abstract` modifier) and `is_exported` (the `export`
  modifier — feeds public-API coverage).
- **Pass 2 (references):** every identifier is resolved through the **type checker**
  (`getSymbolAtLocation`, alias-following via `getAliasedSymbol`) back to a pass-1 declaration —
  this is what makes cross-file edges dense and import-alias-proof. Call-position identifiers
  become `calls` edges, the rest `references`; heritage clauses become `extends`/`implements`.
  `containerId` attributes each reference to its innermost enclosing declaration (file node
  fallback).

## Python edge supplement (`py_calls.py`)

codegraph resolves same-file Python calls only, so `enrich` adds what's missing (full rationale
in [`setup.md`](setup.md) §1): cross-module `calls`, value-position `references` (kwarg function
refs, constant reads — imported, `mod.CONST`, or same-file module-level), `from x import name`
as a reference, and `is_exported` stamps from module-level `__all__`. Pieces worth knowing:
**`_resolve_module`** — relative imports resolve against the importing file's package directory
(walking up `level-1` dirs, then trying `<path>.py` and `<path>/__init__.py`); absolute imports
resolve by **unique** path-suffix match over the indexed file set — two matches means ambiguous
means no edge. **Shadow tracking** — bare-name value refs resolve only when no enclosing
function scope binds the name (`_local_names` collects params + assignment targets,
over-collecting nested defs on purpose; `global`/`nonlocal` un-shadow). Caller attribution
reuses the node line spans (innermost enclosing def/class wins, file node for module-level
sites), so it never re-derives codegraph's qualified-name scheme.

## Layer IO and scaffolding (`driver.py`, `scaffold.py`, `hooks.py`, `doctor.py`)

`cli.py` is the composition root only — the argparse surface plus thin handlers. The
implementations live in three stdlib-only modules: `scaffold.py` (everything `init` writes
into a consumer repo), `hooks.py` (git-hook installers + the Claude-hook gate helpers — what
Phase 6's faq gate will clone), and `doctor.py` (dependency probes + the tool-isolation
conflict detectors).

- **`read_layer(outdir, name)`** is the single gate for reading a committed layer: returns
  `None` when the file is absent (callers decide if that's fatal), but **raises** on corrupt
  JSON or a `schema_version` mismatch — a malformed layer is rejected loudly, never silently
  consumed (R10). Consumer reads degrade instead via `load_fused`'s fallback chain.
- **`_append_once(path, marker, block)`** is `init`'s idempotency primitive for shared files
  (`AGENTS.md`, `.gitattributes`): append the marker-carrying block only if the marker isn't
  already present — re-running `init` never duplicates, and pre-existing user content is never
  clobbered.
- **`_resolve_hook_cmd(sub, out_name)`** builds the command line committed into
  `.claude/settings.json` for the SessionStart/Stop hooks: the bare pipx-installed
  `cg-graphify-bridge` on PATH (every consumer installs the tool), with `--out` appended only
  for non-default out dirs — committed settings stay machine-portable.
