"""Phase 2 (R6, KD14) — engine stamp + mismatch hard-error.

graph.json is byte-deterministic only for a fixed clustering engine; a repo built by Leiden
(CI) must not be silently rebuilt by Louvain (dev) or vice-versa. The stamp lives in the
manifest; the guard raises SystemExit on drift; the first build establishes the stamp clean.
Tests are environment-independent (the mismatch case derives the *opposite* of whatever
engine is running; the default-engine case monkeypatches the importability probe).
"""
import json

import pytest

from cg_graphify_bridge import engine, freshness


def test_engine_stamp_written(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    (tmp_path / "src").mkdir()
    m = freshness.write_manifest(out, tmp_path, ["src"], engine_stamp=engine.detect_engine())
    on_disk = json.loads((out / freshness.MANIFEST).read_text())
    for k in ("engine", "graphifyy", "networkx", "schema_version"):
        assert k in on_disk and k in m
    assert on_disk["engine"] in ("leiden", "louvain")
    assert on_disk["schema_version"] == engine.SCHEMA_VERSION
    # backward-compat: the freshness fields are still present so staleness keeps working
    assert "hash" in on_disk and "scopes" in on_disk


def test_engine_mismatch_raises_systemexit():
    current = engine.detect_engine()["engine"]
    other = "leiden" if current == "louvain" else "louvain"
    with pytest.raises(SystemExit) as ei:
        engine.check_engine_compat({"engine": other})
    assert "engine mismatch" in str(ei.value)


def test_first_build_writes_stamp_no_error():
    # no manifest (fresh repo), a pre-KD14 manifest with no engine field, and a same-engine
    # rebuild all pass without raising — only a true cross-engine drift is fatal.
    engine.check_engine_compat(None)
    engine.check_engine_compat({"hash": "abc", "files": 3, "scopes": ["src"]})
    engine.check_engine_compat({"engine": engine.detect_engine()["engine"]})


def test_louvain_default_when_no_graspologic(monkeypatch):
    monkeypatch.setattr(engine, "_installed", lambda mod: False)
    assert engine.detect_engine()["engine"] == "louvain"   # base install → Louvain
    monkeypatch.setattr(engine, "_installed", lambda mod: True)
    assert engine.detect_engine()["engine"] == "leiden"    # graspologic present → Leiden
