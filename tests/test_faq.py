"""Phase 6 — PROJECT_FAQ: quantitative feature map, narrative prep/merge, staleness, render."""
import json

from cg_graphify_bridge import faq, freshness


def _n(nid, label, file, kind="function", exported=False):
    return {"id": nid, "label": label, "file_type": "code", "source_file": file,
            "source_location": "L1",
            "metadata": {"cg_kind": kind, "qualified_name": label, "start_line": 1,
                         "end_line": 2, "is_exported": exported}}


def _e(s, t, rel="calls"):
    return {"source": s, "target": t, "relation": rel, "context": rel,
            "confidence": "EXTRACTED", "weight": 1.0, "source_file": "", "source_location": ""}


def _structural(tmp_path):
    for f, body in (("src/a.py", "def A(): pass\n"), ("src/b.py", "def B(): pass\n"),
                    ("src/c.py", "def C(): pass\n")):
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return {"schema_version": 1, "layer": "structural",
            "nodes": [_n("cg:a", "A", "src/a.py", exported=True),
                      _n("cg:b", "B", "src/b.py"),
                      _n("cg:c", "C", "src/c.py")],
            "edges": [_e("cg:b", "cg:a"), _e("cg:a", "cg:c")],
            "communities": {"c0": ["cg:a", "cg:b"], "c1": ["cg:c"]},
            "god_nodes": [], "surprising": [], "stats": {}}


def test_feature_map_facts(tmp_path):
    feats = faq.feature_map(_structural(tmp_path))
    f0 = next(f for f in feats if f["community"] == "c0")
    f1 = next(f for f in feats if f["community"] == "c1")
    assert f0["anchor"] == "cg:a" and f0["size"] == 2
    assert f0["inputs"] == ["A"]                      # exported member = public surface
    assert f0["outputs"] == ["C"]                     # cross-community dependency
    assert f0["downstream"] == [("c1", 1)]            # c0 depends on c1
    assert f1["upstream"] == [("c0", 1)]              # mirrored


def test_prep_merge_roundtrip_and_baseline(tmp_path):
    st = _structural(tmp_path)
    out = tmp_path / "graphify-out"
    out.mkdir()
    info = faq.prep_faq(out, tmp_path, st)
    assert info["feature_tasks"] == 2 and info["project_task"]
    pdir = out / ".cache" / "faq" / "payloads"
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps(
        {"project": {"what": "A test project.", "purpose": "Testing.", "ignored_key": "x"}}))
    (pdir / "features.json").write_text(json.dumps({"features": [
        {"anchor": "cg:a", "name": "Core", "concept": "The core.", "functionality": "Does core."},
        {"anchor": "cg:invented", "name": "Ghost"}]}))
    res = faq.merge_faq(out, tmp_path, st)
    assert res["merged"] == 1 and res["unknown_anchors"] == ["cg:invented"]
    data = json.loads((out / "faq.json").read_text())
    assert data["project"] == {"what": "A test project.", "purpose": "Testing."}
    assert data["features"][0]["name"] == "Core"
    assert not (out / ".cache" / "faq").exists()      # scratch consumed
    base = freshness.read_manifest(out)["faq"]["features"]
    assert set(base) == {"cg:a", "cg:c"} and base["cg:a"]["files"] == ["src/a.py", "src/b.py"]


def test_per_feature_staleness_light_path(tmp_path):
    st = _structural(tmp_path)
    out = tmp_path / "graphify-out"
    out.mkdir()
    faq.write_faq({"project": {"what": "x"}, "features": [
        {"anchor": "cg:a", "name": "Core"}, {"anchor": "cg:c", "name": "Leaf"}]}, out)
    faq.merge_faq(out, tmp_path, st)                  # stamps the baseline, keeps narratives
    assert freshness.faq_status(out, tmp_path)["state"] == "fresh"
    (tmp_path / "src/c.py").write_text("def C():\n    return 1\n")   # edit feature c1 only
    stt = freshness.faq_status(out, tmp_path)
    assert stt["state"] == "stale" and stt["stale_features"] == ["cg:c"]
    # graph-path state agrees, and only c1 needs work
    state = faq.faq_state(out, tmp_path, st)
    assert [f["anchor"] for f in state["stale"]] == ["cg:c"]


def test_unadopted_repo_never_gates(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    assert freshness.faq_status(out, tmp_path)["state"] == "unbuilt"


def test_orphaned_narrative_dropped_and_reported(tmp_path):
    st = _structural(tmp_path)
    out = tmp_path / "graphify-out"
    out.mkdir()
    faq.write_faq({"project": {}, "features": [
        {"anchor": "cg:gone", "name": "Old"}, {"anchor": "cg:a", "name": "Core"}]}, out)
    res = faq.merge_faq(out, tmp_path, st)
    assert res["dropped_orphans"] == ["cg:gone"]
    kept = {f["anchor"] for f in json.loads((out / "faq.json").read_text())["features"]}
    assert kept == {"cg:a"}


def test_render_deterministic_with_pending_placeholders(tmp_path):
    st = _structural(tmp_path)
    out = tmp_path / "graphify-out"
    out.mkdir()
    faq.write_faq({"project": {"what": "A bridge."},
                   "features": [{"anchor": "cg:a", "name": "Core", "concept": "The core."}]}, out)
    md1 = faq.render_faq(out, tmp_path, st)
    md2 = faq.render_faq(out, tmp_path, st)
    assert md1 == md2
    assert "# 📒 PROJECT_FAQ" in md1 and "**What.** A bridge." in md1
    assert "### Core — 2 components" in md1 and "The core." in md1
    assert "_(narrative pending)_" in md1             # c1 has no narrative yet
    assert "**Public surface:** `A`" in md1 and "**Depends on:**" in md1
