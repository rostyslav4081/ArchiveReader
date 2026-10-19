"""Shared temporary storage for tests that run from a clean checkout."""
from pathlib import Path
import tempfile


def workspace_tempdir():
    """Create the ignored parent before allocating an isolated test directory."""
    output = Path(__file__).resolve().parents[1] / 'test-output'
    output.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=output)
