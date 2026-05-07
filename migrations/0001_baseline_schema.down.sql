-- ============================================================================
-- 0001_baseline_schema.down.sql
-- ============================================================================
-- 倒退：DROP 全部 baseline 表 + index。
--
-- ⚠️ 警告：對既有資料庫執行此 down 會清空所有 transcription / event / cer 資料！
--      正常情況下 baseline 不應被 down——除非整個 DB 要重建。
--      runner 仍提供能力，但實務上建議先備份再執行。
--
-- DROP 順序：先 drop child（FK referencing parent），最後 drop parent。
-- ============================================================================

-- CER 同步表（無 FK）
DROP INDEX IF EXISTS cer_event_engine_ts;
DROP TABLE IF EXISTS cer_event_type_history;

DROP INDEX IF EXISTS cer_history_engine_ts;
DROP TABLE IF EXISTS cer_history;

DROP TABLE IF EXISTS cer_sync_log;

-- 主流程：keywords 先 drop（refs events + transcriptions）
DROP INDEX IF EXISTS idx_kw_event;
DROP TABLE IF EXISTS keywords;

-- transcriptions_fts 與 transcriptions 表獨立（共享 rowid 空間，無 FK）
DROP TABLE IF EXISTS transcriptions_fts;

-- transcriptions（refs events + audio_files）
DROP INDEX IF EXISTS idx_trans_event;
DROP INDEX IF EXISTS idx_trans_audio;
DROP TABLE IF EXISTS transcriptions;

-- audio_files（refs events）
DROP INDEX IF EXISTS idx_audio_event;
DROP TABLE IF EXISTS audio_files;

-- events（無 FK）
DROP TABLE IF EXISTS events;

-- 即時層遺產：transcripts（無 FK）
DROP INDEX IF EXISTS idx_ts;
DROP INDEX IF EXISTS idx_ch;
DROP TABLE IF EXISTS transcripts;
