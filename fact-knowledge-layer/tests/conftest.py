"""Test configuration and shared fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure src/ is on the path
_SRC = str(Path(__file__).parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Absolute paths for test artifacts
_PROJECT_ROOT = Path(__file__).parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_DATA_DIR.mkdir(exist_ok=True)
(_DATA_DIR / "test_uploads").mkdir(exist_ok=True)
(_DATA_DIR / "test_renders").mkdir(exist_ok=True)

# Force fake LLM for all tests — must be set before any fkl import
os.environ["LLM_PROVIDER"] = "fake"
os.environ["DATABASE_URL"] = f"sqlite:///{_DATA_DIR / 'test_fkl.sqlite3'}"
os.environ["UPLOAD_DIR"] = str(_DATA_DIR / "test_uploads")
os.environ["RENDER_DIR"] = str(_DATA_DIR / "test_renders")
os.environ.setdefault("GEMINI_API_KEY", "fake-key-for-tests")


@pytest.fixture(autouse=True)
def reset_settings():
    """Reset settings singleton between tests."""
    import fkl.config as cfg
    cfg._settings = None
    yield
    cfg._settings = None
