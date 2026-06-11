#!/usr/bin/env node
// Type-aware TS substrate for cg-graphify-bridge.
// Emits {nodes, edges} via the TypeScript compiler API (the mechanism scip-typescript
// uses) — cross-file resolution via the type checker (alias-following) is far denser
// than codegraph's tree-sitter. Output JSON -> consumed by ts_ingest.py.
// Usage: node extract.cjs <REPO_ROOT> <scope1,scope2,...>
const fs = require("fs");
const path = require("path");

const REPO = path.resolve(process.argv[2]);
const SCOPES = (process.argv[3] || "apps,services,packages,infra").split(",").filter(Boolean);
const ts = require(path.join(REPO, "node_modules/typescript"));

function readOpts() {
  for (const name of ["tsconfig.base.json", "tsconfig.json"]) {
    const p = path.join(REPO, name);
    if (fs.existsSync(p)) {
      const cfg = ts.readConfigFile(p, ts.sys.readFile).config;
      return ts.parseJsonConfigFileContent(cfg, ts.sys, REPO).options;
    }
  }
  return { allowJs: true, jsx: ts.JsxEmit.Preserve, target: ts.ScriptTarget.ESNext };
}

const files = [];
function walk(d) {
  let ents; try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
  // KD3: sort entries so the file-walk order is OS/filesystem-independent (readdirSync
  // returns inode order) -> deterministic node ordering across machines.
  ents.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  for (const e of ents) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) { if (!["node_modules", "dist", "build", ".git", ".codegraph"].includes(e.name)) walk(p); }
    else if (/\.(ts|tsx)$/.test(e.name) && !e.name.endsWith(".d.ts")) files.push(p);
  }
}
for (const s of SCOPES) walk(path.join(REPO, s));

const program = ts.createProgram(files, readOpts());
const checker = program.getTypeChecker();
const rel = (f) => path.relative(REPO, f);
const inScope = (f) => !f.endsWith(".d.ts") && !f.includes("node_modules") &&
  SCOPES.some((s) => f.startsWith(path.join(REPO, s) + path.sep) || f === path.join(REPO, s));

const KIND = {
  [ts.SyntaxKind.FunctionDeclaration]: "function",
  [ts.SyntaxKind.MethodDeclaration]: "method",
  [ts.SyntaxKind.ClassDeclaration]: "class",
  [ts.SyntaxKind.InterfaceDeclaration]: "interface",
  [ts.SyntaxKind.EnumDeclaration]: "enum",
  [ts.SyntaxKind.TypeAliasDeclaration]: "type_alias",
  [ts.SyntaxKind.ModuleDeclaration]: "namespace",
  [ts.SyntaxKind.GetAccessor]: "method",
  [ts.SyntaxKind.SetAccessor]: "method",
};
const SCOPE_KINDS = new Set(["class", "interface", "namespace", "enum"]);

const nodes = [];
const byDecl = new Map();
const fileNode = new Map();
let nid = 0;
const edges = [];
const addEdge = (f, t, k) => { if (f != null && t != null && f !== t) edges.push({ source: f, target: t, kind: k }); };

const lineOf = (n) => n.getSourceFile().getLineAndCharacterOfPosition(n.getStart()).line + 1;
function sigOf(n) {
  try {
    if (ts.isFunctionLike(n)) {
      const s = checker.getSignatureFromDeclaration(n);
      if (s) return "(" + s.getParameters().map((p) => p.getName()).join(",") + ")";
    }
  } catch (e) { /* noop */ }
  return "";
}
// Martin-metric inputs (Phase2 FR0): abstractness + public-API surface. Interfaces are abstract
// by definition; classes/methods via the `abstract` modifier; export via the `export` modifier.
const modOf = (n) => { try { return ts.getCombinedModifierFlags(n); } catch (e) { return 0; } };
const isAbstractOf = (n, kind) => kind === "interface" || (modOf(n) & ts.ModifierFlags.Abstract) !== 0;
const isExportedOf = (n) => (modOf(n) & ts.ModifierFlags.Export) !== 0;
function emitFile(sf) {
  const r = rel(sf.fileName);
  if (fileNode.has(r)) return fileNode.get(r);
  const id = nid++;
  nodes.push({ id, kind: "file", name: path.basename(r), qualified_name: r, file_path: r, signature: "", line: 1, is_abstract: false, is_exported: false });
  fileNode.set(r, id);
  return id;
}

// pass 1: declarations
for (const sf of program.getSourceFiles()) {
  if (!inScope(sf.fileName)) continue;
  const fId = emitFile(sf);
  const stack = [];
  const visit = (node) => {
    let kind = KIND[node.kind];
    let name = node.name && ts.isIdentifier(node.name) ? node.name.text : null;
    if (ts.isVariableDeclaration(node) && node.name && ts.isIdentifier(node.name) && node.initializer &&
        (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))) {
      kind = "function"; name = node.name.text;
    }
    let myId = null;
    if (kind && name) {
      myId = nid++;
      const qn = stack.map((s) => s.name).concat(name).join(".");
      nodes.push({ id: myId, kind, name, qualified_name: rel(sf.fileName) + "::" + qn,
        file_path: rel(sf.fileName), signature: sigOf(node), line: lineOf(node),
        is_abstract: isAbstractOf(node, kind), is_exported: isExportedOf(node) });
      byDecl.set(node, myId);
      addEdge(stack.length ? stack[stack.length - 1].id : fId, myId, "contains");
    }
    const push = myId != null && SCOPE_KINDS.has(kind);
    if (push) stack.push({ id: myId, name });
    ts.forEachChild(node, visit);
    if (push) stack.pop();
  };
  ts.forEachChild(sf, visit);
}

// pass 2: references
function containerId(node) {
  let p = node.parent;
  while (p) { if (byDecl.has(p)) return byDecl.get(p); p = p.parent; }
  return fileNode.get(rel(node.getSourceFile().fileName));
}
function targetId(idNode) {
  let s = checker.getSymbolAtLocation(idNode);
  if (!s) return null;
  if (s.flags & ts.SymbolFlags.Alias) { try { s = checker.getAliasedSymbol(s); } catch (e) {} }
  for (const d of (s.declarations || [])) { if (byDecl.has(d)) return byDecl.get(d); }
  return null;
}
for (const sf of program.getSourceFiles()) {
  if (!inScope(sf.fileName)) continue;
  const visit = (node) => {
    if (ts.isHeritageClause(node)) {
      const k = node.token === ts.SyntaxKind.ExtendsKeyword ? "extends" : "implements";
      for (const t of node.types) addEdge(containerId(node), targetId(t.expression), k);
    } else if (ts.isIdentifier(node)) {
      const isDeclName = node.parent && node.parent.name === node && byDecl.has(node.parent);
      if (!isDeclName) {
        const tid = targetId(node);
        if (tid != null) {
          const isCall = node.parent && ts.isCallExpression(node.parent) && node.parent.expression === node;
          addEdge(containerId(node), tid, isCall ? "calls" : "references");
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  ts.forEachChild(sf, visit);
}

const xfile = edges.filter((e) => nodes[e.source] && nodes[e.target] && nodes[e.source].file_path !== nodes[e.target].file_path).length;
console.log(JSON.stringify({ nodes, edges, stats: { files: fileNode.size, nodes: nodes.length, edges: edges.length, crossFileEdges: xfile } }));
