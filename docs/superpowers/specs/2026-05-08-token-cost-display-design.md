---
title: 即時 STT 成本與使用量顯示
status: approved (design phase complete)
date: 2026-05-08
authors:
  - shawnclaw
  - Claude Opus 4.7 (1M context, brainstorming)
phase: A (STT only) → B (+LLM) deferred
spec_path: docs/superpowers/specs/2026-05-08-token-cost-display-design.md
---

# 即時 STT 成本與使用量顯示 — 設計

## 1. Goals

讓「即時辨識頁」(monitor.html, `:8000/monitor`) 顯示**正在花多少錢**，達到「適當控制 STT 模型 token 花費」的目標。

具體交付：
- 頂部 status bar：「今日 NT$ X · session NT$ Y · N/6 席位活動中」即時更新
- 點擊展開：**6 席位 × engine 拆解**（含原始使用量 audio_seconds / tokens）
- Threshold 視覺警告（≥ 80% 橘 / ≥ 100% 紅）
- 跨 tab/refresh 同步（DB 持久 + REST endpoint）
- Phase A schema 設計時預留 Phase B（LLM）位置，避免重工

**列維度說明**：UI 以**席位 (channel)** 為單位列分，**不是事件類型**（控制中心/軌道/動車門等是後處理 tag、不是 channel 標籤）。席位對應實體錄音通道與操作員座位。

## 2. Non-Goals

明確排除的事（避免 scope creep）：

- ❌ Gemini correction / 其他 LLM 的 token tracking（Phase B 才做）
- ❌ 月累計、cumulative 視圖（Phase B 之後）
- ❌ Pricing UI 線上編輯器（直接改 JSON）
- ❌ 即時匯率 API（hardcoded TWD 31.0）
- ❌ 桌面通知 / 硬煞車自動停 channel（v3+）
- ❌ per-channel alarm（v1 只系統級判斷 threshold）
- ❌ 改動 `display.html` / `capture.html`（控制室螢幕、場域端機都不該塞成本）

## 3. Decision Summary

| 決策 | 結果 | 理由 |
|---|---|---|
| Scope | Phase A→B 分階段 | 較快有產值、降低重工風險 |
| 擴展性 | 高（schema/message/UI 均預留 LLM） | 加 LLM 不用改 schema |
| 時間範圍 | session + per-day 同時顯示 | 「即時感」+「每日預算」 |
| 持久化 | SQLite usage_log 表 | per-day 跨 tab 同步需要 |
| UI 粒度 | 系統 status bar + 點擊展開 5 channel × engine | 平時不亂、需要時可深入 |
| Pricing 表 | hardcoded `config/pricing.json` 手動維護 | 最小依賴、離線可跑 |
| TWD 匯率 | hardcoded 31.0 | 估算非會計、2% 誤差可接受 |
| 警告 | 軟性視覺（橘 ≥ 80% / 紅 ≥ 100%） | 不誤動產品功能、開發成本低 |
| 「TOKEN」概念 | 改用 `usage` dict，按引擎類型自動 format | STT 沒 token 概念、強塞會誤導 |

## 3.5 Definitions

避免後段含糊，先把幾個關鍵詞釘死：

| 詞 | 意義 |
|---|---|
| **today** | 伺服器**台灣時區（TST = UTC+8）**的當天日期，午夜 00:00 翻新（用 SQLite `date(occurred_at, 'localtime')`，伺服器作業系統時區設 `Asia/Taipei`） |
| **session** | **伺服器 process 啟動以來**的累計（in-memory）。Browser refresh **不會** reset，只有 `app_api.py` 重啟才歸零。前端 UI 顯示用「session」這字面是承襲自 server side 概念。 |
| **audio_seconds** | 實際送進 STT API 的音訊秒數（**不含**前端 VAD 已切掉的靜音）。意味同樣 1 分鐘真實時間，Google STT（後端 batch + VAD）通常 < Scribe RT（前端持續送 raw 串流） |
| **ledger record 時機** | 每次 STT API 呼叫**返回後**記一筆（一次 call = 一筆 event）。失敗的 call 不記。 |
| **席位 (seat)** | UI 顯示用詞，等價於 channel / 錄音通道。Project 已用此詞於 `static/index.html:418`「席位代號」。 |
| **channel_id** | TEXT 型別（不是 INTEGER），對齊既有 `transcripts.channel_id TEXT`。實務值通常為 "1"~"6" 字串。 |
| **支援 channel 數** | 結構上最多 6 (依 `monitor.html` CSS lanes)。實際同時連線數動態，未連的席位顯示 idle。 |

## 4. Architecture

```mermaid
flowchart TD
    subgraph Server[":8000 FastAPI"]
        Scribe[model_scribe.py<br/>RT / batch] --> Ledger
        GoogleSTT[model_google_stt.py] --> Ledger
        Ledger[utils/usage_ledger.py<br/>in-memory + DB write] --> Pricing
        Pricing[utils/pricing.py<br/>load JSON, calc USD→TWD] --> Ledger
        Ledger --> DB[(SQLite<br/>usage_log table<br/>migration 0002)]
        Ledger --> WS[WebSocket emit<br/>usage_update]
        DB --> REST[/api/usage/today<br/>GET]
    end

    subgraph Client["monitor.html"]
        StatusBar["💰 今日 NT$ X · session NT$ Y [▼]"]
        Expand[Expand panel:<br/>5 channel × engine breakdown]
        StatusBar -->|click| Expand
    end

    WS -.WebSocket.-> StatusBar
    REST -.fetch on load/refresh.-> StatusBar
    Pricing -.import.-> Config[config/pricing.json<br/>rates + thresholds]
```

**Phase B（之後）疊加**：

- `model_gemini.py` 抽 `usage_metadata` → 同樣呼叫 ledger
- ledger / DB / WS message 已支援 `usage` dict 自由 schema，**Phase B 不改 schema**
- UI 在 expand panel 多顯示 LLM 那行（同樣的 row 渲染邏輯）

## 5. Data Model

新檔 `utils/usage_ledger.py`：

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class UsageEvent:
    """單一次模型使用紀錄。

    `usage` 欄位刻意設成 dict 以容納各引擎不同的計費單位：
    - STT 引擎：    {"audio_seconds": 87.3}
    - LLM 引擎（Phase B）：{"input_tokens": 8400, "output_tokens": 6100}

    UI 渲染時依 dict 鍵自動 format（audio_seconds → "87 秒"，
    input_tokens → "8.4k in"），不需改 schema 即可加新引擎類型。
    """
    channel_id: str                    # TEXT，對齊 transcripts.channel_id（"1"~"6" 字串）
    engine: str                        # "scribe_rt" | "google_stt_chirp_3" | ...
    occurred_at: datetime
    usage: dict[str, int | float]      # 高擴展性核心
    cost_usd: float
    cost_twd: float


class UsageLedger:
    """簡單事件 ledger：in-memory cache + DB 持久。

    對外 API：
        record(event)               → emit WS + write DB
        today_total_twd()           → SELECT SUM ... WHERE date(occurred_at) = today
        session_total_twd()         → from in-memory cache
        by_channel(channel_id)      → 該 channel 今日 + session 數據
    """
```

## 6. DB Schema · Migration 0002

`migrations/0002_add_usage_log.sql`：

```sql
CREATE TABLE IF NOT EXISTS usage_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   TEXT    NOT NULL,           -- 對齊 transcripts.channel_id TEXT（值如 "1"~"6"）
    engine       TEXT    NOT NULL,
    occurred_at  TIMESTAMP NOT NULL,
    usage_json   TEXT    NOT NULL,           -- JSON: {"audio_seconds": 87.3}
    cost_usd     REAL    NOT NULL,
    cost_twd     REAL    NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_usage_occurred ON usage_log(occurred_at);
CREATE INDEX IF NOT EXISTS idx_usage_ch_occurred ON usage_log(channel_id, occurred_at);
```

`0002_add_usage_log.down.sql`：

```sql
DROP INDEX IF EXISTS idx_usage_ch_occurred;
DROP INDEX IF EXISTS idx_usage_occurred;
DROP TABLE IF EXISTS usage_log;
```

> [!note] C3 機制首次實戰
> 這是 C3 引入 migration 機制後**第一次真實 schema 變更**（非 baseline reconcile）。執行：`python -m aispeech migrate up` 自動套用。

## 7. Server API

### 7.1 WebSocket message（向後相容）

新 message type，舊 client 不認得會 ignore（已驗證 `:8000/monitor` JS handler 用 switch case）：

```json
{
  "type": "usage_update",
  "channel_id": "1",
  "category": "stt",
  "engine": "google_stt_chirp_3",
  "usage": {"audio_seconds": 15.2},
  "cost_usd": 0.0061,
  "cost_twd": 0.19,
  "session_total_twd": 1.83,
  "today_total_twd": 12.40
}
```

`category` 欄位是 future-proof：Phase B 加 `"llm"`，UI 用 category 分組顯示。

### 7.2 REST endpoint

`GET /api/usage/today`：

```json
{
  "today_total_twd": 12.40,
  "session_total_twd": 3.20,
  "by_channel": [
    {
      "channel_id": "1",
      "today_twd": 18.20,
      "session_twd": 3.10,
      "is_active": true,
      "by_engine": [
        {"engine": "scribe_rt",          "today_twd": 0.81, "session_twd": 0.20, "usage": {"audio_seconds": 237.0}},
        {"engine": "google_stt_chirp_3", "today_twd": 2.38, "session_twd": 0.40, "usage": {"audio_seconds": 192.0}}
      ]
    }
    /* ... 最多 6 筆，未連線的席位 is_active=false 且 by_engine: [] */
  ],
  "active_channel_count": 5,
  "max_channel_slots": 6,
  "alerts": {"daily_pct": 12.4, "level": "ok"}  // "ok" | "warning" | "critical"（對應 pricing.alerts 兩個 pct 閾值）
}
```

用途：
- 開頁/刷頁時的初始化（避免要等下次 STT result 才看到數字）
- 跨 tab 同步（每 tab 各自 fetch，無 broadcast）

## 8. Pricing 設定 · `config/pricing.json`

```json
{
  "_meta": {
    "last_updated": "2026-05-08",
    "source": "ElevenLabs / Google Cloud 公開定價（請定期 review）",
    "next_review_due": "2026-08-08"
  },
  "usd_to_twd": 31.0,
  "alerts": {
    "daily_warning_pct": 80,
    "daily_critical_pct": 100,
    "daily_budget_twd": 100
  },
  "engines": {
    "scribe_rt": {
      "type": "stt",
      "unit": "audio_seconds",
      "usd_per_unit": 0.000111,
      "_note": "$0.0067/min ÷ 60 ≈ $6.7/k min（請以實際 ElevenLabs 帳單驗證校準）"
    },
    "google_stt_chirp_3": {
      "type": "stt",
      "unit": "audio_seconds",
      "usd_per_unit": 0.000400,
      "_note": "$0.024/min ÷ 60（請以 GCP 帳單驗證）"
    }
  }
}
```

> [!warning] **單價需要校準**
> JSON 裡的 `usd_per_unit` 是公開資料估值。實作完成第一週應對照 ElevenLabs / GCP 帳單校準後 commit 修正。

Phase B 加 LLM 條目時 `engines.<name>.unit` 改 `"input_tokens"` / `"output_tokens"`，可同 model 複數 unit。

## 9. UI 行為 · `monitor.html`

### 9.1 預設視圖（status bar）

```
┌──────────────────────────────────────────────────────────────────┐
│  💰 今日 NT$ 24.30 · session NT$ 5.40 · 5/6 席位活動中  [▼ 展開] │
└──────────────────────────────────────────────────────────────────┘
```

放在 monitor.html 頂部、「6 lane grid」上方。`5/6 席位活動中` 由 REST 的 `active_channel_count / max_channel_slots` 計算。

### 9.2 展開視圖（席位導向）

```
┌──────────────────────────────────────────────────────────────────┐
│  💰 今日 NT$ 47.20 · session NT$ 8.40                  [▲ 收起] │
├──────────────────────────────────────────────────────────────────┤
│  席位 1 · ● live · dual                                          │
│    今日 NT$ 18.20 · session NT$ 3.10                            │
│    └ scribe_rt           237 秒      NT$ 0.81                   │
│    └ google_stt          192 秒      NT$ 2.38                   │
│                                                                   │
│  席位 2 · ● live · dual                                          │
│    今日 NT$ 11.30 · session NT$ 1.80                            │
│    └ scribe_rt           142 秒      NT$ 0.49                   │
│    └ google_stt          115 秒      NT$ 1.43                   │
│                                                                   │
│  席位 3 · ● live · dual + LLM    [⚠️ warning 個別席位也套同色規則] │
│    今日 NT$ 9.40 · session NT$ 2.20                             │
│    └ google_stt           98 秒      NT$ 1.21                   │
│                                                                   │
│  席位 4 · ● live · scribe_rt                                     │
│    今日 NT$ 4.80 · session NT$ 0.90                             │
│    └ scribe_rt            63 秒      NT$ 0.22                   │
│                                                                   │
│  席位 5 · ● live · google_stream                                 │
│    今日 NT$ 3.50 · session NT$ 0.40                             │
│    └ google_stt           88 秒      NT$ 1.09                   │
│                                                                   │
│  席位 6 · ○ idle · 無 WS 連線                                    │
│    —                                                             │
└──────────────────────────────────────────────────────────────────┘
```

**列維度釘死**：

- 一列 = 一個席位 (channel_id) = 一個錄音通道 = 一個操作員座位
- **不**用「事件類型」（控制中心 / 軌道 / 動車門）為列——那是後處理 tag 不是 channel
- 6 列固定佔位（`monitor.html` CSS lanes）；未連線者顯示 idle (○)、不隱藏，方便對應實體座位佈局
- 席位個別 today/session 數字也套同套 ok/warning/critical 色彩規則（席位個別 budget 留 v2）
- 視覺呈現見 [mockup `/tmp/cost-display-mockup.html`](/tmp/cost-display-mockup.html)（snip approved 2026-05-08）

### 9.3 色彩規則（status bar 「今日」數字）

| level | 條件 | 色 | icon |
|---|---|---|---|
| `ok` | `today_pct < daily_warning_pct` (預設 80%) | 正常（白/灰） | 💰 |
| `warning` | `daily_warning_pct ≤ today_pct < daily_critical_pct` (預設 80~100%) | 橘 | ⚠️ |
| `critical` | `today_pct ≥ daily_critical_pct` (預設 100%) | 紅 | 🚨 |

```
today_pct = today_total_twd / pricing.alerts.daily_budget_twd × 100
```

**邊界 case**：若 `daily_budget_twd <= 0`，alerts 全程禁用（level 永遠 `ok`），UI 不顯示 warning/critical 色彩。

### 9.4 更新頻率

- WebSocket `usage_update` message 來一次更新一次（即時）
- Client 端 debounce 100ms 避免 jitter
- 每次 page load / refresh 先 `fetch /api/usage/today` 初始化
- 跨 tab：因為 today 數據共用 DB，REST endpoint 是真相源

### 9.5 互動

- 點 `[▼ 展開]` → 展開區動畫展開（CSS transition 200ms）
- 點 `[▲ 收起]` → 收起
- 收起狀態存 localStorage（記得使用者偏好）

## 10. Test 計畫

5 新 test 檔案，目標 ≥ 10 tests：

| 檔 | 數量 | 內容 |
|---|---|---|
| `tests/test_pricing.py` | 4 | load JSON / calc audio_seconds × rate / TWD 轉換 / 單位未知時 raise |
| `tests/test_usage_ledger.py` | 6 | record / today_total / session_total / by_channel / threshold pct / 空 ledger |
| `tests/test_db_manager.py` | +2 | usage_log INSERT / 查 today（補進現有檔） |
| `tests/test_migrate.py` | +1 | 0002 migration up + down round-trip |

完工後 pytest 應從現有 56 跑到 **≥ 65 tests**。

## 11. 實作步驟（Phase A）

| # | 步驟 | 估時 |
|---|---|---|
| 1 | `migrations/0002_add_usage_log.sql` + `.down.sql` + 跑 `aispeech migrate up` | 30 min |
| 2 | `config/pricing.json` + `utils/pricing.py`（load + calc 函式） | 1 hr |
| 3 | `utils/usage_ledger.py`（in-memory + DB write + threshold 計算） | 1.5 hr |
| 4 | `model_scribe.py` + `model_google_stt.py` 在 transcribe 結果加 `audio_seconds` 欄位 | 30 min |
| 5 | `app_api.py` 加 `usage_update` 推 + `/api/usage/today` GET | 1 hr |
| 6 | `monitor.html` UI（status bar + expand + WS handler + threshold color + localStorage） | 1.5 hr |
| 7 | 寫 ~10 tests + 跑 `pytest` 全綠 | 1 hr |
| 8 | README + devlog（記設計決策 + lessons）+ commit + push + 看 CI 綠 | 30 min |

**Total Phase A：~7.5 hr**

## 12. 風險與 Mitigation

| # | 風險 | 嚴重 | Mitigation |
|---|---|---|---|
| R1 | Pricing 估錯 → UI 數字偏誤 | 中 | `_note` 寫來源 + `next_review_due` 提醒 + 上線後一週對帳 |
| R2 | WebSocket 訊息高頻 → 前端 jitter | 低 | client 100ms debounce |
| R3 | DB 寫入延遲影響 STT 路徑 | 中 | usage_ledger.record 改 `asyncio.create_task()` fire-and-forget |
| R4 | 多 channel 同時跑 → ledger race | 低 | SQLite WAL（已開）+ 計總用 SUM SQL |
| R5 | Pricing JSON 載入失敗 → 系統啟動失敗 | 中 | utils/pricing.py 加 try/except，失敗 fallback 到內建空 dict（cost = 0），log warn 不阻擋 STT 服務 |
| R6 | TWD 31.0 偏離真匯率 1-2% | 低 | 接受；季度 review pricing 時順便改 |

## 13. Open Questions / TBD

- **Q1**：Phase A 完成後 1 週看實際數據——STT 占總成本比例如何？> 50% 才值得做 Phase B；< 20% 表示 LLM correction 才是主成本，Phase B 反而更急
- **Q2**：localStorage 存的「展開狀態」要不要跨 channel 各自記？v1 採用全局單一 flag
- **Q3**：CER 評測（batch）時也經過很多 STT 呼叫，要不要算進「成本」？v1 只算 monitor 路徑（即時），batch 不算（避免歷史評測炸數字）
- **Q4**：如果一個 channel 持續跑 8 小時不停，session_total 會不會數字膨脹到醜？v1 顯示用 NT$ 1234.5 格式；超過 NT$ 10k 顯示 "10.2k"

## 14. Phase B（之後）需要做什麼

Spec 不深入但記錄方向：

- `model_gemini.py` 抽 `response.usage_metadata.prompt_token_count` / `candidates_token_count`
- `pricing.json` 加 LLM 條目（input/output 各 unit）
- UI expand panel 多渲染 LLM 那行（同一個 renderer 認 dict 鍵）
- 加 `category="llm"` 的 WS message 路徑
- Test 加 `test_llm_pricing.py` ~5 tests

預估 Phase B：~10 hr（依 LLM 呼叫點分散程度）。

## 15. Revision History

| Date | Change | Author |
|---|---|---|
| 2026-05-08 | Initial design after 5-question brainstorming | shawnclaw + Claude |
| 2026-05-08 | v2: 列維度修正為「席位 (channel)」非事件類型；channel_id 改 TEXT 對齊既有 schema；最大 6 槽；mockup snip-approved | shawnclaw + Claude |
