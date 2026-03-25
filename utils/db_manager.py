#!/usr/bin/env python3
"""
aiSpeech 資料庫管理器
版本: 1.1

功能：
- 以 SQLite 儲存語音辨識事件、音檔記錄、辨識結果與關鍵字
- FTS5 全文搜尋（save_transcription 呼叫時手動同步，避免 trigger BEGIN...END 相容性問題）
- 零外部相依（僅使用 Python 內建 sqlite3）

資料表：
  events              - 事件（一次辨識批次）
  audio_files         - 各音檔基本資訊（含封存路徑、SHA-256）
  transcriptions      - 辨識結果（對應 audio_files）
  transcriptions_fts  - FTS5 全文搜尋虛擬表（手動同步）
  keywords            - 關鍵字（P2 填入，P1 先建表）
"""

import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional

try:
    from .logger import get_logger
except ImportError:
    import logging
    def get_logger(name):
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)


# 預設 DB 位置（呼叫端可覆寫）
_DEFAULT_DB = Path(__file__).parent.parent / "data" / "aiSpeech.db"

# ── DDL ──────────────────────────────────────────────────────────────────────

_DDL_STATEMENTS = [
    # 事件表：一次辨識批次 = 一個事件
    """
    CREATE TABLE IF NOT EXISTS events (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        event_name   TEXT    NOT NULL,
        event_date   DATE,
        model_type   TEXT,
        sub_model    TEXT,
        hazard_level INTEGER DEFAULT 0,
        notes        TEXT,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # 音檔表：每個原始音檔一筆記錄
    """
    CREATE TABLE IF NOT EXISTS audio_files (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id          INTEGER REFERENCES events(id) ON DELETE CASCADE,
        original_filename TEXT NOT NULL,
        archive_path      TEXT,
        file_hash         TEXT,
        file_size         INTEGER,
        recorded_at       TIMESTAMP,
        created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # 辨識結果表
    """
    CREATE TABLE IF NOT EXISTS transcriptions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        audio_file_id   INTEGER REFERENCES audio_files(id) ON DELETE CASCADE,
        event_id        INTEGER REFERENCES events(id) ON DELETE CASCADE,
        transcript      TEXT,
        status          TEXT    DEFAULT 'success',
        error_message   TEXT,
        use_vad         INTEGER DEFAULT 0,
        use_denoise     INTEGER DEFAULT 0,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # FTS5 全文搜尋（獨立表，在 save_transcription 中手動同步）
    # trigram tokenizer：適合中文子字串搜尋，查詢字串需 ≥3 字元
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS transcriptions_fts USING fts5(
        transcript,
        tokenize='trigram'
    )
    """,
    # 關鍵字表（P2 填入，P1 先建表）
    """
    CREATE TABLE IF NOT EXISTS keywords (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id          INTEGER REFERENCES events(id) ON DELETE CASCADE,
        transcription_id  INTEGER REFERENCES transcriptions(id) ON DELETE SET NULL,
        keyword           TEXT NOT NULL,
        source            TEXT DEFAULT 'manual',
        hazard_level      INTEGER DEFAULT 0,
        created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # 索引
    "CREATE INDEX IF NOT EXISTS idx_audio_event ON audio_files(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_trans_audio  ON transcriptions(audio_file_id)",
    "CREATE INDEX IF NOT EXISTS idx_trans_event  ON transcriptions(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_kw_event     ON keywords(event_id)",
]


# ── DBManager ────────────────────────────────────────────────────────────────

class DBManager:
    """
    SQLite 資料庫管理器

    使用方式：
        db = DBManager()
        event_id = db.create_event("捷運火災", "google_stt", "chirp_3")
        audio_id = db.save_audio_file(event_id, "20251222_1922.wav")
        db.save_transcription(audio_id, event_id, "OCC 收到，立即至 G05")
        db.close()

    支援 context manager：
        with DBManager() as db:
            event_id = db.create_event(...)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        初始化資料庫連線並建立所有資料表。

        Args:
            db_path: SQLite 資料庫路徑；None 時使用專案預設路徑
                     (PROJECT_ROOT/data/aiSpeech.db)
        """
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.logger = get_logger(self.__class__.__name__)

        # 確保 data/ 目錄存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 建立連線（check_same_thread=False 供 Streamlit 多執行緒使用）
        # 注意：不使用 detect_types，日期時間欄位以 ISO 字串儲存（Python 3.12 相容）
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")

        self._init_schema()
        self.logger.info(f"DB 已連線：{self.db_path}")

    # ── Schema 初始化 ───────────────────────────────────────────────────────

    def _init_schema(self):
        """建立所有資料表與索引（冪等操作）。"""
        for stmt in _DDL_STATEMENTS:
            self._conn.execute(stmt)
        # 相容舊版資料庫：欄位不存在時自動補上
        for col in ("use_vad", "use_denoise"):
            try:
                self._conn.execute(
                    f"ALTER TABLE transcriptions ADD COLUMN {col} INTEGER DEFAULT 0"
                )
            except Exception:
                pass  # 欄位已存在，忽略
        # 修正既有資料庫中 TEXT 型態的 "0"/"1" → INTEGER
        self._conn.execute("UPDATE transcriptions SET use_vad=CAST(use_vad AS INTEGER), "
                           "use_denoise=CAST(use_denoise AS INTEGER) "
                           "WHERE typeof(use_vad)='text' OR typeof(use_denoise)='text'")
        self._conn.commit()

    # ── 事件 ────────────────────────────────────────────────────────────────

    def create_event(
        self,
        event_name: str,
        model_type: str,
        sub_model: str,
        event_date=None,
        hazard_level: int = 0,
        notes: str = None,
    ) -> int:
        """
        建立一筆事件記錄。

        Args:
            event_name:   事件名稱
            model_type:   模型類型 ("google_stt" | "gemini" | "whisper")
            sub_model:    子模型名稱 ("chirp_3" | "gemini-2.5-pro" 等)
            event_date:   事件日期（datetime.date 或 None）
            hazard_level: 危害等級 0~5（P2 人為設定，預設 0）
            notes:        備注

        Returns:
            int: 新插入的 events.id
        """
        if event_date and not isinstance(event_date, str):
            event_date = event_date.isoformat()

        cur = self._conn.execute(
            """
            INSERT INTO events
                (event_name, event_date, model_type, sub_model, hazard_level, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_name, event_date, model_type, sub_model, hazard_level, notes),
        )
        self._conn.commit()
        event_id = cur.lastrowid
        self.logger.info(f"建立事件 id={event_id}  name={event_name!r}")
        return event_id

    # ── 音檔 ────────────────────────────────────────────────────────────────

    def save_audio_file(
        self,
        event_id: int,
        original_filename: str,
        archive_path: Optional[str] = None,
        file_hash: Optional[str] = None,
        file_size: Optional[int] = None,
        recorded_at=None,
    ) -> int:
        """
        儲存一筆音檔記錄。

        Args:
            event_id:           對應事件 ID
            original_filename:  原始檔名
            archive_path:       封存後的絕對路徑（None = 未封存）
            file_hash:          SHA-256 hex 字串
            file_size:          檔案大小（bytes）
            recorded_at:        從檔名解析的錄製時間（datetime 或 None）

        Returns:
            int: 新插入的 audio_files.id
        """
        if recorded_at and not isinstance(recorded_at, str):
            recorded_at = recorded_at.isoformat()

        cur = self._conn.execute(
            """
            INSERT INTO audio_files
                (event_id, original_filename, archive_path,
                 file_hash, file_size, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, original_filename, archive_path,
             file_hash, file_size, recorded_at),
        )
        self._conn.commit()
        audio_id = cur.lastrowid
        self.logger.debug(f"儲存音檔 id={audio_id}  file={original_filename!r}")
        return audio_id

    # ── 辨識結果 ────────────────────────────────────────────────────────────

    def save_transcription(
        self,
        audio_file_id: int,
        event_id: int,
        transcript: str,
        status: str = "success",
        error_message: Optional[str] = None,
        use_vad: bool = False,
        use_denoise: bool = False,
    ) -> int:
        """
        儲存一筆辨識結果，並同步更新 FTS5 全文搜尋索引。

        Args:
            audio_file_id:  對應音檔 ID
            event_id:       對應事件 ID
            transcript:     辨識文字（後處理後）
            status:         "success" | "error"
            error_message:  錯誤訊息（status="error" 時使用）
            use_vad:        本次辨識是否開啟 Silero VAD 前處理
            use_denoise:    本次辨識是否開啟 DeepFilterNet 降噪前處理

        Returns:
            int: 新插入的 transcriptions.id
        """
        cur = self._conn.execute(
            """
            INSERT INTO transcriptions
                (audio_file_id, event_id, transcript, status, error_message, use_vad, use_denoise)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (audio_file_id, event_id, transcript, status, error_message,
             int(use_vad), int(use_denoise)),
        )
        trans_id = cur.lastrowid

        # 同步 FTS5（手動插入，避免 trigger BEGIN...END 相容性問題）
        if transcript:
            self._conn.execute(
                "INSERT INTO transcriptions_fts(rowid, transcript) VALUES (?, ?)",
                (trans_id, transcript),
            )

        self._conn.commit()
        self.logger.debug(
            f"儲存辨識結果 id={trans_id}  status={status}  "
            f"text={repr(transcript[:30]) if transcript else '(empty)'}"
        )
        return trans_id

    # ── 關鍵字（P2 預留） ───────────────────────────────────────────────────

    def add_keyword(
        self,
        event_id: int,
        keyword: str,
        source: str = "manual",
        transcription_id: Optional[int] = None,
        hazard_level: int = 0,
    ) -> int:
        """
        新增關鍵字（P2 人工 / AI 填入）。

        Returns:
            int: 新插入的 keywords.id
        """
        cur = self._conn.execute(
            """
            INSERT INTO keywords
                (event_id, transcription_id, keyword, source, hazard_level)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_id, transcription_id, keyword, source, hazard_level),
        )
        self._conn.commit()
        return cur.lastrowid

    # ── P2：危害等級 / 備注 / 關鍵字管理 ────────────────────────────────────

    def update_event_hazard(self, event_id: int, hazard_level: int) -> None:
        """
        更新事件危害等級（P2 人為設定）。

        Args:
            event_id:     事件 ID
            hazard_level: 危害等級 0~5
        """
        self._conn.execute(
            "UPDATE events SET hazard_level=? WHERE id=?",
            (hazard_level, event_id),
        )
        self._conn.commit()
        self.logger.info(f"事件 id={event_id} 危害等級更新為 {hazard_level}")

    def update_event_notes(self, event_id: int, notes: str) -> None:
        """
        更新事件備注。

        Args:
            event_id: 事件 ID
            notes:    備注文字
        """
        self._conn.execute(
            "UPDATE events SET notes=? WHERE id=?",
            (notes, event_id),
        )
        self._conn.commit()
        self.logger.debug(f"事件 id={event_id} 備注已更新")

    def get_event_keywords(self, event_id: int) -> list:
        """
        取得某事件的所有關鍵字（依危害等級降冪、建立時間升冪排序）。

        Returns:
            list[sqlite3.Row]: id, keyword, source, hazard_level, created_at
        """
        return self._conn.execute(
            """
            SELECT id, keyword, source, hazard_level, created_at
            FROM keywords
            WHERE event_id = ?
            ORDER BY hazard_level DESC, created_at
            """,
            (event_id,),
        ).fetchall()

    def delete_keyword(self, keyword_id: int) -> None:
        """
        刪除關鍵字。

        Args:
            keyword_id: keywords.id
        """
        self._conn.execute("DELETE FROM keywords WHERE id=?", (keyword_id,))
        self._conn.commit()
        self.logger.debug(f"關鍵字 id={keyword_id} 已刪除")

    def find_keyword_in_event(self, event_id: int, keyword: str) -> Optional[dict]:
        """
        在指定事件中尋找相同關鍵字（不分大小寫）。

        Returns:
            dict with id/keyword/hazard_level/source，或 None（不存在）
        """
        row = self._conn.execute(
            """
            SELECT id, keyword, hazard_level, source
            FROM keywords
            WHERE event_id = ? AND LOWER(keyword) = LOWER(?)
            LIMIT 1
            """,
            (event_id, keyword),
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "keyword": row[1], "hazard_level": row[2], "source": row[3]}

    def get_all_keywords(self) -> list:
        """
        取得所有事件的所有關鍵字（含事件名稱），供全局 CSV 匯出使用。
        """
        return self._conn.execute(
            """
            SELECT k.id, k.keyword, k.hazard_level, k.source,
                   e.id AS event_id, e.event_name, k.created_at
            FROM keywords k
            JOIN events e ON k.event_id = e.id
            ORDER BY k.hazard_level DESC, k.created_at
            """
        ).fetchall()

    # ── 查詢（P3 預留） ─────────────────────────────────────────────────────

    def search_transcriptions(self, query: str, limit: int = 50) -> list:
        """
        FTS5 全文搜尋辨識結果（trigram tokenizer）。

        注意：trigram tokenizer 要求查詢字串長度 ≥3 字元。
              2 字元查詢（如「疏散」）請改用 search_transcriptions_like()。

        Args:
            query: 搜尋字串（≥3 字元；支援 FTS5 MATCH 語法）
            limit: 最多回傳筆數

        Returns:
            list[sqlite3.Row]
        """
        rows = self._conn.execute(
            """
            SELECT t.id, t.event_id, t.transcript, t.created_at,
                   a.original_filename, e.event_name
            FROM transcriptions_fts fts
            JOIN transcriptions t ON t.id = fts.rowid
            JOIN audio_files a    ON a.id = t.audio_file_id
            JOIN events e         ON e.id = t.event_id
            WHERE transcriptions_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return rows

    def search_transcriptions_like(self, keyword: str, limit: int = 50) -> list:
        """
        LIKE 子字串搜尋（無最小長度限制，適合 1~2 字元查詢）。
        速度較 FTS5 慢，但對短關鍵字更可靠。

        Args:
            keyword: 搜尋關鍵字（SQL LIKE 萬用字元 %/_ 會自動跳脫）
            limit:   最多回傳筆數

        Returns:
            list[sqlite3.Row]
        """
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        return self._conn.execute(
            """
            SELECT t.id, t.event_id, t.transcript, t.created_at,
                   a.original_filename, e.event_name
            FROM transcriptions t
            JOIN audio_files a ON a.id = t.audio_file_id
            JOIN events e      ON e.id = t.event_id
            WHERE t.transcript LIKE ? ESCAPE '\\'
            ORDER BY t.created_at DESC
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()

    def list_events(self, limit: int = 100) -> list:
        """列出最近的事件（降冪）。"""
        return self._conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def get_event_transcriptions(self, event_id: int) -> list:
        """取得某事件的所有辨識結果（含音檔名稱、錄製時間）。"""
        return self._conn.execute(
            """
            SELECT t.id, t.transcript, t.status, t.created_at,
                   a.original_filename, a.recorded_at
            FROM transcriptions t
            JOIN audio_files a ON a.id = t.audio_file_id
            WHERE t.event_id = ?
            ORDER BY a.recorded_at NULLS LAST, t.id
            """,
            (event_id,),
        ).fetchall()

    # ── P3：統計查詢 ─────────────────────────────────────────────────────────

    def get_stats_summary(self) -> dict:
        """整體統計摘要（事件數、音檔數、辨識筆數、關鍵字數）。"""
        row = self._conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM events)        AS total_events,
                (SELECT COUNT(*) FROM audio_files)   AS total_audios,
                (SELECT COUNT(*) FROM transcriptions WHERE status='success') AS total_trans,
                (SELECT COUNT(*) FROM keywords)      AS total_keywords
            """
        ).fetchone()
        return dict(row) if row else {}

    def get_stats_by_date(self) -> list:
        """按事件日期統計（回傳 event_date, count, max_hazard）。"""
        return self._conn.execute(
            """
            SELECT event_date,
                   COUNT(*)           AS count,
                   MAX(hazard_level)  AS max_hazard
            FROM events
            WHERE event_date IS NOT NULL
            GROUP BY event_date
            ORDER BY event_date
            """
        ).fetchall()

    def get_stats_by_model(self) -> list:
        """按模型統計事件數（model_type, sub_model, count）。"""
        return self._conn.execute(
            """
            SELECT model_type, sub_model, COUNT(*) AS count
            FROM events
            GROUP BY model_type, sub_model
            ORDER BY count DESC
            """
        ).fetchall()

    def get_stats_by_hazard(self) -> list:
        """按危害等級統計事件數（hazard_level, count）。"""
        return self._conn.execute(
            """
            SELECT hazard_level, COUNT(*) AS count
            FROM events
            GROUP BY hazard_level
            ORDER BY hazard_level
            """
        ).fetchall()

    def export_all_events_csv(self, limit: int = 5000) -> list:
        """
        匯出全部事件資料（含音檔與辨識結果），供 CSV 下載使用。

        Returns:
            list[sqlite3.Row]: event_id, event_name, event_date, model_type,
                               sub_model, hazard_level, notes, event_created_at,
                               original_filename, recorded_at, file_size,
                               transcript, transcription_status,
                               use_vad, use_denoise
        """
        return self._conn.execute(
            """
            SELECT
                e.id              AS event_id,
                e.event_name,
                e.event_date,
                e.model_type,
                e.sub_model,
                e.hazard_level,
                e.notes,
                e.created_at      AS event_created_at,
                a.original_filename,
                a.recorded_at,
                a.file_size,
                t.transcript,
                t.status          AS transcription_status,
                CASE WHEN t.use_vad     = 1 THEN '是' ELSE '否' END AS use_vad,
                CASE WHEN t.use_denoise = 1 THEN '是' ELSE '否' END AS use_denoise
            FROM events e
            LEFT JOIN audio_files   a ON a.event_id     = e.id
            LEFT JOIN transcriptions t ON t.audio_file_id = a.id
            ORDER BY e.created_at DESC, a.recorded_at NULLS LAST
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    # ── 連線管理 ────────────────────────────────────────────────────────────

    def close(self):
        """關閉資料庫連線。"""
        if self._conn:
            self._conn.close()
            self._conn = None
            self.logger.debug("DB 連線已關閉")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── CLI 測試 ─────────────────────────────────────────────────────────────────

def _cli_test():
    """本地簡易測試（不依賴 Streamlit）。"""
    from datetime import date
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with DBManager(db_path) as db:
            # 建立事件
            eid = db.create_event(
                "捷運火災", "google_stt", "chirp_3",
                event_date=date(2025, 12, 22),
            )

            # 儲存音檔
            aid = db.save_audio_file(
                eid, "20251222_1922.wav",
                file_hash="abc123def456", file_size=204800,
            )

            # 儲存辨識結果
            tid = db.save_transcription(
                aid, eid, "OCC 收到，G05 立即至月台疏散旅客",
            )

            # 新增關鍵字
            kid = db.add_keyword(
                eid, "疏散",
                source="ai", transcription_id=tid, hazard_level=4,
            )

            # FTS5 全文搜尋（trigram，≥3 字元）
            fts_results = db.search_transcriptions("月台疏散")
            assert len(fts_results) == 1, f"FTS5 搜尋結果數量錯誤: {len(fts_results)}"
            assert fts_results[0]["event_name"] == "捷運火災", "FTS5 事件名稱不符"

            # LIKE 搜尋（2 字元）
            like_results = db.search_transcriptions_like("疏散")
            assert len(like_results) == 1, f"LIKE 搜尋結果數量錯誤: {len(like_results)}"

            # 列出事件
            events = db.list_events()
            assert len(events) == 1, f"事件數量錯誤: {len(events)}"

            # 取得事件辨識結果
            trans = db.get_event_transcriptions(eid)
            assert len(trans) == 1, f"辨識結果數量錯誤: {len(trans)}"

            print("✅ DBManager 測試全部通過")
            print(f"   事件 id={eid}, 音檔 id={aid}, 辨識 id={tid}, 關鍵字 id={kid}")
            print(f"   FTS5 搜尋「月台疏散」→ {fts_results[0]['transcript']!r}")
            print(f"   LIKE 搜尋「疏散」→ {like_results[0]['transcript']!r}")


if __name__ == "__main__":
    _cli_test()
