#!/usr/bin/env python3
"""sync_cer_to_sqlite.py — 把 cer_history.csv / cer_event_type_history.csv 同步進 SQLite。

介面整併 P2：Grafana 的 frser-sqlite-datasource 透過 aiSpeechMulti.db 讀取，
所以把 CSV 鏡進 DB 是最低成本接 Grafana 的做法（無需新增 datasource plugin）。

用法：
    python scripts/sync_cer_to_sqlite.py
    或
    python -m aispeech data sync-cer

策略：
- 整表重建（DROP + CREATE + bulk INSERT），不做增量
  CSV 是 append-only 的事件記錄，整表重建簡單可靠且每次幾百筆無感
- 每次同步寫一行到 cer_sync_log，方便 Grafana 顯示「最後同步時間」
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aiSpeechMulti.db"
CER_HISTORY_CSV = PROJECT_ROOT / "experiments" / "llm_correction_poc" / "cer_history.csv"
CER_EVENT_CSV   = PROJECT_ROOT / "experiments" / "llm_correction_poc" / "cer_event_type_history.csv"


CER_HISTORY_DDL = """
CREATE TABLE cer_history (
    timestamp        TEXT,
    timestamp_iso    TEXT,
    timestamp_unix   INTEGER,    -- Grafana time series 用
    engine_label     TEXT,
    post_process     TEXT,
    sample_count     INTEGER,
    success_count    INTEGER,
    avg_cer_raw      REAL,
    avg_cer_final    REAL,
    avg_improvement  REAL,
    avg_wer_final    REAL,
    source_json      TEXT
);
CREATE INDEX cer_history_engine_ts ON cer_history(engine_label, timestamp_unix);
"""

CER_EVENT_DDL = """
CREATE TABLE cer_event_type_history (
    timestamp        TEXT,
    timestamp_iso    TEXT,
    timestamp_unix   INTEGER,
    engine_label     TEXT,
    post_process     TEXT,
    event_type       TEXT,
    sample_count     INTEGER,
    avg_cer_raw      REAL,
    avg_cer_final    REAL,
    avg_improvement  REAL,
    source_json      TEXT
);
CREATE INDEX cer_event_engine_ts ON cer_event_type_history(engine_label, event_type, timestamp_unix);
"""

CER_SYNC_LOG_DDL = """
CREATE TABLE IF NOT EXISTS cer_sync_log (
    sync_at_iso    TEXT,
    sync_at_unix   INTEGER,
    history_rows   INTEGER,
    event_rows     INTEGER
);
"""


def _to_unix(iso: str) -> int | None:
    try:
        return int(datetime.fromisoformat(iso).timestamp() * 1000)  # Grafana 用毫秒
    except Exception:
        return None


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        print(f"⚠️  CSV 不存在：{path}", file=sys.stderr)
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            row["timestamp_unix"] = _to_unix(row.get("timestamp_iso", ""))
            rows.append(row)
    return rows


def _coerce_int(v):
    try: return int(v)
    except (TypeError, ValueError): return None


def _coerce_float(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def main() -> int:
    if not DB_PATH.exists():
        print(f"❌ DB 不存在：{DB_PATH}", file=sys.stderr)
        return 1

    history_rows = _load_csv(CER_HISTORY_CSV)
    event_rows   = _load_csv(CER_EVENT_CSV)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 整表重建
    cur.execute("DROP TABLE IF EXISTS cer_history")
    cur.executescript(CER_HISTORY_DDL)
    cur.executemany(
        """INSERT INTO cer_history
           (timestamp, timestamp_iso, timestamp_unix, engine_label, post_process,
            sample_count, success_count, avg_cer_raw, avg_cer_final,
            avg_improvement, avg_wer_final, source_json)
           VALUES (:timestamp, :timestamp_iso, :timestamp_unix, :engine_label,
                   :post_process, :sample_count, :success_count, :avg_cer_raw,
                   :avg_cer_final, :avg_improvement, :avg_wer_final, :source_json)""",
        [{
            **r,
            "sample_count":    _coerce_int(r.get("sample_count")),
            "success_count":   _coerce_int(r.get("success_count")),
            "avg_cer_raw":     _coerce_float(r.get("avg_cer_raw")),
            "avg_cer_final":   _coerce_float(r.get("avg_cer_final")),
            "avg_improvement": _coerce_float(r.get("avg_improvement")),
            "avg_wer_final":   _coerce_float(r.get("avg_wer_final")),
        } for r in history_rows]
    )

    cur.execute("DROP TABLE IF EXISTS cer_event_type_history")
    cur.executescript(CER_EVENT_DDL)
    cur.executemany(
        """INSERT INTO cer_event_type_history
           (timestamp, timestamp_iso, timestamp_unix, engine_label, post_process,
            event_type, sample_count, avg_cer_raw, avg_cer_final,
            avg_improvement, source_json)
           VALUES (:timestamp, :timestamp_iso, :timestamp_unix, :engine_label,
                   :post_process, :event_type, :sample_count, :avg_cer_raw,
                   :avg_cer_final, :avg_improvement, :source_json)""",
        [{
            **r,
            "sample_count":    _coerce_int(r.get("sample_count")),
            "avg_cer_raw":     _coerce_float(r.get("avg_cer_raw")),
            "avg_cer_final":   _coerce_float(r.get("avg_cer_final")),
            "avg_improvement": _coerce_float(r.get("avg_improvement")),
        } for r in event_rows]
    )

    cur.executescript(CER_SYNC_LOG_DDL)
    now = datetime.now()
    cur.execute(
        "INSERT INTO cer_sync_log VALUES (?, ?, ?, ?)",
        (now.isoformat(), int(now.timestamp() * 1000), len(history_rows), len(event_rows)),
    )

    conn.commit()
    conn.close()

    print(f"✅ cer_history          {len(history_rows):4d} 列")
    print(f"✅ cer_event_type_hist  {len(event_rows):4d} 列")
    print(f"✅ DB: {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
