"""Phase 5 (R2, KD13) — the shipped GitHub Actions workflow builds structural on the PR's own
branch (build-on-PR-branch), and `init` installs it.

Asserted (text-based; pyyaml isn't a runtime dep, so a real parse is guarded to CI):
- triggers on pull_request for CODE paths only (graphify-out absent -> a structural-only push
  never re-runs the workflow = loop-safe);
- permissions: contents: write (to push onto the PR branch);
- the structural commit is DIFF-GATED and pushed to the PR's head ref — and there is NO
  separate-PR / auto-merge machinery (the simpler model we chose);
- `init` installs .github/workflows/graph-build.yml idempotently.
"""
import importlib.util
from importlib.resources import files
from types import SimpleNamespace

import pytest

from cg_graphify_bridge import cli, driver
from cg_graphify_bridge.adapter import AdaptResult


def _template() -> str:
    return files("cg_graphify_bridge.templates").joinpath("graph-build.yml").read_text()


def _noncomment(text: str) -> str:
    # drop comment lines so the explanatory header (which mentions graphify-out / auto-merge to
    # explain what we DON'T do) doesn't pollute config assertions
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _on_block(text: str) -> str:
    return _noncomment(text.split("permissions:", 1)[0])   # the `on:` triggers, sans comments


def test_workflow_template_packaged():
    txt = _template()
    assert txt.strip() and "name: graph-build" in txt


def test_workflow_triggers_pull_request_on_code_paths():
    on = _on_block(_template())
    assert "pull_request:" in on
    for p in ("apps/**", "services/**", "packages/**", "infra/**"):
        assert p in on


def test_workflow_has_contents_write():
    txt = _template()
    assert "permissions:" in txt and "contents: write" in txt


def test_workflow_pushes_to_head_only_on_diff():
    txt = _template()
    assert "git diff --quiet" in txt                 # diff-gated
    assert "git push" in txt and "github.head_ref" in txt   # push to the PR's head branch
    # the simpler model: NO separate-PR / auto-merge machinery (check the config, not comments)
    body = _noncomment(txt).lower()
    assert "create-pull-request" not in body and "peter-evans" not in body
    assert "automerge" not in body and "auto-merge" not in body


def test_workflow_loop_safe_graphify_out_not_a_trigger():
    # a structural-only push touches graphify-out/** which is NOT a trigger path -> no re-run
    assert "graphify-out" not in _on_block(_template())


def test_workflow_has_concurrency_guard():
    assert "concurrency:" in _template()


def test_init_installs_ci_workflow(tmp_path, monkeypatch):
    def _fake_build(repo, out_name, **kw):
        driver.write_structural({"adapt": AdaptResult([], [], {}, {}), "communities": {},
                                 "god_nodes": [], "surprising": []}, repo / out_name)
        return {"out_dir": str(repo / out_name)}
    monkeypatch.setattr(cli, "build_repo", _fake_build)
    cli._init(SimpleNamespace(repo=str(tmp_path), out="graphify-out", substrate="auto", scopes=None))
    wf = tmp_path / ".github" / "workflows" / "graph-build.yml"
    assert wf.exists() and "graph-build" in wf.read_text()


def test_write_ci_workflow_idempotent(tmp_path):
    first = cli.write_ci_workflow(tmp_path)
    assert first["action"] == "installed"
    (tmp_path / ".github" / "workflows" / "graph-build.yml").write_text("# customized\n")
    second = cli.write_ci_workflow(tmp_path)
    assert "exists" in second["action"]                       # never clobbers
    assert (tmp_path / ".github" / "workflows" / "graph-build.yml").read_text() == "# customized\n"


@pytest.mark.skipif(importlib.util.find_spec("yaml") is None,
                    reason="pyyaml not installed offline — text assertions cover structure; CI parses for real")
def test_workflow_is_valid_yaml():
    import yaml
    d = yaml.safe_load(_template())          # raises on malformed YAML
    assert d["name"] == "graph-build"
    assert d["permissions"]["contents"] == "write"
    assert "structural" in d["jobs"]
