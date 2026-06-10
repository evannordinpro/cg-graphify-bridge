"""Engine identity + version stamp for the committed-artifact determinism contract (KD14, R6).

``graph.json`` is byte-deterministic only for a fixed clustering engine + pinned versions.
CI is the single Leiden builder (D4 — graspologic present); devs run Louvain on a base
install (graspologic absent). A repo whose committed graph was built by one engine must
never be silently rebuilt by the other: community ids would flip and churn the artifact.

``detect_engine()`` captures the running identity (stdlib only — ``importlib.metadata``/
``util`` do NOT import the heavy packages, so the bare-``python3`` freshness path stays
light). ``check_engine_compat()`` hard-errors (``SystemExit``) when the runtime engine
differs from the committed stamp; the first build (no stamp) establishes it without error.
"""
from __future__ import annotations

import importlib.metadata as _md
import importlib.util as _util

# Bump when the on-disk artifact schema changes (consumers gate on this — ODQ-E).
SCHEMA_VERSION = 1


def _installed(mod: str) -> bool:
    """True iff `mod` is importable — mirrors graphify.cluster's `from graspologic ... import`
    selection without actually importing (find_spec does not execute the module)."""
    try:
        return _util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def _ver(dist: str) -> str | None:
    try:
        return _md.version(dist)
    except _md.PackageNotFoundError:
        return None


def detect_engine() -> dict:
    """Runtime engine identity + pinned-dep versions for the manifest stamp."""
    leiden = _installed("graspologic")
    return {
        "engine": "leiden" if leiden else "louvain",
        "graphifyy": _ver("graphifyy"),
        "graspologic": _ver("graspologic"),
        "networkx": _ver("networkx"),
        "schema_version": SCHEMA_VERSION,
    }


def check_engine_compat(manifest: dict | None) -> None:
    """Raise ``SystemExit`` when the committed graph's engine differs from this runtime's.

    A missing manifest, a pre-KD14 manifest with no ``engine`` field, or a matching engine
    all pass — the first build of a fresh repo establishes the stamp without error."""
    if not manifest:
        return
    committed = manifest.get("engine")
    if not committed:
        return
    current = detect_engine()["engine"]
    if current == committed:
        return
    if committed == "leiden":
        hint = ("this repo's graph is Leiden-built (CI owns structural rebuilds). Install the "
                "extra — `pipx install 'cg-graphify-bridge[leiden]'` — or let CI rebuild "
                "structural; do not commit a Louvain rebuild over it.")
    else:
        hint = ("this repo's graph is Louvain-built. Uninstall graspologic (or use a base, "
                "non-`[leiden]` install) so the engine matches the committed artifact.")
    raise SystemExit(
        f"cg-graphify-bridge: engine mismatch — committed graph built with '{committed}', "
        f"this runtime would use '{current}'. {hint}")


def check_substrate_drift(manifest: dict | None, substrate: str, substrate_version: str | None) -> str | None:
    """Return an ADVISORY (non-fatal) when the committed graph's substrate/version differs from this
    runtime's (R6). Unlike the clustering-engine guard, a substrate version bump only *may* change
    extraction, so this warns rather than blocks — and the diff-gate catches any real churn. CI is
    the authoritative builder, so its pinned substrate version is canonical. Returns None when there
    is nothing to compare (no manifest, a pre-stamp manifest, or an exact match)."""
    if not manifest:
        return None
    committed = (manifest.get("substrate"), manifest.get("substrate_version"))
    if committed == (None, None):
        return None  # pre-substrate-stamp manifest — first stamp establishes it
    if committed == (substrate, substrate_version):
        return None
    return (f"substrate drift: committed graph built with {committed[0]} {committed[1]!r}, this "
            f"runtime uses {substrate} {substrate_version!r} — extraction may differ (structural.json "
            f"will diff if so). CI is the authoritative builder; align versions for reproducibility.")
