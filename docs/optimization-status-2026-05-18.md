---
title: aiSpeechMulti 優化盤點與待辦對齊 2026-05-18
created: 2026-05-18
reviewer: Claude Opus 4.7 (1M context)
methodology: 整體資料夾深度檢視 + Obsidian 筆記交叉比對 + Code Review 校正
related:
  - docs/architecture-review-2026-05-07.md
  - docs/INTERFACES.md
status: snapshot
---

# 🔍 aiSpeechMulti 優化盤點與待辦對齊（2026-05-18）

> 同步位置：obsidian `_decisions/2026-05-18 優化盤點對齊筆記.md`（含 wikilink）。

## TL;DR

- **基線**：4 Critical 全清 ✅ · Phase A 即時成本顯示已上線 ✅ · 85 tests · CI 綠 · production live
- **誤判校正**：先前 stateless Code Review 列為「待辦」的 H3/M3/M4/M8/L1/L3/L4 多項實已完成或排定
- **真實主線**：P0 = GT 標註解鎖飛輪（不缺音檔缺人工），P1 = 架構審視 5 條 Important，P2 = 觀察 1 週決定 Phase B
- **核心結論**：當前瓶頸不是技術，是飛輪空轉

---

## 1 · 當前基線（已完成 · 不要重做）

引用 `_decisions/2026-05-10 4 日工作總結.md` + `_decisions/架構審視 2026-05-07.md`：

### 1.1 架構審視 4 Critical 全清（2026-05-07~08）
- **C1 安全**：撤換 ElevenLabs key + 修 `.env` 4 處錯誤路徑
- **C2 SQL 審計**：5 種 grep 全掃，0 真風險（原報告誤判已降 FYI）
- **C3 schema migration**：`migrations/` + `utils/migrate.py` + `aispeech migrate` CLI + 啟動 auto-apply
- **C4 pytest + CI**：0→56 tests · GitHub Actions Ubuntu/Py3.12 · 44 秒跑完

### 1.2 Phase A 即時 STT 成本顯示（2026-05-10）
- `static/monitor.html` 💰 status bar + 6 席位 × engine 展開
- `usage_log` 表（schema 已預留 LLM unit）
- `utils/usage_ledger.py`（in-memory + DB 雙寫，含 fixed-hour TZ regression test）
- `config/pricing.json` + `utils/pricing.py` + `utils/audio_duration.py`
- 56→85 tests · 14 commits

### 1.3 2026-05-06 健檢三波（同日全清）
- vocab CSV section 註解 bug 修復（`utils/vocab_csv.py` helper）
- 前處理參數 expose + A/B 框架（`scripts/preproc_ab.py` + 6 combo）
- confidence-based 引擎 fallback（`utils/confidence_fallback.py` + REST `/api/confidence`）
- sync-cer 自動 hook + Grafana GT 進度 panel + export-feedback Popen 排程
- 前端 `static/index.html` capture 重構（WS 指數退讓重連 + a11y 22 條）
- 儲存重複盤確認（結論：不刪）

### 1.4 介面整併 + Design / Theme（2026-05-04~05）
- `app_dashboard.py` 12 頁拆三層；統一 CLI `python -m aispeech`
- 7 commits design system + 1 commit theme switcher（dark-cool / dark-warm）

---

## 2 · 先前 Code Review 報告的誤判校正

| 編號 | 原誤判 | 真實狀態 |
|---|---|---|
| H3 | `logs/` 1299 個無 rotation | RotatingFileHandler **已設**（utils/logger.py:82,98），實際是否落實值得小驗證，非急迫 |
| M3 | cer_history 手動同步 | **已完成** sync-cer hook（2026-05-06）；FTS5 仍應用層同步（D2）但 Streamlit threading 限制使然 |
| M4 | `.env` vs `.env.example` drift | **已完成** C1 安全修復（2026-05-07）|
| M8 | `.coverage` 未進 `.gitignore` | **已完成** C4 隨手加 |
| L1 | `app_dashboard.py` 仍在 repo | **排定 2026-06-04 後刪**（過渡期保留） |
| L3 | migration startup hook 未呼叫 | **已完成** `DBManager.__init__` 已掛（C3） |
| L4 | WORKLOG 散亂 | **已完成** Sg2 已搬到 `_devlog/` |

校正原則：當代碼狀態與 stateless Code Review 結論衝突時，**以筆記為真**（筆記是用戶意圖的累積，Code Review 是當下 snapshot）。

---

## 3 · 真實待辦清單

### P0 — CER 主線（用戶最高優先：解鎖資料飛輪）

> 出處：`_devlog/2026-05-06 三項健檢 — CER 主線 GT 缺口 Code Health.md` + `_devlog/2026-05-06 音檔存量盤點 — 不缺音檔缺人工.md`
> **核心結論：瓶頸是飛輪空轉，不是技術問題**

| 項 | 工時 | 備註 |
|---|---|---|
| P0-1 遷移 Test_ASR 7 段進 manifest（63→70 段）| 0.5h | 7 段已有人工 GT（emergency 場景） |
| P0-2 寫 ASR 草稿 import 腳本（parse `_彙整_*.txt` × 3）| 1h | 118 wav 有 ASR 草稿可半自動 |
| P0-3 dashboard 加 batch GT import 介面 | 4-8h | 評估後決定，或沿用現有 `✏️ 修正` UI |
| P0-4 每日 30 分鐘批次標註 → 188 段 | ~10h 總 | 1-2 週單人完成，標序：emergency→control→door→track |
| P0-5 冷啟動修正飛輪：手工修 5-10 段 CER>40% control/door | 1-2h | 可並行 |
| P0-6 Val 重均衡：6→10 段（補 4 control）| 1h | control val 目前 2 段不可信 |
| P0-7 修 DB 內 229 筆 `archive_path` stale 路徑 ★ 高 ROI | 5-10min | 立即可做 |

### P1 — 架構審視 Important（5 條未完成）

> 出處：`docs/architecture-review-2026-05-07.md` §7。**等 P0 飛輪轉起來再輪動**。

| # | 動作 | 預估 |
|---|---|---|
| I1 | 定義 `STTEngine` Protocol + `TranscriptionResult` dataclass，6 個 `scripts/models/model_*.py` 改繼承 | 3d |
| I2 | 拆 `app_lab.py` 4048 LOC god-file → Streamlit `pages/` 目錄、抽 design-system 注入 | 4d |
| I3 | 拆 `app_api.py` 1723 LOC god-file → FastAPI `APIRouter`（stream / vocabulary / usage / health） | 3d |
| I5 | GCP project ID 硬編碼 8 處 → 抽到 `utils/config.py`，缺失時 fail-fast | 2d |
| I6 | `離線模式規劃/` fork → merge 回主程式 或 標 prototype（`python -m aispeech serve offline`） | 2d |

### P2 — Phase B 觀察期 + Pricing 校準

- **跑 1 週 usage_log**：`sqlite3 data/aiSpeechMulti.db "SELECT engine, SUM(cost_twd) twd, COUNT(*) n FROM usage_log GROUP BY engine"`
  - LLM 佔比 >30% → Phase B 急（~10h，LLM token tracking）
  - STT 為主 → Phase A 已夠
- **2026-08-08 `config/pricing.json` `next_review_due`** → 對 ElevenLabs / GCP 帳單校準 `usd_per_unit`
- **Phase B v2 已知限制**：
  - `google_stream` 模式不入 ledger（`stream_recognize` 無 audio_seconds）
  - `_session_events` list 無上限 → 每週重啟
  - LLM (Gemini correction) 尚未追蹤

### P3 — CER Phase 4 收尾 + Phase 5 正式 fine-tune

當前最佳 **28.12%**，距 20% 目標還 8.12pp。

**Phase 4 收尾**：
- 錯字回饋累積 100+（用 dashboard `✏️ 修正`）
- 語境感知後處理擴充：contextual 規則 14 → 30+ 條（仍可加 -1~2pp）

**Phase 5 正式**（GT ≥150 段才啟動；B1-B5 + B7 已完工）：
- B6 正式訓練 4-8h × 多輪
- 超參再搜索（lr 1.5e-3 / batch 8 / warmup 加長 / 試解凍 encoder 最後 2 層）
- multi-seed stratified（3-5 seeds 取平均 checkpoint）
- 雙 fine-tuned ensemble PoC（SenseVoice + Whisper-medium 各自 LoRA + confidence-weighted fusion）

### P4 — Design / Theme follow-up

| 類別 | 待辦 |
|---|---|
| Design System | axe-core 自動掃描整合到 CI；Lab `st.metric`→`.stat` 元件（4 處）；WCAG AA 對比度全面量測；logo 極簡 SVG |
| Capture 前端 | AudioWorklet 升級；全面 `.btn` / `.input` class 改造 |
| Theme Switcher | 第三套主題；light theme 變體；Grafana 主題切換；plotly chart 跟主題；`prefers-color-scheme` 自動偵測 |
| 清理 | 2026-06-04 後刪 deprecated `app_dashboard.py`；同期移除 Lab `cer_trend` 本地 plotly；30 天後刪 `RadioRecognition_UI/` |

### P5 — Suggestions / Cleanup（架構審視 Sg + D）

- **Sg1** 移除死檔 `data/aiSpeech.db`（60KB）
- **Sg3** `requirements.txt` 拿掉 `psycopg2-binary` + `sqlalchemy`（未用）
- **Sg5** 統一 api_keys 入口
- **Sg6** `gemini-3.1-pro-preview` 標 deprecated
- **D3** dual 模式 Scribe partial 不入 DB（FYI）
- **D4** post_process audit trail 加進 DB 欄位

### P6 — 待研究 / 待確認（長期）

- SQLite vs PostgreSQL（依資料量決定，目前 229 筆 OK）
- Confidence-based 引擎切換（前置 #5 已完成，可動）
- Speaker diarization：區分 OCC / 站長 / 司機員 / 維修
- 句子對齊 + 段落級 LLM 修正（#8）
- Whisper + Prompt Chaining 局部重跑（#13）
- 領域專屬 n-gram LM 加權（#14，需 100+ GT）

---

## 4 · 建議下一步

依用戶筆記的優先順序：

1. **P0-1 + P0-2 + P0-7**（合計 ~2h）— 三個高 ROI 小工，GT 63→70 + 自動 import + 修 stale path
2. **跑 1 週看 usage_log** — 純等數據，不需動工
3. **每日 30 分鐘標註** — 解鎖 Phase 5 B6 正式訓練前置

I1~I6 全是「nice to have」，不阻塞主線。

---

## 5 · 方法論與資料來源

- **比對**：`/Users/apple/Projects/projectArea/aiSpeechMulti/` 全資料夾 × `2nd brain/20_Programming/Projects/aiSpeechMulti/` 全文件
- **權威**：`00_Project MOC.md` + `_decisions/架構審視 2026-05-07.md` + `_decisions/2026-05-10 4 日工作總結.md` + `_todos/TODO.md`
- **校正原則**：代碼 snapshot 與筆記衝突時以筆記為真；新發現的「真問題」需附最新 grep / file 證據

---

*盤點：2026-05-18 · Claude Opus 4.7 (1M context)*
