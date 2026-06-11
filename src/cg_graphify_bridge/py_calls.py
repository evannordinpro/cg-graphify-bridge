"""Supplemental Python cross-module edges (stdlib `ast`) over the adapted substrate.

codegraph 0.9.9 resolves same-file Python calls only: a cross-module call
(`driver.read_layer(...)` after `from . import driver`, or `f()` after `from .x import f`)
yields no `calls` edge, and VALUE references — a function passed to `set_defaults(func=...)`,
a module constant read as a bare identifier, `freshness.SCAN_EXT` — yield no edge at all,
so such symbols sit at zero in-degree (dead-code false positives) and centrality/impact
understate reality. This pass parses the indexed `.py` sources, resolves import aliases
(module-level and function-local, absolute and relative), and emits the missing edges:

- `calls` — bare-name calls through imported-symbol aliases (same-file calls are the
  substrate's job and already edged) and attribute calls through imported-module aliases;
- `references` — value-position loads of functions/classes/constants (imported, module-
  attribute, or same-file module-level), and `from x import name` itself (an import IS a
  reference); a bare name shadowed by a local binding in any enclosing function scope is
  never resolved (no guessing);
- `is_exported` stamping — names listed in a module-level `__all__` are the module's declared
  public API; dead-code's entry-point filter excludes exported symbols, so a library surface
  with no in-repo callers stops looking dead.

Strictly supplemental and conservative: a target must resolve to exactly ONE indexed
top-level definition or it is skipped (ambiguous absolute imports never guess); `self.x()`
needs type info we don't have and is out of scope. Deterministic: files walked sorted, AST
visited in lexical order, stdlib only; emitted edges are deduped against the substrate's and
stamped context="pyast" / confidence="INFERRED" so their provenance stays visible.
"""
from __future__ import annotations

import ast
from pathlib import Path

from .adapter import AdaptResult

# kinds a resolved CALL may target: functions, and classes (instantiation is a call)
_CALL_KINDS = {"function", "class"}
# kinds a VALUE reference may target: callables plus module-level data
_REF_KINDS = {"function", "class", "constant", "variable"}
# kinds that can own a call/reference site (innermost enclosing span wins; file node fallback)
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


def _local_names(fn) -> set:
    """Names bound inside a function scope (params + assignment targets, nested included —
    over-collecting only makes the shadow check more conservative). `global`/`nonlocal`
    declarations un-shadow: those names deliberately refer to an outer binding."""
    bound, unshadowed = set(), set()
    for a in ast.walk(fn):
        if isinstance(a, ast.Name) and isinstance(a.ctx, (ast.Store, ast.Del)):
            bound.add(a.id)
        elif isinstance(a, ast.arg):
            bound.add(a.arg)
        elif isinstance(a, (ast.Global, ast.Nonlocal)):
            unshadowed.update(a.names)
    return bound - unshadowed


def _all_names(tree) -> list[str]:
    """String entries of a module-level `__all__ = [...]` / tuple, lexically last wins."""
    names: list[str] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in stmt.targets):
            if isinstance(stmt.value, (ast.List, ast.Tuple)):
                names = [e.value for e in stmt.value.elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return names


class _RefVisitor(ast.NodeVisitor):
    """One pass per file, lexical order: import statements populate the alias tables as they
    appear (so a function-local alias is visible to the uses below it, approximating scope);
    Call nodes resolve to `calls`, value-position Name/Attribute loads to `references`."""

    def __init__(self, cur_file: str, pyfiles: set, defs: dict):
        self.cur_file, self.pyfiles, self.defs = cur_file, pyfiles, defs
        self.mod_alias: dict[str, str] = {}      # local (possibly dotted) name -> module file
        self.sym_alias: dict[str, tuple] = {}    # local name -> (module file, original name)
        self.calls: list[tuple] = []             # (lineno, target_file, target_name)
        self.refs: list[tuple] = []              # (lineno, target_file, target_name)
        self._scopes: list[set] = []             # local-binding sets, innermost last
        self._consumed: set[int] = set()         # node ids handled as call funcs

    # ----- imports -----

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
                self.refs.append((node.lineno, base, a.name))   # an import IS a reference

    # ----- scopes (shadow tracking for bare-name value refs) -----

    def _scoped(self, node):
        self._scopes.append(_local_names(node))
        self.generic_visit(node)
        self._scopes.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _scoped

    def _shadowed(self, name: str) -> bool:
        return any(name in s for s in self._scopes)

    # ----- calls and value references -----

    def _root_ref(self, dotted: str, lineno: int):
        """`CONST.get(...)` / `OBJ.attr` — calling/reading an attribute OF a value is using the
        value: resolve the chain root as a value reference when it isn't a module alias."""
        root = dotted.split(".", 1)[0]
        if self._shadowed(root):
            return
        tgt = self.sym_alias.get(root)
        if tgt:
            self.refs.append((lineno, tgt[0], tgt[1]))
        elif (self.cur_file, root) in self.defs:
            self.refs.append((lineno, self.cur_file, root))

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Name):
            self._consumed.add(id(f))
            tgt = self.sym_alias.get(f.id)
            if tgt:
                self.calls.append((node.lineno, tgt[0], tgt[1]))
        elif isinstance(f, ast.Attribute):
            dotted = _dotted(f)
            if dotted:
                self._consumed.add(id(f))
                prefix, _, name = dotted.rpartition(".")
                mf = self.mod_alias.get(prefix)
                if mf:
                    self.calls.append((node.lineno, mf, name))
                else:
                    self._root_ref(dotted, node.lineno)
        self.generic_visit(node)

    def visit_Name(self, node):
        if id(node) in self._consumed or not isinstance(node.ctx, ast.Load):
            return
        if self._shadowed(node.id):
            return
        tgt = self.sym_alias.get(node.id)
        if tgt:
            self.refs.append((node.lineno, tgt[0], tgt[1]))
        elif (self.cur_file, node.id) in self.defs:   # same-file module-level value read
            self.refs.append((node.lineno, self.cur_file, node.id))

    def visit_Attribute(self, node):
        if id(node) in self._consumed:
            return
        dotted = _dotted(node)
        if dotted is None:                       # not a pure chain — descend (e.g. f().attr)
            self.generic_visit(node)
            return
        if isinstance(node.ctx, ast.Load):
            prefix, _, name = dotted.rpartition(".")
            mf = self.mod_alias.get(prefix)
            if mf:
                self.refs.append((node.lineno, mf, name))
            else:
                self._root_ref(dotted, node.lineno)
        # a pure chain has no other children worth visiting (root Name is part of the chain)


def _caller_of(line: int, spans: list, file_node_id: str | None) -> str | None:
    """Innermost def/class whose [start_line, end_line] contains the line; file node fallback."""
    best = None
    for s, e, nid in spans:
        if s <= line <= e and (best is None or (e - s) < best[0]):
            best = (e - s, nid)
    return best[1] if best else file_node_id


def enrich(repo: Path, res: AdaptResult) -> AdaptResult:
    """Add cross-module/value-reference edges + `__all__` export stamps to `res`. No-op (same
    object) for non-Python node sets; never adds nodes, never alters composite ids."""
    pyfiles = sorted({n["source_file"] for n in res.nodes
                      if (n.get("source_file") or "").endswith(".py")})
    if not pyfiles:
        return res
    pyset = set(pyfiles)
    defs: dict[tuple, tuple] = {}        # (file, name) -> (node id, kind)
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
        if kind in _REF_KINDS and md.get("qualified_name") == n.get("label"):
            defs.setdefault((sf, n["label"]), (n["id"], kind))
        if kind in _SCOPE_KINDS and md.get("start_line") and md.get("end_line"):
            spans.setdefault(sf, []).append((md["start_line"], md["end_line"], n["id"]))
    for v in spans.values():
        v.sort()
    node_by_id = {n["id"]: n for n in res.nodes}
    seen = {(e["source"], e["target"], e["relation"]) for e in res.edges}
    added: list[dict] = []
    exported = 0

    def _emit(sid, tid, relation, sf, line):
        nonlocal added
        if not sid or not tid or sid == tid:
            return
        key = (sid, tid, relation)
        if key in seen:
            return
        seen.add(key)
        added.append({"source": sid, "target": tid, "relation": relation,
                      "context": "pyast", "confidence": "INFERRED", "weight": 1.0,
                      "source_file": sf, "source_location": f"L{line}"})

    for f in pyfiles:
        try:
            tree = ast.parse((repo / f).read_text(errors="replace"))
        except (OSError, SyntaxError):
            continue
        for name in _all_names(tree):            # declared public API -> entry point
            hit = defs.get((f, name))
            if hit:
                md = node_by_id[hit[0]].setdefault("metadata", {})
                if not md.get("is_exported"):
                    md["is_exported"] = True
                    exported += 1
        vis = _RefVisitor(f, pyset, defs)
        vis.visit(tree)
        for line, tf, tn in vis.calls:
            hit = defs.get((tf, tn))
            if hit and hit[1] in _CALL_KINDS:
                _emit(_caller_of(line, spans.get(f, []), file_node.get(f)), hit[0],
                      "calls", f, line)
        for line, tf, tn in vis.refs:
            hit = defs.get((tf, tn))
            if hit:
                _emit(_caller_of(line, spans.get(f, []), file_node.get(f)), hit[0],
                      "references", f, line)
    if not added and not exported:
        return res
    n_calls = sum(1 for e in added if e["relation"] == "calls")
    return AdaptResult(res.nodes, res.edges + added, res.cg_to_composite,
                       {**res.stats, "pyast_call_edges": n_calls,
                        "pyast_ref_edges": len(added) - n_calls,
                        "pyast_exports_stamped": exported})
