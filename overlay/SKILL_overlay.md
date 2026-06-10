<!-- OVERLAY-MODE PATCH for graphify SKILL.md (applied to the fresh global skill at promote, Phase 4 / T4.2).
     Injected into the semantic-extraction (Part B) subagent instructions. Trace: R4, D6, D17. -->

## Overlay mode: codegraph is the code substrate

When `graphify-out/.cg_overlay` is present, graphify does **not** run its own code AST
extraction. Code nodes come from codegraph via the bridge adapter, identified by a
**composite id** `cg:<hash(file_path, qualifiedName, kind, signature)>`.

### Semantic subagent contract (overlay mode)

Each semantic-extraction subagent is handed a **codegraph node list** scoped to its
community — entries of the form `{composite_id, label, file, cg_kind}`. The subagent
reads the assigned docs/PDFs/images and emits concept/doc nodes plus doc→code edges.

Rules (MANDATORY):
1. Every doc→code edge MUST set `target` to the **exact `composite_id`** from the
   provided codegraph node list. Do **not** invent ids and do **not** emit graphify-style
   AST ids — those don't exist in overlay mode.
2. If you cannot determine the id but know the symbol name, set `target_label` to the
   name and leave `target` empty; the bridge resolves it by unique label match, or prunes
   and reports it (no silent dangling edges).
3. You are given **no source code** — only identity metadata + the documents. Never
   request or emit code bodies (egress discipline, R7).
