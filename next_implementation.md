# Next implementation — `PROJECT_FAQ.md` + auto-narrative mechanism

> **Status:** PLANNED, deferred (2026-06-11). Strategy + decisions locked; not yet built.
> This is the next feature after the shipped insights stack (isolation, benchmarks/health, query
> surface, `GRAPH_INSIGHTS.md`, technical-debt assessment). Pick up from here.

## The idea in one line
A second versioned, CI-built doc — **`PROJECT_FAQ.md`** at the repo root — that answers evolving
questions about the project (what is it, what are its features, where's the technical debt) by
combining **deterministic graph computation** with a **narrative synthesized automatically by the
dev's own Claude Code instance** (no manual step, no LLM in CI).

## Two halves
**1. Quantitative (deterministic, computed in CI — no LLM):**
- *What are the features?* → Leiden **communities** are the features; their members are the
  components; **upstream/downstream nearest-neighbors** = cross-community coupling (already computed
  inside `analytics.coupling_instability`, just needs exposing).
- *Feature input/output* → externally-called `is_exported` entry points vs the symbols it calls outward.
- *Where is the most technical debt? (by feature / component / type)* → **reuse Phase 5's
  `health()["debt"]`** rollups directly.

**2. Narrative (synthesized by the dev's Claude — committed, matures over time):**
- *What is this project? purpose / business problem / value proposition*, and per-feature
  concept + functionality. Not derivable from the graph → needs synthesis.

## The auto-narrative mechanism (the novel part)
Validated via `claude-code-guide`: hooks **cannot** inject a prompt Claude obeys, but an **observable
tool failure is a reliable forcing function**, and `CLAUDECODE=1` distinguishes Claude-driven from
human commits.

```
dev's Claude edits code → git push
  └─ pre-push gate (CLAUDECODE-aware): did a changed feature's narrative go stale?
       ├─ Claude committing → exit≠0 with an imperative:
       │     "run `cg-graphify-bridge faq-prep` → fill payloads → `faq-merge`, then re-push"
       │   → Claude sees the failure, writes narrative into the EPHEMERAL .cache/faq scratch,
       │     `faq-merge` commits faq.json, re-pushes ✓  (no manual dev step)
       └─ human committing → soft-warn + escape hatch (CG_BRIDGE_DISABLE / ~/.claude/state/cg-bridge/OFF)
```

**Ephemeral vs persistent (never-touches-main contract):**
- **Ephemeral** = `graphify-out/.cache/faq/` scratch (tasks + Claude's raw narrative payloads).
  **Gitignored** → never committed, never on main; deleted by `faq-merge`.
- **Persistent (versioned on main)** = `graphify-out/faq.json` (narrative store, mirrors
  `semantic.json`) + the rendered `PROJECT_FAQ.md` at repo root.
- **CI stays LLM-free** — it only deterministically *renders* `PROJECT_FAQ.md` from the committed
  `faq.json` + freshly-computed quantitative metrics, and commits it (diff-gated, content-deterministic).
- Narrative is regenerated **only when the relevant code changed** (per-feature staleness), so
  `faq.json` is stable/versionable, not churned every build.

## Locked decisions (DEC-1…DEC-6)
1. **DEC-1** — enforcement = CLAUDECODE-aware **pre-push gate** (clone the existing semantic pre-push gate); not every-commit.
2. **DEC-2** — ephemeral gitignored `.cache/faq` scratch → `faq-merge` → committed `faq.json` + `PROJECT_FAQ.md`.
3. **DEC-3** — phasing: this is Phase 6 (after Phase 5 debt, which it reuses).
4. **DEC-4** — (was stale-comment depth) — N/A; stale-docs/comments were dropped from Phase 5.
5. **DEC-5** — human-commit fallback = soft-warn + escape hatch now; **AWS Bedrock via the EC2 API
   deferred** (preferred synthesis engine later, once dev-tested).
6. **DEC-6** — "feature" unit = Leiden community (narrative can name/group them); Q&A set = what-is-this,
   features+neighbors+IO, debt-by-feature/component/type, and grows as `faq.json` matures.

## Reuse (~75% of the semantic-overlay machinery)
| Existing | Reused for |
|---|---|
| `semantic.prep_tasks` / `merge_payloads` | `faq-prep` / `faq-merge` (faq/ scratch subdir, narrative payload schema) |
| `driver.write_semantic` + deterministic `_write_json` | `write_faq` → `faq.json` |
| `freshness.write_semantic_freshness` / `compute_status` | per-feature narrative baseline + staleness (new manifest key `faq`) |
| `cli.install_prepush_hook` / `_hook_stop` / `_check_semantic` + escape hatches | CLAUDECODE-aware faq gate (the one NEEDS-NEW branch) |
| `insights._write`-style render / `health()["debt"]` | `PROJECT_FAQ.md` render + debt-by-feature |

## Implementation outline (building blocks)
- **KD1** expose nearest-neighbor cross-community map from `coupling_instability`.
- **KD5** `faq.json` committed narrative store (clone `write_semantic`).
- **KD6** `faq-prep` / `faq-merge` (clone prep/merge; faq/ scratch; narrative payload schema).
- **KD7** faq baseline + per-feature staleness (clone freshness).
- **KD8** CLAUDECODE-aware pre-push + Stop gate + escape hatch (clone `install_prepush_hook`/`_hook_stop`).
- **KD9** quantitative FAQ computations (features/components/neighbors/IO; debt-by-X reuses Phase 5).
- **KD10** `PROJECT_FAQ.md` render (quantitative + committed narrative).
- **KD11** CI wiring: render `PROJECT_FAQ.md` (LLM-free) + diff-gated commit; consumer opt-in via a `CG_FAQ` var (tool repo always-on, like `GRAPH_INSIGHTS.md`).
- **KD12** `faq-prep` / `faq-merge` skill so Claude auto-invokes on the gate's instruction.

## Determinism + safety
- `PROJECT_FAQ.md` must be **content-deterministic** (no timestamp/SHA) so it rides the diff-gate
  (verified pattern: `GRAPH_INSIGHTS.md` post-merge rebuild is a no-op).
- The gate **fails open** and honors the escape hatch (mandatory): a guard error must never brick a commit.
- CLAUDECODE detection enables graceful degradation: enforce when Claude is present, soft-warn for humans.

## Where to resume
- Open the Phase 6 dev-cycle (requirements → design → tasks) — the decisions above are settled.
- Full pre-planning detail (4-table inventory, hook-feasibility findings, reuse map) lives in the
  ephemeral planning workspace: `~/AppDev/cg-bridge-planning/PHASE5-6-FAQ-DEBT-RESEARCH.md`.
- Reference implementations to clone: `src/cg_graphify_bridge/semantic.py`, `freshness.py`,
  `insights.py`, and the enforcement wiring in `cli.py` (`install_prepush_hook`, `_hook_stop`).
