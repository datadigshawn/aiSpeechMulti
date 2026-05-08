"""Tests for utils/usage_ledger.py — 使用量 ledger（in-memory + DB persist）。"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest

from utils.usage_ledger import UsageLedger, UsageEvent


@pytest.fixture
def ledger_db(tmp_db_path):
    """乾淨 DB 含 usage_log 表（套 0001 + 0002 baseline）。"""
    sql_0001 = (Path(__file__).resolve().parent.parent / "migrations" / "0001_baseline_schema.sql").read_text()
    sql_0002 = (Path(__file__).resolve().parent.parent / "migrations" / "0002_add_usage_log.sql").read_text()
    conn = sqlite3.connect(tmp_db_path)
    conn.executescript(sql_0001)
    conn.executescript(sql_0002)
    conn.commit()
    conn.close()
    return tmp_db_path


@pytest.fixture
def sample_pricing():
    return {
        "usd_to_twd": 31.0,
        "alerts": {"daily_warning_pct": 80, "daily_critical_pct": 100, "daily_budget_twd": 100},
        "engines": {
            "scribe_rt": {"type": "stt", "unit": "audio_seconds", "usd_per_unit": 0.000111},
            "google_stt_chirp_3": {"type": "stt", "unit": "audio_seconds", "usd_per_unit": 0.000400},
        },
    }


class TestRecord:
    def test_record_writes_to_db(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        ledger.record(channel_id="1", engine="scribe_rt", usage={"audio_seconds": 60.0})

        conn = sqlite3.connect(ledger_db)
        rows = conn.execute("SELECT channel_id, engine, cost_usd FROM usage_log").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "1"
        assert rows[0][1] == "scribe_rt"
        assert abs(rows[0][2] - 60 * 0.000111) < 1e-9
        conn.close()


class TestAggregations:
    def test_today_total_with_multiple_events(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        ledger.record("1", "scribe_rt", {"audio_seconds": 60.0})
        ledger.record("1", "google_stt_chirp_3", {"audio_seconds": 100.0})
        ledger.record("2", "scribe_rt", {"audio_seconds": 30.0})

        # scribe 60s = $0.00666 = NT$ 0.2065
        # google 100s = $0.04 = NT$ 1.24
        # scribe 30s = $0.00333 = NT$ 0.1033
        # total ≈ NT$ 1.55
        assert abs(ledger.today_total_twd() - (60 + 30) * 0.000111 * 31 - 100 * 0.000400 * 31) < 0.01

    def test_session_total_matches_in_memory(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        ledger.record("1", "scribe_rt", {"audio_seconds": 60.0})
        ledger.record("2", "scribe_rt", {"audio_seconds": 60.0})
        # session = sum of 2 events
        expected = 2 * 60 * 0.000111 * 31
        assert abs(ledger.session_total_twd() - expected) < 1e-6

    def test_by_channel_groups_by_channel_and_engine(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        ledger.record("1", "scribe_rt", {"audio_seconds": 60.0})
        ledger.record("1", "google_stt_chirp_3", {"audio_seconds": 100.0})
        ledger.record("2", "scribe_rt", {"audio_seconds": 30.0})

        result = ledger.by_channel()
        # 應有 2 個 channel
        assert len(result) == 2
        ch1 = next(c for c in result if c["channel_id"] == "1")
        # ch1 有兩個引擎
        assert len(ch1["by_engine"]) == 2
        assert {e["engine"] for e in ch1["by_engine"]} == {"scribe_rt", "google_stt_chirp_3"}

    def test_empty_ledger_returns_zero(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        assert ledger.today_total_twd() == 0.0
        assert ledger.session_total_twd() == 0.0
        assert ledger.by_channel() == []

    def test_alert_level_changes_with_total(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        # daily_budget_twd = 100，warning = 80%
        # 跑到 NT$ 90 = 90% → warning
        # 一筆 google 100s = NT$ 1.24，要跑 ~73 筆才到 NT$ 90
        # 簡化用 scribe 多一點：scribe 1 sec = $0.000111 * 31 = NT$ 0.00344
        # 要 NT$ 90 → 26200 sec ≈ 7.3 hr，不實際；改用 mock 路徑
        # 直接寫一筆超大 audio_seconds
        ledger.record("1", "scribe_rt", {"audio_seconds": 30000.0})  # ≈ NT$ 103
        assert ledger.alert_level() == "critical"
