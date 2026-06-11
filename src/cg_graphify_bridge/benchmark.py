"""Phase 2 (2c) — `benchmark`: rigorous context/token-reduction of graph-guided retrieval vs a
naive full-file-read baseline, reported PER QUERY CLASS (pinpoint vs global).

Uses a real tokenizer (tiktoken cl100k) when available, else a clearly-labeled chars/4 estimate —
never the crude words×1.3 the research warns against. Offline; reads the committed graph + local
source files only. Honest: every number is paired with the tokenizer + baseline it used.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import driver


def _load_tiktoken():
    try:
        import tiktoken
        return tiktoken
    except Exception:
        return None


def _tokenizer():
    """(count_fn, label). Real BPE if tiktoken is installed; else a labeled chars/4 estimate."""
    tk = _load_tiktoken()
    if tk is not None:
        try:
            enc = tk.get_encoding("cl100k_base")
            return (lambda s: len(enc.encode(s)), "tiktoken/cl100k_base (exact)")
        except Exception:
            pass
    return (lambda s: max(1, len(s) // 4), "chars/4 estimate (install tiktoken for exact counts)")


def _identity(node: dict) -> str:
    """The graph-context line an agent reads for a node (NO source body)."""
    md = node.get("metadata", {})
    return (f"{node.get('label', '')} {node.get('source_file', '')}:{node.get('source_location', '')} "
            f"{md.get('cg_kind', '')} {md.get('signature') or ''}").strip()


def benchmark(out: Path, repo: Path, *, max_pinpoint: int = 10, max_global: int = 5) -> dict:
    structural = driver.read_layer(out, "structural")
    if structural is None:
        raise SystemExit(f"no structural.json in {out} — build the graph first (or pull it)")
    tok, tokname = _tokenizer()
    meta = {n["id"]: n for n in structural.get("nodes", [])}
    adj = defaultdict(set)
    for e in structural.get("edges", []):
        if e.get("relation") == "contains":
            continue
        adj[e["source"]].add(e["target"])
        adj[e["target"]].add(e["source"])
    fcache: dict[str, int] = {}

    def file_tokens(rel: str) -> int:
        if rel not in fcache:
            try:
                fcache[rel] = tok((repo / rel).read_text(errors="ignore"))
            except OSError:
                fcache[rel] = 0
        return fcache[rel]

    def files_of(ids) -> set:
        return {meta[i]["source_file"] for i in ids
                if i in meta and meta[i].get("source_file")}

    def row(label, ids):
        ids = list(ids)
        graph_t = tok("\n".join(_identity(meta[i]) for i in ids if i in meta))
        base_t = sum(file_tokens(f) for f in files_of(ids)) or 1
        return {"query": label, "graph_tokens": graph_t, "baseline_tokens": base_t,
                "reduction": round(1 - graph_t / base_t, 4)}

    # Pinpoint: "what is / what touches <hub>" — the node + its 1-hop neighborhood.
    pinpoint = [row(meta.get(g["id"], {}).get("label", g["id"]),
                    [g["id"], *sorted(adj[g["id"]])])
                for g in structural.get("god_nodes", [])[:max_pinpoint]]
    # Global: "explain this subsystem" — a whole community.
    comms = sorted(structural.get("communities", {}).items(),
                   key=lambda kv: (-len(kv[1]), kv[0]))[:max_global]
    glob = [row(f"community {cid}", members) for cid, members in comms]

    def mean(rows):
        return round(sum(r["reduction"] for r in rows) / len(rows), 4) if rows else None

    return {
        "out_dir": str(out), "tokenizer": tokname,
        "baseline": "naive full-file read of the source files a query's nodes live in",
        "pinpoint": {"mean_reduction": mean(pinpoint), "questions": pinpoint},
        "global": {"mean_reduction": mean(glob), "questions": glob},
        "note": ("graph-guided context = node identity lines (label/file/kind/signature, no source "
                 "body) for the node + neighborhood; baseline = reading the whole files. Reported "
                 "per query class — graphs win most on global/multi-hop, least on single-fact lookups."),
    }


def render_report(r: dict) -> str:
    L = ["# Graph Token-Reduction Benchmark", "",
         f"_Tokenizer: {r['tokenizer']}. Baseline: {r['baseline']}._", ""]
    for cls in ("pinpoint", "global"):
        b = r[cls]
        mr = b["mean_reduction"]
        L.append(f"## {cls.title()} — mean reduction {mr:.0%}" if mr is not None
                 else f"## {cls.title()} — (no sample)")
        for q in b["questions"][:10]:
            L.append(f"- `{q['query']}`: {q['reduction']:.0%} "
                     f"({q['graph_tokens']} vs {q['baseline_tokens']} tokens)")
        L.append("")
    L.append(f"_{r['note']}_")
    return "\n".join(L) + "\n"
