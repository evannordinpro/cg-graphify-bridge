"""A test file — should be EXCLUDED from the analysis view (D14)."""
from pkg_a.auth import process


def test_process():
    assert process("tok")
