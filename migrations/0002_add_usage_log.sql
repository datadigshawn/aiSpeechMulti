-- ============================================================================
-- 0002_add_usage_log.sql
-- ============================================================================
-- 用途：記錄每次 STT (Phase A) / LLM (Phase B) API 呼叫的使用量與成本。
-- 新增表：usage_log + 2 個 index。對既有 5 張表零影響。
--
-- 欄位設計：
--   channel_id: TEXT (對齊 transcripts.channel_id 類型，值如 "1"~"6")
--   engine: TEXT ("scribe_rt" | "google_stt_chirp_3" | "gemini-2.5-flash" ...)
--   occurred_at: TIMESTAMP (API 呼叫發生時間)
--   usage_json: TEXT (JSON dict: STT={"audio_seconds": 87.3}, LLM={"input_tokens": ...})
--   cost_usd / cost_twd: REAL (成本數字)
--
-- Index 策略：
--   idx_usage_occurred: 時間序列查詢（儀表板 top N）
--   idx_usage_ch_occurred: 複合索引（特定 channel 時間範圍）
-- ============================================================================

CREATE TABLE IF NOT EXISTS usage_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   TEXT    NOT NULL,           -- 對齊 transcripts.channel_id TEXT（值如 "1"~"6"）
    engine       TEXT    NOT NULL,           -- "scribe_rt" | "google_stt_chirp_3" | (Phase B) "gemini-2.5-flash" ...
    occurred_at  TIMESTAMP NOT NULL,
    usage_json   TEXT    NOT NULL,           -- JSON dict: STT={"audio_seconds": 87.3}, LLM={"input_tokens": ...}
    cost_usd     REAL    NOT NULL,
    cost_twd     REAL    NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_usage_occurred    ON usage_log(occurred_at);
CREATE INDEX IF NOT EXISTS idx_usage_ch_occurred ON usage_log(channel_id, occurred_at);
