"""Phase 6 P6d (R7/R10, KD9) — the optional universal git pre-push gate.

It blocks a push when `cg-graphify-bridge check-semantic` fails (stale overlay) and documents the
`git push --no-verify` escape. Exercised as a shell harness: install into a tmp git repo, put a
fake `cg-graphify-bridge` on PATH (controls the exit code), run the hook, assert behavior.
"""
import os
import subprocess

from cg_graphify_bridge import cli


def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def _fake_cg(tmp_path, exit_code: int):
    binp = tmp_path / "bin"
    binp.mkdir(exist_ok=True)
    fake = binp / "cg-graphify-bridge"
    fake.write_text(f"#!/usr/bin/env sh\nexit {exit_code}\n")
    fake.chmod(0o755)
    return {**os.environ, "PATH": f"{binp}:{os.environ['PATH']}"}


def test_prepush_installed_and_documents_noverify(tmp_path):
    _git_repo(tmp_path)
    res = cli.install_prepush_hook(tmp_path, "graphify-out")
    assert res["action"] == "installed"
    hook = tmp_path / ".git" / "hooks" / "pre-push"
    txt = hook.read_text()
    assert "check-semantic" in txt and "--no-verify" in txt and cli._PREPUSH_MARK in txt


def test_prepush_blocks_on_stale(tmp_path):
    _git_repo(tmp_path)
    cli.install_prepush_hook(tmp_path, "graphify-out")
    hook = tmp_path / ".git" / "hooks" / "pre-push"
    r = subprocess.run(["sh", str(hook)], cwd=tmp_path, env=_fake_cg(tmp_path, 1),
                       input="", capture_output=True, text=True)
    assert r.returncode == 1 and "stale" in (r.stdout + r.stderr).lower()


def test_prepush_allows_when_fresh(tmp_path):
    _git_repo(tmp_path)
    cli.install_prepush_hook(tmp_path, "graphify-out")
    hook = tmp_path / ".git" / "hooks" / "pre-push"
    r = subprocess.run(["sh", str(hook)], cwd=tmp_path, env=_fake_cg(tmp_path, 0),
                       input="", capture_output=True, text=True)
    assert r.returncode == 0


def test_prepush_idempotent(tmp_path):
    _git_repo(tmp_path)
    cli.install_prepush_hook(tmp_path, "graphify-out")
    second = cli.install_prepush_hook(tmp_path, "graphify-out")
    assert second["action"] == "already present"
    assert (tmp_path / ".git" / "hooks" / "pre-push").read_text().count(cli._PREPUSH_MARK) == 1
