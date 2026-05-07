# aiSpeechMulti Schema Migrations

> 純 SQL + numbered file 機制。零新依賴，runner 在 [`utils/migrate.py`](../utils/migrate.py)。

---

## 一、為什麼有這個目錄

之前 schema 變更靠 `db_manager.py::_init_schema()` 內嵌 DDL + `try: ALTER TABLE ... except: pass` 的 idempotent ALTER。優點是「能跑就好」，缺點是：

- schema 演化軌跡只在 git history 散落的 commit 裡
- 同事 / 未來自己 clone 後跑不出當前 schema（必須跑全部歷史 ALTER 才對齊）
- 沒法倒退某個欄位
- 沒法在 prod 部署前 review 即將套的 SQL

引入 numbered SQL migration 後：

- 每次 schema 變更 = 一個 .sql + .down.sql 檔
- 套用紀錄存在 `schema_migrations` 表，含 checksum 防 drift
- 完整 audit trail：誰套了什麼、何時套
- 可倒退（dev/staging 安全）
- 可 dry-run（看 SQL 不執行）
- 自動 backup DB

---

## 二、檔案結構

```
migrations/
├── README.md                          ← 本文件
├── 0001_baseline_schema.sql           ← 凍結 2026-05-07 當下真實 schema
├── 0001_baseline_schema.down.sql      ← 反向 DROP
├── 0002_<next_change>.sql             ← 你的下一個 migration
├── 0002_<next_change>.down.sql        ← 對應倒退
└── ...
```

**命名規則**：

- `NNNN_<snake_case_name>.sql`
- `NNNN` 4 位數連續整數（0001, 0002, 0003...）
- `<snake_case_name>` 描述變更（例：`add_word_confidences`、`drop_legacy_transcripts`）
- 每個 up 配一個 `<同名>.down.sql`（**強烈建議**——否則 down 命令會拒絕該 migration）

---

## 三、寫一個新 migration（5 分鐘）

### Step 1 · 想清楚變更

| 類型 | 範例 |
|---|---|
| 加欄位 | `ALTER TABLE transcriptions ADD COLUMN priority INTEGER DEFAULT 0;` |
| 加表 | `CREATE TABLE feedback ( ... );` |
| 加 index | `CREATE INDEX idx_xxx ON ...;` |
| 改欄位（SQLite 限制） | `CREATE TABLE _new + INSERT SELECT + DROP old + ALTER RENAME`（10 行 SQL） |
| 資料 backfill | `UPDATE transcriptions SET ... WHERE ...;` |

### Step 2 · 建檔

下個編號 = `ls migrations/ | grep -E "^[0-9]" | tail -1` +1。例：

```bash
NEW_VER=0002
cat > migrations/${NEW_VER}_add_priority.sql <<'EOF'
ALTER TABLE transcriptions ADD COLUMN priority INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_trans_priority ON transcriptions(priority);
EOF

cat > migrations/${NEW_VER}_add_priority.down.sql <<'EOF'
DROP INDEX IF EXISTS idx_trans_priority;
-- SQLite 3.35+ 才支援 DROP COLUMN，舊版需重建表：
ALTER TABLE transcriptions DROP COLUMN priority;
EOF
```

### Step 3 · 本機驗證

```bash
# 看有什麼 pending
python -m utils.migrate status

# Dry run（印 SQL 不執行）
python -m utils.migrate up --dry-run

# 真的套用（會自動 backup DB）
python -m utils.migrate up

# 馬上 verify schema
sqlite3 data/aiSpeechMulti.db "PRAGMA table_info(transcriptions);"

# 不行就倒退
python -m utils.migrate down 0001
```

### Step 4 · Commit

```bash
git add migrations/0002_add_priority.sql migrations/0002_add_priority.down.sql
git commit -m "feat(db): add transcriptions.priority + index"
```

---

## 四、紀律（不能違反）

| 規則 | 為什麼 |
|---|---|
| **已套用的 migration 不可修改** | runner 用 SHA256 checksum 偵測 drift；改了就會在 status 顯示 `⚠ DRIFT` |
| **一個 migration 一個邏輯目的** | 易 review、易倒退、易理解 |
| **編號連續、不可跳號** | runner 按字串排序套用，跳號雖能跑但讀者會困惑 |
| **不可刪除歷史 migration 檔案** | clone repo 的人需要全部跑過才能對齊 schema |
| **重大變更（DROP TABLE/COLUMN）要備份提示** | 直接寫在 .sql 開頭註解 |
| **不能在 migration 裡呼叫 Python 邏輯** | 純 SQL，避免「migration 跑不過因為某個 module 沒裝」 |

---

## 五、執行的時機

### 自動（推薦）

`utils/db_manager.py::_init_schema()` 啟動時呼叫 `migrate.run_pending()`，**任何打開 DB 的入口**（API server / Streamlit Lab / CLI script）都會自動套用 pending migration。

### 手動

```bash
python -m utils.migrate status
python -m utils.migrate up
python -m utils.migrate up 0003       # 套到 0003 為止
python -m utils.migrate down 0001     # 倒退到 0001（0001 自己保留）
python -m utils.migrate <cmd> --db /path/to/other.db    # 對其他 DB
python -m utils.migrate <cmd> --dry-run                 # 印 SQL 不執行
```

---

## 六、Baseline 0001 的特殊處理

`0001_baseline_schema.sql` 是**現況快照**，不是「全新 install」。

- 對**既有 DB**（已有 events / transcriptions 等表）：runner 走 reconcile 路徑——只 INSERT 一行紀錄到 `schema_migrations`，**不執行任何 DDL**，避免破壞現有資料
- 對**全新 DB**（fresh install）：runner 正常執行 0001 的 `CREATE IF NOT EXISTS` 全套表

判斷依據：`SELECT 1 FROM sqlite_master WHERE name = 'transcriptions'`。存在 = 既有 DB，不存在 = fresh。

---

## 七、Backup 機制

`up` 和 `down` 在執行前自動 backup：

```
data/aiSpeechMulti.db.bak.20260507_163542
```

格式：`<原檔名>.bak.<YYYYMMDD_HHMMSS>`。**不會自動清理**——磁碟空間自己留意，定期 `find data/ -name "*.bak.*" -mtime +30 -delete`。

---

## 八、tracking table 結構

```sql
CREATE TABLE schema_migrations (
    version    TEXT PRIMARY KEY,    -- "0001"
    name       TEXT NOT NULL,       -- "baseline_schema"
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    checksum   TEXT NOT NULL        -- SHA256 of .sql file
);
```

可以直接 query 看歷史：

```bash
sqlite3 data/aiSpeechMulti.db "SELECT * FROM schema_migrations ORDER BY version"
```

---

## 九、CER 同步表的歸屬

`cer_history` / `cer_event_type_history` / `cer_sync_log` 三張表現由 [`scripts/sync_cer_to_sqlite.py`](../scripts/sync_cer_to_sqlite.py) 內嵌 DDL 創建。**0001 baseline 已包含這三張**（為了 reconcile 完整性），但實際 schema source-of-truth 還在那支 script 裡。

未來計畫：
- 若 cer 表 schema 要變，**統一寫成 migration**，不再改 sync_cer_to_sqlite.py 內嵌 DDL
- 等成熟後可以把 sync_cer_to_sqlite.py 的 DDL 完全刪掉

---

## 十、SQLite 限制提醒

| 想做 | SQLite 支援？ |
|---|---|
| ALTER TABLE ADD COLUMN | ✓ |
| ALTER TABLE RENAME COLUMN | ✓ (3.25+) |
| ALTER TABLE DROP COLUMN | ✓ (3.35+，舊版需重建表) |
| 改欄位 type / 改 default / 加 NOT NULL | ✗ 必須重建表（CREATE _new + INSERT SELECT + DROP + RENAME）|
| ALTER TABLE 帶參數 | ✗ 只能 f-string 拼 SQL（identifier 不能參數化） |

[官方 ALTER TABLE 文檔](https://www.sqlite.org/lang_altertable.html)

---

*本目錄機制設計於 2026-05-07，搭配 [docs/architecture-review-2026-05-07.md](../docs/architecture-review-2026-05-07.md) 的 C3 行動項。*
