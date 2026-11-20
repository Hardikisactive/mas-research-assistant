"""conftest.py — shared pytest fixtures."""
import sys
from pathlib import Path
import pytest

# Make sure project root is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture
def tmp_blackboard(tmp_path):
    """Return a Blackboard backed by a temp file DB."""
    from app.state.blackboard import Blackboard
    return Blackboard(str(tmp_path / "test_bb.db"))


@pytest.fixture
def memory_blackboard():
    """Return an in-memory Blackboard (fastest for unit tests)."""
    from app.state.blackboard import Blackboard
    return Blackboard(":memory:")

