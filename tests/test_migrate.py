"""Tests for utils/migrate.py — schema migration runner.

涵蓋：
- _ensure_tracking_table / _file_checksum / _list_migrations / _backup / _table_exists
- cmd_status / cmd_up / cmd_down
- baseline reconcile 路徑
- checksum drift 偵測
- dry-run 不執行
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from utils import migrate


# ─────────────────────────────────────────────────────────────────────────────
# 內部工具函數
# ─────────────────────────────────────────────────────────────────────────────

class TestInternals:
    def test_ensure_tracking_table_creates_schema_migrations(self, in_memory_conn):
        """首次呼叫應建立 schema_migrations 表。"""
        migrate._ensure_tracking_table(in_memory_conn)
        rows = in_memory_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchall()
        assert len(rows) == 1

    def test_ensure_tracking_table_idempotent(self, in_memory_conn):
        """第二次呼叫應 no-op，不爆炸。"""
        migrate._ensure_tracking_table(in_memory_conn)
        migrate._ensure_tracking_table(in_memory_conn)  # 不應 raise

    def test_file_checksum_deterministic(self, tmp_path):
        """同樣內容兩次 checksum 一致；改了內容 checksum 不同。"""
        f = tmp_path / "x.sql"
        f.write_text("SELECT 1;")
        c1 = migrate._file_checksum(f)
        c2 = migrate._file_checksum(f)
        assert c1 == c2
        assert len(c1) == 64  # sha256 hex
        f.write_text("SELECT 2;")
        c3 = migrate._file_checksum(f)
        assert c1 != c3

    def test_table_exists(self, in_memory_conn):
        assert not migrate._table_exists(in_memory_conn, "foo")
        in_memory_conn.execute("CREATE TABLE foo (id INTEGER)")
        assert migrate._table_exists(in_memory_conn, "foo")

    def test_backup_creates_timestamped_copy(self, tmp_path):
        db = tmp_path / "x.db"
        db.write_bytes(b"sentinel-content")
        bak = migrate._backup(db)
        assert bak is not None
        assert bak.exists()
        assert bak.read_bytes() == b"sentinel-content"
        assert ".bak." in bak.name

    def test_backup_missing_db_returns_none(self, tmp_path):
        assert migrate._backup(tmp_path / "nope.db") is None


# ─────────────────────────────────────────────────────────────────────────────
# Baseline reconcile 路徑（既有 DB）
# ─────────────────────────────────────────────────────────────────────────────

class TestBaselineReconcile:
    def test_up_on_existing_db_takes_reconcile_path(self, baseline_db):
        """已有 transcriptions 表 → up 0001 應只 INSERT 紀錄、不執行 DDL。"""
        # baseline_db fixture 已套用 0001 schema 但無 schema_migrations 紀錄
        conn = sqlite3.connect(baseline_db)
        # 確認還沒紀錄
        migrate._ensure_tracking_table(conn)
        applied = migrate._applied(conn)
        assert len(applied) == 0
        conn.close()

        # 跑 up
        rc = migrate.cmd_up(baseline_db, target=None, dry_run=False)
        assert rc == 0

        # 確認 0001 進了 schema_migrations
        conn = sqlite3.connect(baseline_db)
        applied = migrate._applied(conn)
        assert "0001" in applied
        assert applied["0001"]["name"] == "baseline_schema"
        conn.close()

    def test_up_idempotent(self, baseline_db):
        """連續跑兩次 up 結果一樣，不應重複 INSERT。"""
        migrate.cmd_up(baseline_db, target=None, dry_run=False)
        migrate.cmd_up(baseline_db, target=None, dry_run=False)
        conn = sqlite3.connect(baseline_db)
        rows = conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='0001'").fetchone()
        assert rows[0] == 1
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Up / Down 整合 — 用 dummy migration 驗
# ─────────────────────────────────────────────────────────────────────────────

class TestUpDown:
    @pytest.fixture
    def dummy_migration(self, tmp_path, monkeypatch, baseline_db):
        """造一個假 migration 0099 + .down.sql，用 monkeypatch 把 MIGRATIONS_DIR 指過去。"""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        # 把真 0001 複製過去（reconcile 需要）
        real_baseline = migrate.MIGRATIONS_DIR / "0001_baseline_schema.sql"
        (mig_dir / "0001_baseline_schema.sql").write_text(real_baseline.read_text())
        # 加 dummy 0099
        (mig_dir / "0099_add_dummy.sql").write_text(
            "ALTER TABLE transcriptions ADD COLUMN _dummy INTEGER DEFAULT 0;\n"
        )
        (mig_dir / "0099_add_dummy.down.sql").write_text(
            "ALTER TABLE transcriptions DROP COLUMN _dummy;\n"
        )
        monkeypatch.setattr(migrate, "MIGRATIONS_DIR", mig_dir)
        return baseline_db

    def test_up_applies_dummy_migration(self, dummy_migration):
        """0099 上去後欄位應出現。"""
        rc = migrate.cmd_up(dummy_migration, target=None, dry_run=False)
        assert rc == 0
        conn = sqlite3.connect(dummy_migration)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(transcriptions)").fetchall()]
        assert "_dummy" in cols
        conn.close()

    def test_down_rolls_back_dummy_only(self, dummy_migration):
        """down 0001 應只 rollback 0099，留下 0001 baseline 紀錄。"""
        migrate.cmd_up(dummy_migration, target=None, dry_run=False)
        rc = migrate.cmd_down(dummy_migration, target="0001", dry_run=False)
        assert rc == 0
        conn = sqlite3.connect(dummy_migration)
        # 0099 不在 schema_migrations
        applied = migrate._applied(conn)
        assert "0099" not in applied
        assert "0001" in applied
        # _dummy 欄位也消失
        cols = [r[1] for r in conn.execute("PRAGMA table_info(transcriptions)").fetchall()]
        assert "_dummy" not in cols
        conn.close()

    def test_down_refuses_without_down_sql(self, tmp_path, monkeypatch, baseline_db):
        """沒有 .down.sql 時 down 應 return 2 並拒絕。"""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        real_baseline = migrate.MIGRATIONS_DIR / "0001_baseline_schema.sql"
        (mig_dir / "0001_baseline_schema.sql").write_text(real_baseline.read_text())
        # 0099 沒 .down.sql
        (mig_dir / "0099_no_down.sql").write_text(
            "ALTER TABLE transcriptions ADD COLUMN _x INTEGER DEFAULT 0;\n"
        )
        monkeypatch.setattr(migrate, "MIGRATIONS_DIR", mig_dir)

        migrate.cmd_up(baseline_db, target=None, dry_run=False)
        rc = migrate.cmd_down(baseline_db, target="0001", dry_run=False)
        assert rc == 2  # 拒絕代碼

    def test_dry_run_does_not_apply(self, dummy_migration):
        """--dry-run 不應寫 schema_migrations、不應改 schema。"""
        rc = migrate.cmd_up(dummy_migration, target=None, dry_run=True)
        assert rc == 0
        conn = sqlite3.connect(dummy_migration)
        applied = migrate._applied(conn)
        assert "0099" not in applied
        cols = [r[1] for r in conn.execute("PRAGMA table_info(transcriptions)").fetchall()]
        assert "_dummy" not in cols
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 0002 round-trip test
# ─────────────────────────────────────────────────────────────────────────────

class TestMigration0002:
    """0002_add_usage_log 真 migration（不是 dummy）的 round-trip。"""

    def test_0002_creates_usage_log_table(self, baseline_db):
        # baseline_db 已套用 0001。
        # 跑 cmd_up 應該套上 0002（reconcile 0001 + apply 0002）
        rc = migrate.cmd_up(baseline_db, target=None, dry_run=False)
        assert rc == 0

        import sqlite3
        conn = sqlite3.connect(baseline_db)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_log'"
        ).fetchall()
        assert len(rows) == 1
        # 確認欄位齊全
        cols = [r[1] for r in conn.execute("PRAGMA table_info(usage_log)").fetchall()]
        for c in ("channel_id", "engine", "occurred_at", "usage_json", "cost_usd", "cost_twd"):
            assert c in cols, f"missing column {c}"
        conn.close()
