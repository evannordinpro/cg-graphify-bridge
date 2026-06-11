"""Supplemental Python cross-module call edges (stdlib `ast`) over the adapted substrate.

codegraph 0.9.9 resolves same-file Python calls only: a cross-module call —
`driver.read_layer(...)` after `from . import driver`, or `f()` after `from .x import f` —
yields no `calls` edge, so every cross-module symbol sits at zero in-degree (dead-code false
positives) and centrality/impact understate reality. This pass parses the indexed `.py`
sources, resolves import aliases (module-level and function-local, absolute and relative),
and emits the missing edges. Strictly supplemental to the substrate:

- bare-name calls resolve ONLY through imported-symbol aliases (same-file calls are the
  substrate's job and already edged);
- attribute calls resolve ONLY when the dotted prefix is an imported-module alias
  (`self.x()` / instance methods are out of scope — they need type info we don't have);
- a target must resolve to exactly ONE indexed top-level definition, or it is skipped
  (ambiguous absolute imports never guess).

Deterministic: files walked sorted, AST visited in lexical order, stdlib only; emitted
edges are deduped against the substrate's and stamped context="pyast" /
confidence="INFERRED" so their provenance stays visible in the committed artifact.
"""
from __future__ import annotations

import ast
from pathlib import Path

from .adapter import AdaptResult

# kinds a resolved call may target: functions, and classes (instantiation is a call)
_TARGET_KINDS = {"function", "class"}
# kinds that can own a call site (innermost enclosing span wins; file node is the fallback)
_SCOPE_KINDS = {"function", "method", "class"}


def _resolve_module(modpath: str, cur_file: str, level: int, pyfiles: set) -> str | None:
    """Module reference -> indexed .py path, or None. Relative imports resolve against the
    importing file's package; absolute imports by unique path-suffix match (ambiguous -> None)."""
    if level:
        base = cur_file.split("/")[:-1]
        for _ in range(level - 1):
            if not base:
                return None
            base = base[:-1]
        parts = base + (modpath.split(".") if modpath else [])
        for cand in ("/".join(parts) + ".py", "/".join(parts + ["__init__.py"])):
            if cand in pyfiles:
                return cand
        return None
    if not modpath:
        return None
    parts = modpath.split(".")
    hits = [f for f in sorted(pyfiles)
            if f[:-3].split("/")[-len(parts):] == parts
            or (f.endswith("/__init__.py") and f[:-12].split("/")[-len(parts):] == parts)]
    return hits[0] if len(hits) == 1 else None


def _dotted(node) -> str | None:
    """Attribute chain -> 'a.b.c' when rooted at a plain Name, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class _CallVisitor(ast.NodeVisitor):
    """One pass per file, lexical order: import statements populate the alias tables as they
    appear (so a function-local alias is visible to the calls below it, approximating scope),
    Call nodes resolve through them."""

    def __init__(self, cur_file: str, pyfiles: set, defs: dict):
        self.cur_file, self.pyfiles, self.defs = cur_file, pyfiles, defs
        self.mod_alias: dict[str, str] = {}      # local (possibly dotted) name -> module file
        self.sym_alias: dict[str, tuple] = {}    # local name -> (module file, original name)
        self.calls: list[tuple] = []             # (lineno, target_file, target_name)

    def visit_Import(self, node):
        for a in node.names:
            f = _resolve_module(a.name, self.cur_file, 0, self.pyfiles)
            if f:
                # `import a.b` binds `a` but call sites read `a.b.f()` -> key by the dotted name
                self.mod_alias[a.asname or a.name] = f

    def visit_ImportFrom(self, node):
        for a in node.names:
            if a.name == "*":
                continue
            local = a.asname or a.name
            full = f"{node.module}.{a.name}" if node.module else a.name
            mf = _resolve_module(full, self.cur_file, node.level, self.pyfiles)
            if mf:                               # `from . import driver` — a module alias
                self.mod_alias[local] = mf
                continue
            base = _resolve_module(node.module or "", self.cur_file, node.level, self.pyfiles)
            if base and (base, a.name) in self.defs:   # `from .driver import build_repo`
                self.sym_alias[local] = (base, a.name)

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Name):
            tgt = self.sym_alias.get(f.id)
            if tgt:
                self.calls.append((node.lineno, tgt[0], tgt[1]))
        elif isinstance(f, ast.Attribute):
            dotted = _dotted(f)
            if dotted and "." in dotted:
                prefix, _, name = dotted.rpartition(".")
                mf = self.mod_alias.get(prefix)
                if mf:
                    self.calls.append((node.lineno, mf, name))
        self.generic_visit(node)


def _caller_of(line: int, spans: list, file_node_id: str | None) -> str | None:
    """Innermost def/class whose [start_line, end_line] contains the call; file node fallback."""
    best = None
    for s, e, nid in spans:
        if s <= line <= e and (best is None or (e - s) < best[0]):
            best = (e - s, nid)
    return best[1] if best else file_node_id


def enrich(repo: Path, res: AdaptResult) -> AdaptResult:
    """Add cross-module Python `calls` edges to `res`. No-op (same object) for non-Python
    node sets or when nothing new resolves; never adds nodes, never alters composite ids."""
    pyfiles = sorted({n["source_file"] for n in res.nodes
                      if (n.get("source_file") or "").endswith(".py")})
    if not pyfiles:
        return res
    pyset = set(pyfiles)
    defs: dict[tuple, str] = {}
    file_node: dict[str, str] = {}
    spans: dict[str, list] = {}
    for n in sorted(res.nodes, key=lambda n: n["id"]):
        md = n.get("metadata", {})
        sf, kind = n.get("source_file"), md.get("cg_kind")
        if sf not in pyset:
            continue
        if kind == "file":
            file_node.setdefault(sf, n["id"])
            continue
        # top-level definitions only (qualified_name == bare name): the alias tables hand us
        # bare names, and matching a nested def by label would mis-wire shadowed names
        if kind in _TARGET_KINDS and md.get("qualified_name") == n.get("label"):
            defs.setdefault((sf, n["label"]), n["id"])
        if kind in _SCOPE_KINDS and md.get("start_line") and md.get("end_line"):
            spans.setdefault(sf, []).append((md["start_line"], md["end_line"], n["id"]))
    for v in spans.values():
        v.sort()
    seen = {(e["source"], e["target"], e["relation"]) for e in res.edges}
    added: list[dict] = []
    for f in pyfiles:
        try:
            tree = ast.parse((repo / f).read_text(errors="replace"))
        except (OSError, SyntaxError):
            continue
        vis = _CallVisitor(f, pyset, defs)
        vis.visit(tree)
        for line, tf, tn in vis.calls:
            tid = defs.get((tf, tn))
            sid = _caller_of(line, spans.get(f, []), file_node.get(f))
            if not tid or not sid or sid == tid:
                continue
            key = (sid, tid, "calls")
            if key in seen:
                continue
            seen.add(key)
            added.append({"source": sid, "target": tid, "relation": "calls",
                          "context": "pyast", "confidence": "INFERRED", "weight": 1.0,
                          "source_file": f, "source_location": f"L{line}"})
    if not added:
        return res
    return AdaptResult(res.nodes, res.edges + added, res.cg_to_composite,
                       {**res.stats, "pyast_call_edges": len(added)})
