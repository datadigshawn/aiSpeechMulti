-- ============================================================================
-- 0001_baseline_schema.sql
-- ============================================================================
-- 目的：把 2026-05-07 當下真實 schema 凍結為 migration baseline。
--      所有 CREATE 用 IF NOT EXISTS，對既有 DB 是 no-op；fresh DB 會建出全套表。
--      runner 對既有 DB 走 reconcile 路徑（只記錄 schema_migrations，不執行 DDL）。
--
-- 包含 9 張表 + 8 個 index：
--   主流程：events / audio_files / transcriptions / transcriptions_fts / keywords
--   即時層遺產：transcripts (app_api.py 內嵌建表，與 transcriptions 並存)
--   CER 同步：cer_history / cer_event_type_history / cer_sync_log
--
-- 注意：transcripts.use_vad/use_denoise 為 TEXT DEFAULT 0（歷史包袱，原為 INTEGER 計畫）
--      transcriptions 的 9 個延伸欄位（corrected_*、engine_hint、raw/after_*、word_confidences）
--      是 ALTER 累積結果，這裡攤平在 CREATE 中保留現況。
-- ============================================================================

-- ─── 即時層遺產：transcripts（app_api.py 內嵌） ─────────────────────────────
CREATE TABLE IF NOT EXISTS transcripts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   TEXT    NOT NULL,
    transcript   TEXT    NOT NULL,
    confidence   REAL    DEFAULT 0.0,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    stt_backend  TEXT    DEFAULT 'google',
    use_vad      TEXT    DEFAULT 0,   -- 歷史包袱：原計畫 INTEGER，現存 TEXT
    use_denoise  TEXT    DEFAULT 0    -- 同上
);
CREATE INDEX IF NOT EXISTS idx_ch ON transcripts(channel_id);
CREATE INDEX IF NOT EXISTS idx_ts ON transcripts(created_at);

-- ─── 主流程：events ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name   TEXT    NOT NULL,
    event_date   DATE,
    model_type   TEXT,
    sub_model    TEXT,
    hazard_level INTEGER DEFAULT 0,
    notes        TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─── 主流程：audio_files ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audio_files (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id          INTEGER REFERENCES events(id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    archive_path      TEXT,
    file_hash         TEXT,
    file_size         INTEGER,
    recorded_at       TIMESTAMP,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audio_event ON audio_files(event_id);

-- ─── 主流程：transcriptions（攤平所有 ALTER 欄位） ─────────────────────────
CREATE TABLE IF NOT EXISTS transcriptions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_file_id         INTEGER REFERENCES audio_files(id) ON DELETE CASCADE,
    event_id              INTEGER REFERENCES events(id) ON DELETE CASCADE,
    transcript            TEXT,
    status                TEXT DEFAULT 'success',
    error_message         TEXT,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    use_vad               INTEGER DEFAULT 0,
    use_denoise           INTEGER DEFAULT 0,
    -- 修正回饋飛輪欄位（2026-04-29 ALTER）
    corrected_transcript  TEXT,
    corrected_at          TIMESTAMP,
    engine_hint           TEXT,
    -- 後處理 audit trail 欄位（每階段獨立保存）
    raw_transcript        TEXT,
    after_car_norm        TEXT,
    after_dict            TEXT,
    after_llm             TEXT,
    -- Confidence 標記
    word_confidences      TEXT
);
CREATE INDEX IF NOT EXISTS idx_trans_audio ON transcriptions(audio_file_id);
CREATE INDEX IF NOT EXISTS idx_trans_event ON transcriptions(event_id);

-- ─── 主流程：transcriptions_fts（FTS5 trigram，中文 ≥3 字搜尋） ────────────
CREATE VIRTUAL TABLE IF NOT EXISTS transcriptions_fts USING fts5(
    transcript,
    tokenize='trigram'
);

-- ─── 主流程：keywords ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS keywords (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id          INTEGER REFERENCES events(id) ON DELETE CASCADE,
    transcription_id  INTEGER REFERENCES transcriptions(id) ON DELETE SET NULL,
    keyword           TEXT NOT NULL,
    source            TEXT DEFAULT 'manual',
    hazard_level      INTEGER DEFAULT 0,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kw_event ON keywords(event_id);

-- ─── CER 同步：cer_sync_log ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cer_sync_log (
    sync_at_iso    TEXT,
    sync_at_unix   INTEGER,
    history_rows   INTEGER,
    event_rows     INTEGER
);

-- ─── CER 同步：cer_history（給 Grafana 時序） ────────────────────────────
CREATE TABLE IF NOT EXISTS cer_history (
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
CREATE INDEX IF NOT EXISTS cer_history_engine_ts ON cer_history(engine_label, timestamp_unix);

-- ─── CER 同步：cer_event_type_history（事件類型 × 引擎 CER） ──────────────
CREATE TABLE IF NOT EXISTS cer_event_type_history (
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
CREATE INDEX IF NOT EXISTS cer_event_engine_ts ON cer_event_type_history(engine_label, event_type, timestamp_unix);
