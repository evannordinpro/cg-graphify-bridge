import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SAMPLE = ROOT / "sample"


def _resolve_codegraph_bin() -> str | None:
    """codegraph CLI: $CODEGRAPH_BIN, else whatever's on PATH (npm i -g @colbymchenry/codegraph)."""
    env = os.environ.get("CODEGRAPH_BIN")
    if env and Path(env).exists():
        return env
    return shutil.which("codegraph")


CG_BIN = _resolve_codegraph_bin()
requires_codegraph = pytest.mark.skipif(
    CG_BIN is None,
    reason="codegraph CLI not found (set CODEGRAPH_BIN or `npm i -g @colbymchenry/codegraph`)",
)


def index_repo(repo: Path) -> Path:
    """git-init (if needed) + codegraph index a repo; return the DB path."""
    repo = Path(repo)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cgdir = repo / ".codegraph"
    if cgdir.exists():
        shutil.rmtree(cgdir)
    base = ["node", CG_BIN] if CG_BIN.endswith(".js") else [CG_BIN]
    subprocess.run(base + ["init", "-i"], cwd=str(repo), check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    db = cgdir / "codegraph.db"
    assert db.exists(), f"codegraph DB not created in {repo}"
    return db


@pytest.fixture(scope="session")
def cg_db(tmp_path_factory):
    """Index a throwaway COPY of sample/ so the committed tree stays clean."""
    if CG_BIN is None:
        pytest.skip("codegraph CLI unavailable")
    dest = tmp_path_factory.mktemp("sample_idx") / "sample"
    shutil.copytree(SAMPLE, dest)
    return index_repo(dest)
