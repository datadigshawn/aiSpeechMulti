#!/usr/bin/env python3
"""Schema migration runner — pure stdlib, raw sqlite3.

慣例：
- migrations/NNNN_<snake_case_name>.sql       up migration
- migrations/NNNN_<snake_case_name>.down.sql  rollback (optional but recommended)
- 編號 4 位連續整數
- 一個 migration = 一個邏輯變更
- 應套用後不可修改（checksum 會偵測 drift）

用法：
    python -m utils.migrate status
    python -m utils.migrate up [target_version]
    python -m utils.migrate down <target_version>
    python -m utils.migrate <cmd> --dry-run
    python -m utils.migrate <cmd> --db /path/to/other.db
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
DEFAULT_DB = PROJECT_ROOT / "data" / "aiSpeechMulti.db"

UP_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
DOWN_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.down\.sql$")


def _ensure_tracking_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            checksum   TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _list_migrations() -> list[tuple[str, str, Path, Path | None]]:
    """Return [(version, name, up_path, down_path_or_none), ...] sorted by version."""
    if not MIGRATIONS_DIR.exists():
        return []
    ups: dict[str, tuple[str, Path]] = {}
    downs: dict[str, Path] = {}
    for p in sorted(MIGRATIONS_DIR.iterdir()):
        m = DOWN_RE.match(p.name)
        if m:
            downs[m.group(1)] = p
            continue
        m = UP_RE.match(p.name)
        if m:
            ups[m.group(1)] = (m.group(2), p)
    out = []
    for ver in sorted(ups.keys()):
        name, up_path = ups[ver]
        out.append((ver, name, up_path, downs.get(ver)))
    return out


def _applied(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT version, name, applied_at, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {r[0]: {"name": r[1], "applied_at": r[2], "checksum": r[3]} for r in rows}


def _backup(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = db_path.parent / f"{db_path.name}.bak.{ts}"
    shutil.copy2(db_path, bak)
    return bak


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ───── Commands ──────────────────────────────────────────────────────────────

def cmd_status(db_path: Path) -> int:
    conn = _connect(db_path)
    try:
        _ensure_tracking_table(conn)
        applied = _applied(conn)
        all_ms = _list_migrations()
        if not all_ms:
            print(f"No migrations in {MIGRATIONS_DIR}")
            return 0
        print(f"DB: {db_path}")
        print(f"Migrations dir: {MIGRATIONS_DIR}")
        print()
        print(f"{'Version':<8} {'Name':<35} {'Status':<12} {'Applied at'}")
        print("─" * 80)
        for ver, name, up_path, _ in all_ms:
            if ver in applied:
                row = applied[ver]
                actual = _file_checksum(up_path)
                if actual != row["checksum"]:
                    status = "⚠ DRIFT"
                else:
                    status = "✓ applied"
                print(f"{ver:<8} {name:<35} {status:<12} {row['applied_at']}")
            else:
                print(f"{ver:<8} {name:<35} {'· pending':<12}")
        return 0
    finally:
        conn.close()


def cmd_up(db_path: Path, target: str | None, dry_run: bool) -> int:
    all_ms = _list_migrations()
    if not all_ms:
        print(f"No migrations in {MIGRATIONS_DIR}")
        return 0

    conn = _connect(db_path)
    try:
        _ensure_tracking_table(conn)
        applied = _applied(conn)

        pending = [m for m in all_ms if m[0] not in applied]
        if target:
            pending = [m for m in pending if m[0] <= target]
        if not pending:
            print("Already up to date.")
            return 0

        # Baseline reconcile: 若 0001 未套用但表已存在，僅記錄不執行
        first_ver = pending[0][0]
        if first_ver == "0001" and not applied and _table_exists(conn, "transcriptions"):
            ver, name, up_path, _ = pending[0]
            if dry_run:
                print(f"[dry-run] Would reconcile baseline {ver}_{name} (existing schema)")
            else:
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
                    (ver, name, _file_checksum(up_path)),
                )
                conn.commit()
                print(f"✓ Reconciled baseline {ver}_{name} (existing schema preserved, no DDL run)")
            pending = pending[1:]

        if not pending:
            return 0

        if not dry_run:
            bak = _backup(db_path)
            if bak:
                print(f"Backup: {bak.name}")

        for ver, name, up_path, _ in pending:
            sql = up_path.read_text(encoding="utf-8")
            print(f"\n── Applying {ver}_{name} ──")
            if dry_run:
                print(sql)
                print(f"[dry-run] Would record {ver}_{name}")
                continue
            try:
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
                    (ver, name, _file_checksum(up_path)),
                )
                conn.commit()
                print(f"✓ Applied {ver}_{name}")
            except Exception as e:
                conn.rollback()
                print(f"✗ FAILED {ver}_{name}: {e}", file=sys.stderr)
                return 1
        return 0
    finally:
        conn.close()


def cmd_down(db_path: Path, target: str, dry_run: bool) -> int:
    """Roll back migrations newer than target (target itself stays applied)."""
    all_ms = _list_migrations()
    conn = _connect(db_path)
    try:
        _ensure_tracking_table(conn)
        applied = _applied(conn)

        # Collect applied migrations strictly newer than target, in reverse
        to_rollback = [m for m in all_ms if m[0] in applied and m[0] > target]
        to_rollback.reverse()

        if not to_rollback:
            print(f"Nothing to roll back (already at {target} or older).")
            return 0

        missing = [(v, n) for v, n, _, dn in to_rollback if dn is None]
        if missing:
            print("Cannot roll back — missing .down.sql for:", file=sys.stderr)
            for v, n in missing:
                print(f"  {v}_{n}", file=sys.stderr)
            return 2

        if not dry_run:
            bak = _backup(db_path)
            if bak:
                print(f"Backup: {bak.name}")

        for ver, name, _, down_path in to_rollback:
            sql = down_path.read_text(encoding="utf-8")
            print(f"\n── Rolling back {ver}_{name} ──")
            if dry_run:
                print(sql)
                print(f"[dry-run] Would delete {ver} from schema_migrations")
                continue
            try:
                conn.executescript(sql)
                conn.execute("DELETE FROM schema_migrations WHERE version = ?", (ver,))
                conn.commit()
                print(f"✓ Rolled back {ver}_{name}")
            except Exception as e:
                conn.rollback()
                print(f"✗ FAILED rolling back {ver}_{name}: {e}", file=sys.stderr)
                return 1
        return 0
    finally:
        conn.close()


# ───── Public API for db_manager.py ─────────────────────────────────────────

def run_pending(db_path: Path | None = None) -> None:
    """供 db_manager._init_schema() 啟動時呼叫。靜默套用所有 pending migration。"""
    db_path = db_path or DEFAULT_DB
    cmd_up(db_path, target=None, dry_run=False)


# ───── CLI entry ────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aispeech-migrate",
        description="aiSpeechMulti schema migration runner (numbered SQL in migrations/)",
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB,
        help=f"DB path (default: {DEFAULT_DB.relative_to(PROJECT_ROOT)})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="List applied / pending migrations")
    p_up = sub.add_parser("up", help="Apply all pending (or up to target)")
    p_up.add_argument("target", nargs="?", help="Apply up to this version (inclusive)")
    p_down = sub.add_parser("down", help="Roll back to target (target stays applied)")
    p_down.add_argument("target", help="Roll back to this version")

    args = parser.parse_args(argv)
    if args.cmd == "status":
        return cmd_status(args.db)
    if args.cmd == "up":
        return cmd_up(args.db, args.target, args.dry_run)
    if args.cmd == "down":
        return cmd_down(args.db, args.target, args.dry_run)
    return 2


if __name__ == "__main__":
    sys.exit(main())
