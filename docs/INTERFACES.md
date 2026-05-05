# aiSpeechMulti 介面總表

> **版本**：2026-05-05（基於 2026-05-04 介面整併 P0~P3 + 方案 A/C + P2 完成後的狀態）
> **架構圖**：[architecture.html](./architecture.html)（互動式 Mermaid + 可點擊跳轉）
> **規劃書**：Obsidian `_decisions/介面整併規劃 v1.md`
> **實作 devlog**：Obsidian `_devlog/2026-05-04 介面整併 P0-P3 完成.md`

---

## 三層架構

| 層級 | 介面 | 入口 | 使用者 | 更新頻率 |
|---|---|---|---|---|
| 即時層 | FastAPI + 3 個靜態 HTML | `:8000` | 場域 / 操作員 / 控制室 | 毫秒級 WebSocket |
| 研究層 | Streamlit Lab | `:8501` | 開發 / 評估者 | 互動觸發 |
| 運維層 | Grafana | `:3000` | SRE / 開發 | 分鐘級輪詢 |
| (跨層) | 統一 CLI | `python -m aispeech` | 開發 / 自動化 | 一次性 |

---

## 一、即時層（FastAPI + 靜態 HTML）

由 `python app_api.py`（或 `python -m aispeech serve api`）啟動，全部走 `:8000`。

| 路徑 | 檔案 | 角色 | 用途 |
|---|---|---|---|
| `http://localhost:8000/` | [static/landing.html](../static/landing.html) | 所有人 | 入口 landing：5 個服務徽章 + 跳轉 |
| `http://localhost:8000/capture` | [static/index.html](../static/index.html) | 場域端機 | 5 路麥克風擷取，推 PCM 上 WebSocket |
| `http://localhost:8000/monitor` | [static/monitor.html](../static/monitor.html) | 操作員 | 5 路即時辨識監控（partial / committed） |
| `http://localhost:8000/display` | [static/display.html](../static/display.html) | 控制室大螢幕 | 純文字大字無干擾顯示 |

### Landing 頁特性

- 顯示 5 個入口卡（即時擷取 / 五路監控 / 大螢幕投放 / Lab / Grafana）
- 每個入口附 ● 健康徽章（綠/紅/灰）
- 10 秒輪詢 `/api/landing/status` 自動更新狀態
- 純 vanilla JS + CSS，零依賴

---

## 二、研究工作台 Lab（Streamlit）

由 `streamlit run app_lab.py`（或 `python -m aispeech serve lab`）啟動，走 `:8501`。

**共 9 頁 + 1 個內部執行階段**。

| 頁面 key | 中文標題 | render 函式 | 用途 |
|---|---|---|---|
| `speech` | 🎙️ 批次辨識（**預設首頁**） | `render_speech_page()` | 上傳音檔，選引擎，批次辨識 |
| `running` | (內部執行階段) | `render_running_page()` | speech 點「開始辨識」後跳這頁跑推論 |
| `offline_monitor` | 🔒 離線監看 | `render_offline_monitor_page()` | 監控資料夾，自動對新音檔離線辨識 |
| `evaluation` | 📊 準確率評測 | `render_evaluation_page()` | 黃金語料 CER 評測（含 fine-tuned 引擎） |
| `cer_trend` | 📈 CER 趨勢 | `render_cer_trend_page()` | CER 趨勢圖（**已標記遷移到 Grafana**） |
| `correction_history` | ✏️ 修正歷程 | `render_correction_history_page()` | 錯字回饋飛輪可視化 |
| `management` | 🗂️ 事件管理 | `render_management_page()` | 歷史事件瀏覽、危害等級、備注 |
| `search` | 🔍 全文搜尋 | `render_search_page()` | FTS5 / LIKE 跨事件搜尋 |
| `stats` | 📋 統計報表 | `render_stats_page()` | 趨勢圖、模型分布、危害分布 |
| `vocabulary` | 📚 詞彙表 | `render_vocabulary_page()` | master_vocabulary.csv 線上編輯 |

### Lab 共用元件（[app_lab.py](../app_lab.py)）

- `render_lab_sidebar()` — 統一側邊欄（9 頁 radio 導航 + 跨介面連結 + Backend URL 設定）
- `init_session_state()` — Session state 初始化（預設 `page = "speech"`）
- `setup_credentials()` — 認證設定

### Lab 側邊欄「🔗 其他介面」連結

- 🎙️ 即時擷取 → `:8000/capture`
- 📡 五路監控 → `:8000/monitor`
- 📺 大螢幕投放 → `:8000/display`
- 📊 Grafana → `:3000`

---

## 三、運維層 Grafana

由 `docker compose -f grafana/docker-compose.yml up -d` 啟動，走 `:3000`。
帳號 `admin` / 密碼 `aiSpeech2026`。

| Dashboard | 檔案 | 角色 | 包含 |
|---|---|---|---|
| `aiSpeechMulti 語音辨識監控` | [grafana/dashboards/aiSpeechMulti.json](../grafana/dashboards/aiSpeechMulti.json) | SRE / 開發 | 7 個 row + 25 panels |

### Dashboard 7 個 row（按上下順序）

| Row | id | 內容 |
|---|---|---|
| 📊 整體統計 | 100 | 總辨識筆數、引擎 / 危害分布等 stat |
| 📈 辨識量趨勢 | (略) | 時間軸辨識量 |
| 🔍 引擎與管道分析 | (略) | 各引擎 / 各 channel 統計 |
| ⚠️ 關鍵字危害分析 | (略) | 危害等級分布、熱門關鍵字 |
| 🎙️ 最近辨識記錄 | (略) | 最近 transcripts 表 |
| 📁 檔案辨識評測記錄 | (略) | batch_eval 結果表 |
| **📈 CER 趨勢**（2026-05-04 新增） | **200** | 下方詳列 |

### CER 趨勢區塊（P2 新增 3 panel）

| panel id | 標題 | 類型 | 資料來源 |
|---|---|---|---|
| 201 | 各引擎 final CER 趨勢 | timeseries | `cer_history` table |
| 202 | 最近一輪各引擎最佳 final CER | table | `cer_history` table |
| 203 | 事件類型 × 引擎 — 最近一輪 CER | table | `cer_event_type_history` table |

> **資料來源**：`cer_history` 與 `cer_event_type_history` 兩張 SQLite 表是從 CSV 鏡入的。
> 跑 `python -m aispeech data sync-cer` 同步最新狀態。

---

## 四、命令列入口

由 `python -m aispeech ...` 進入，包在 [aispeech/__main__.py](../aispeech/__main__.py)。
**設計原則**：thin wrapper，舊 `scripts/*.py` 完全保留不刪不動。

### 子命令樹

```
python -m aispeech
├── finetune          → scripts/finetune_sensevoice.py
├── infer             → scripts/batch_inference.py
├── infer-ft-all      → scripts/_inference_finetuned_all.py
├── eval              → scripts/eval_finetuned_model.py
├── eval-batch        → scripts/batch_stt_eval.py
├── ensemble          → scripts/ensemble_eval.py
├── data
│   ├── build-manifest        → scripts/build_golden_manifest.py
│   ├── build-finetune        → scripts/build_finetune_dataset.py
│   ├── build-lm              → scripts/build_ngram_lm.py
│   ├── extract-errors        → scripts/extract_error_pairs.py
│   ├── extract-regression    → scripts/extract_regression_cases.py
│   ├── export-feedback       → scripts/export_correction_feedback.py
│   └── sync-cer              → scripts/sync_cer_to_sqlite.py
└── serve
    ├── api           → python app_api.py
    ├── lab           → streamlit run app_lab.py
    └── all           → 兩支同時起（Ctrl-C 廣播停兩個）
```

### 透傳機制

未識別的旗標一律透傳給對應 script。例：

```bash
python -m aispeech finetune --mode lora --lora-rank 32 --epochs 60 --lr 1e-3
# 等價於
python scripts/finetune_sensevoice.py --mode lora --lora-rank 32 --epochs 60 --lr 1e-3
```

---

## 五、API endpoints（資料層）

由 [app_api.py](../app_api.py) 提供，是所有上層介面的後端：

### WebSocket

| endpoint | 用途 |
|---|---|
| `WS /ws/stream/{channel_id}?mode=dual&backend=google` | 5 路即時串流（4 種 mode） |

### REST — 系統 / 辨識

| endpoint | 用途 |
|---|---|
| `GET /api/channels` | 5 路管道狀態 |
| `GET /api/transcripts` | 辨識結果查詢 |
| `GET /api/keywords` | 關鍵字清單（display 頁用） |
| `GET /api/test_scribe` | Scribe RT 連線診斷 |

### REST — 健康 / Landing（2026-05-04 新增）

| endpoint | 用途 |
|---|---|
| `GET /api/health` | 健康檢查 |
| `GET /api/landing/status` | Landing 頁外部服務探活（FastAPI/Lab/Grafana） |

### REST — 設定

| endpoint | 用途 |
|---|---|
| `GET /api/settings` / `POST /api/settings` | 音訊前處理設定（VAD / 降噪） |

### REST — 詞彙表（2026-05-04 P3-Vocab 新增）

| endpoint | 用途 |
|---|---|
| `GET /api/vocabulary` | 查全部 + sha256 hash |
| `GET /api/vocabulary/engines` | 列出引擎 overlay |
| `GET /api/vocabulary/{term}` | 查單筆 |
| `POST /api/vocabulary` | 新增（409 if exists） |
| `PUT /api/vocabulary/{term}` | 修改 |
| `DELETE /api/vocabulary/{term}` | 刪除 |

---

## 六、deprecated 介面（30 天過渡期）

| 路徑 | 狀態 | 處理 |
|---|---|---|
| `streamlit run app_dashboard.py` | ⚠️ **2026-05-04 起 deprecated** | 啟動只看到警示頁；2026-06-04 後刪除 |
| Lab `cer_trend` 頁 | ⚠️ 已標記遷移到 Grafana | 已加遷移橫幅；2026-06-04 後刪除 render 函式 |

---

## 七、速查卡

```
:8000/          → Landing（5 入口）
:8000/capture   → 擷取頁（場域）
:8000/monitor   → 5 路監控（操作員）
:8000/display   → 大螢幕（控制室）

:8501/          → Streamlit Lab（9 頁 sidebar 切換）
                  └ speech / offline_monitor / evaluation / cer_trend
                    correction_history / management / search / stats / vocabulary

:3000/          → Grafana（admin / aiSpeech2026）
                  └ 系統指標 6 區 + 📈 CER 趨勢 1 區

CLI             → python -m aispeech ...
```

---

## 八、啟動指令對照

| 場景 | 指令 |
|---|---|
| 只起 API（場域監控） | `python app_api.py` 或 `python -m aispeech serve api` |
| 只起 Lab（研究） | `streamlit run app_lab.py` 或 `python -m aispeech serve lab` |
| 兩支同時起 | `python -m aispeech serve all` |
| 起 Grafana | `docker compose -f grafana/docker-compose.yml up -d` |
| CER 同步入庫 | `python -m aispeech data sync-cer` |
| 全套（推薦） | 開三個 terminal 各跑：API、Lab、Grafana docker；CLI 隨用隨跑 |

---

## 九、相關連結

- 規劃書：Obsidian `_decisions/介面整併規劃 v1.md`
- 實作 devlog：Obsidian `_devlog/2026-05-04 介面整併 P0-P3 完成.md`
- 互動架構圖：[architecture.html](./architecture.html)
- 主路線圖：Obsidian `_decisions/CER 20%目標路線圖.md`
- 專案入口：Obsidian `00_Project MOC.md`
