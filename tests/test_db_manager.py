"""Tests for utils/db_manager.py — SQLite + FTS5 主資料層。

涵蓋：
- 啟動建表（_init_schema 自動跑）
- create_event / save_audio_file / save_transcription（CRUD 主路徑）
- FTS5 search 真的能找到剛存的 transcript（包含 trigram ≥3 字限制）
- close 不留 lock

跳過（v2 再補）：
- 多 thread 並發 save（需 threading 設計）
- 大量資料 / 效能 / index 命中率
"""

from __future__ import annotations

from utils.db_manager import DBManager


class TestStartup:
    def test_init_creates_all_tables(self, tmp_db_path):
        """新 DB 啟動後應有所有主流程表。"""
        db = DBManager(tmp_db_path)
        rows = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = [r[0] for r in rows]
        for required in ("events", "audio_files", "transcriptions", "keywords"):
            assert required in names, f"missing table: {required}"
        db.close()

    def test_init_creates_fts_table(self, tmp_db_path):
        """FTS5 虛擬表應建立。"""
        db = DBManager(tmp_db_path)
        rows = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE name='transcriptions_fts'"
        ).fetchall()
        assert len(rows) == 1
        db.close()

    def test_init_records_baseline_migration(self, tmp_db_path):
        """整合 C3：DBManager 啟動應自動 reconcile 0001 baseline。"""
        db = DBManager(tmp_db_path)
        versions = [r["version"] for r in db._conn.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall()]
        assert "0001" in versions
        db.close()


class TestCRUD:
    def test_create_event_returns_id(self, tmp_db_path):
        db = DBManager(tmp_db_path)
        eid = db.create_event(
            event_name="測試事件",
            model_type="google_stt",
            sub_model="chirp_3",
        )
        assert isinstance(eid, int) and eid > 0
        db.close()

    def test_save_audio_and_transcription(self, tmp_db_path):
        db = DBManager(tmp_db_path)
        eid = db.create_event("test", "google_stt", "chirp_3")
        aid = db.save_audio_file(eid, "test.wav", archive_path="archive/test.wav")
        assert isinstance(aid, int) and aid > 0

        tid = db.save_transcription(aid, eid, "OCC 收到請繼續")
        assert isinstance(tid, int) and tid > 0
        db.close()


class TestFTSSearch:
    """FTS5 trigram 搜尋——存進去要能搜得到（≥3 字）。"""

    def test_search_finds_recently_saved(self, tmp_db_path):
        db = DBManager(tmp_db_path)
        eid = db.create_event("test", "google_stt", "chirp_3")
        aid = db.save_audio_file(eid, "test.wav")
        db.save_transcription(aid, eid, "OCC 收到 G07 站長呼叫")

        rows = db.search_transcriptions("G07 站長")  # ≥3 字
        assert len(rows) >= 1
        # 找到的 transcript 應包含關鍵字
        assert any("G07" in r["transcript"] for r in rows)
        db.close()

    def test_search_like_works_for_short_query(self, tmp_db_path):
        """LIKE 搜尋給 1~2 字短查詢用。"""
        db = DBManager(tmp_db_path)
        eid = db.create_event("test", "google_stt", "chirp_3")
        aid = db.save_audio_file(eid, "test.wav")
        db.save_transcription(aid, eid, "疏散乘客")

        rows = db.search_transcriptions_like("疏散")  # 2 字
        assert len(rows) >= 1
        db.close()


class TestClose:
    def test_close_releases_connection(self, tmp_db_path):
        """close 後第二次開應該也能跑（不被 lock）。"""
        db = DBManager(tmp_db_path)
        db.close()
        # 第二次開
        db2 = DBManager(tmp_db_path)
        assert db2._conn is not None
        db2.close()


class TestSTTWrapperAudioSeconds:
    """Smoke test: confirm STT wrapper modules import and have transcribe_file.

    We don't call the real API (needs key + network). We only verify the
    audio_duration helper works (since wrappers will use it) and that the
    wrapper modules still import cleanly after our edits.
    """

    def test_audio_duration_helper_works(self, tmp_path):
        import wave
        wav = tmp_path / "1sec.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000)

        from utils.audio_duration import audio_seconds
        assert abs(audio_seconds(wav) - 1.0) < 0.01

    def test_stt_wrapper_modules_import_cleanly(self):
        """Confirm wrapper modules still import after we added audio_seconds logic."""
        from scripts.models import model_scribe, model_google_stt
        assert hasattr(model_scribe, "ScribeSTTModel")
        assert hasattr(model_google_stt, "GoogleSTTModel")
        # Confirm transcribe_file method exists with expected signature
        import inspect
        scribe_sig = inspect.signature(model_scribe.ScribeSTTModel.transcribe_file)
        google_sig = inspect.signature(model_google_stt.GoogleSTTModel.transcribe_file)
        # 必含 audio_file 參數
        assert "audio_file" in scribe_sig.parameters
        assert "audio_file" in google_sig.parameters


class TestUsageLogQueries:
    """db_manager 對 usage_log 的存取（v1 純 SQL；之後可能抽 helper）。"""

    def test_can_insert_and_select_usage_log(self, tmp_db_path):
        db = DBManager(tmp_db_path)
        # baseline + 0002 應已套用
        # 直接 INSERT
        db._conn.execute(
            "INSERT INTO usage_log (channel_id, engine, occurred_at, usage_json, cost_usd, cost_twd) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("1", "scribe_rt", "2026-05-08T10:00:00", '{"audio_seconds": 60.0}', 0.00666, 0.20646)
        )
        db._conn.commit()
        rows = db._conn.execute("SELECT cost_usd FROM usage_log WHERE channel_id='1'").fetchall()
        assert len(rows) == 1
        assert abs(rows[0]["cost_usd"] - 0.00666) < 1e-6
        db.close()

    def test_db_init_runs_0002_migration(self, tmp_db_path):
        """DBManager 啟動應自動套用 0001 + 0002。"""
        db = DBManager(tmp_db_path)
        rows = db._conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        versions = [r["version"] for r in rows]
        assert "0001" in versions
        assert "0002" in versions
        db.close()
