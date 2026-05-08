-- ============================================================================
-- 0002_add_usage_log.down.sql
-- ============================================================================
-- 倒退：DROP usage_log + 2 indexes。
-- ⚠️ 對既有資料庫執行此 down 會清空所有使用量歷史。
-- ============================================================================

DROP INDEX IF EXISTS idx_usage_ch_occurred;
DROP INDEX IF EXISTS idx_usage_occurred;
DROP TABLE IF EXISTS usage_log;
