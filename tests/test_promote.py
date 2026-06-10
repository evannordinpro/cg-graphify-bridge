"""Phase 4 promote acceptance — trace R8/D9.

Environment-coupled: asserts the post-promote state of the live machine. Skips
cleanly on a fresh checkout where no promote was performed.
"""
import hashlib
import os
from pathlib import Path

import pytest

LATEST = Path.home() / ".claude/state/cg-bridge-promote-backup/LATEST"
pytestmark = pytest.mark.skipif(
    not LATEST.exists(), reason="no graphify promote performed on this machine"
)


def _backup_dir() -> Path:
    return Path(LATEST.read_text().strip())


def test_global_skill_backup_exists():
    bk = _backup_dir()
    assert (bk / "skills-graphify" / "SKILL.md").exists(), "global skill not backed up"
    assert (bk / "claude.json").exists(), "claude.json not backed up"
    assert (bk / "appdev-graphify.tar.gz").exists(), "AppDev/graphify tar not preserved"


def test_global_skill_reinstalled_with_overlay():
    base = Path.home() / ".claude/skills/graphify"
    assert (base / "SKILL.md").exists() and (base / ".graphify_version").exists()
    assert (base / ".graphify_version").read_text().strip() == "0.8.36"
    assert "Overlay mode: codegraph is the code substrate" in (base / "SKILL.md").read_text(), \
        "overlay patch not merged into the global skill"


def _cortex_hash() -> str:
    """Deterministic, order-independent content hash (sorted rel paths + bytes).
    Replaces a brittle `find|shasum` pipeline that varied across shells (/bin/sh
    vs zsh produced different file orderings -> different aggregate hash)."""
    root = Path.home() / "AppDev/Cortex/daemon/graphify"
    h = hashlib.sha256()
    for rel in sorted(os.path.relpath(os.path.join(d, f), root)
                      for d, _, fs in os.walk(root) if "/.git" not in d for f in fs):
        h.update(rel.encode())
        h.update((root / rel).read_bytes())
    return h.hexdigest()


def test_cortex_copy_checksum_unchanged():
    baseline = (_backup_dir() / "cortex-baseline.sha").read_text().strip()
    assert _cortex_hash() == baseline, "Cortex copy MUST stay byte-identical (preserve, R8)"
