"""共用 fixture / 路徑常數。

供所有 tests/test_*.py 自動 import（pytest 自動發現 conftest.py）。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"

# 確保 tests 能 import scripts/, utils/, aispeech/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# 路徑類 fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def project_root() -> Path:
    """專案根目錄絕對路徑。"""
    return PROJECT_ROOT


@pytest.fixture
def migrations_dir() -> Path:
    """migrations/ 絕對路徑。"""
    return MIGRATIONS_DIR


# ─────────────────────────────────────────────────────────────────────────────
# DB 類 fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """每測試一個全新的 .db 檔（pytest tmp_path 自動清理）。"""
    return tmp_path / "test.db"


@pytest.fixture
def in_memory_conn() -> sqlite3.Connection:
    """In-memory SQLite connection；測完自動關。適合不需要持久化的測試。"""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


@pytest.fixture
def baseline_db(tmp_db_path: Path):
    """套用過 0001 baseline 的乾淨 SQLite DB 檔路徑。

    用法：def test_xxx(baseline_db): ...
    """
    sql = (MIGRATIONS_DIR / "0001_baseline_schema.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(tmp_db_path)
    conn.executescript(sql)
    conn.commit()
    conn.close()
    return tmp_db_path
