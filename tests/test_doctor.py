"""Phase 4 P4c (R9, KD8) — `doctor` reports runtime-dep readiness with actionable hints,
not stack traces. node + codegraph are global; target typescript is repo-local.
"""
from cg_graphify_bridge import cli


def test_doctor_json_shape():
    rep = cli.doctor_report(None)
    assert "checks" in rep and "ok" in rep
    deps = {c["dep"] for c in rep["checks"]}
    assert {"node", "codegraph"} <= deps
    for c in rep["checks"]:
        assert set(c) >= {"dep", "ok", "detail", "hint"}
        assert isinstance(c["ok"], bool)


def test_doctor_reports_missing_node_hint(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)  # nothing on PATH
    monkeypatch.delenv("CODEGRAPH_BIN", raising=False)
    rep = cli.doctor_report(None)
    node = next(c for c in rep["checks"] if c["dep"] == "node")
    assert node["ok"] is False and node["hint"] and "Node" in node["hint"]
    assert rep["ok"] is False


def test_doctor_detects_target_typescript(tmp_path):
    (tmp_path / "node_modules" / "typescript").mkdir(parents=True)
    rep = cli.doctor_report(tmp_path)
    ts = next(c for c in rep["checks"] if c["dep"] == "target typescript")
    assert ts["ok"] is True and ts["hint"] is None


def test_doctor_missing_target_typescript_hints(tmp_path):
    rep = cli.doctor_report(tmp_path)   # no node_modules/typescript
    ts = next(c for c in rep["checks"] if c["dep"] == "target typescript")
    assert ts["ok"] is False and ts["hint"]
