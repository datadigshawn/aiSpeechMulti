# aiSpeechMulti

> 五路無線電語音即時辨識平台 · 多 STT 引擎 + LLM 後修正 + 黃金語料 CER 追蹤

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.28%2B-red)](https://streamlit.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-green)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-internal-lightgrey)]()

---

## 一、它是什麼

針對 **窄頻無線電語音**（如捷運 OCC 控制中心 5 路通訊）設計的多引擎辨識平台：

- **即時：** 5 路同時擷取麥克風輸入，WebSocket 串流到後端，~150ms TTFT 即時推播 partial transcript
- **離線/批次：** 黃金語料集自動跑分 6 個 STT 引擎，CER 評測排序，支援 fine-tune
- **後處理飛輪：** 規則庫（基底 + 引擎 overlay + contextual + LLM）持續優化字準
- **可觀測：** Grafana dashboard 看引擎/危害/CER 趨勢

**當前主力**：gemini-2.5-pro（CER 48.03%），備援 SenseVoice-FT（離線零成本）。

---

## 二、為什麼這樣設計

| 設計決策 | 原因 |
|---|---|
| 多 STT 引擎並列而非單一引擎 | 窄頻無線電 baseline CER 50-80%，不同引擎在不同事件類型強弱不同；ensemble + 規則救字 |
| 引擎專屬 overlay（vocabulary/engines/*.json） | 實證每引擎錯字 pattern 不同（一條 blacklist 對 scribe 0 命中對 sensevoice 4 命中），統一規則互打 |
| dual mode（Scribe RT partial + Google batch confirmed） | RT 給操作員即時感，batch 給控制室存證 + LLM 後修正提供高準度紀錄 |
| 介面三層分離（FastAPI / Streamlit / Grafana） | 即時/研究/運維三種用戶 + 三種更新頻率，混在一起會互拖 |
| SQLite + WAL + FTS5 trigram | 單機部署夠用、零運維、中文 ≥3 字搜尋天然適配 |
| Audio preprocessing 引擎差異化 | chirp3/scribe 內建 frontend AGC，外部 loudnorm 反而 +CER；通過 `audio_preprocess.enabled` flag 路由 |

---

## 三、目錄結構

```
aiSpeechMulti/
├── app_api.py             # FastAPI 即時層 (1570 LOC, :8000)
├── app_dashboard.py       # ⚠️ deprecated 過渡頁
├── app_lab.py             # Streamlit 研究層 (4048 LOC, :8501, 9 頁)
├── aispeech/              # python -m aispeech 統一 CLI
│   ├── __init__.py
│   └── __main__.py        # thin wrapper → scripts/*.py
├── scripts/               # 30+ 工具腳本
│   ├── models/            # 6 個 STT 引擎 wrapper
│   │   ├── model_google_stt.py
│   │   ├── model_scribe.py        # 含 RT WebSocket
│   │   ├── model_sensevoice.py
│   │   ├── model_sensevoice_ft.py # fine-tuned
│   │   ├── model_whisper.py
│   │   └── model_gemini.py
│   ├── post_process.py    # 後處理 4 階段（car_norm → dict → contextual → LLM）
│   ├── batch_stt_eval.py  # 批次跑分（manifest.csv → 6 引擎）
│   ├── batch_inference.py # 批次推論協調
│   ├── cer_engine.py      # CER 度量
│   ├── result_fuser_sentence.py  # ensemble 仲裁
│   ├── finetune_sensevoice.py    # SenseVoice LoRA fine-tune
│   ├── build_cer_index.py        # CER 趨勢資料聚合
│   ├── extract_error_pairs.py    # 錯字配對抽取（draft overlay）
│   └── extract_regression_cases.py
├── utils/
│   ├── db_manager.py      # SQLite + FTS5 + 5 張表
│   ├── config.py          # 設定載入（singleton）
│   ├── gemini_client.py   # Gemini SDK 統一入口
│   ├── logger.py          # rotating + colored
│   ├── vad_filter.py      # WebRTC / Silero VAD
│   ├── noise_filter.py    # DeepFilterNet 降噪
│   ├── audio_archiver.py  # 音檔封存
│   └── api_keys.json      # 🔒 (gitignored)
├── vocabulary/
│   ├── term_filter.json              # 共用基底（v2.0）
│   ├── engines/
│   │   ├── gemini25pro.json
│   │   ├── scribe.json
│   │   ├── sensevoice.json
│   │   ├── chirp3.json
│   │   └── sensevoice_ft.json
│   ├── contextual_corrections.json   # 共用基底
│   └── correction_dict.py            # RADIO_REPLACEMENT_RULES
├── data/
│   ├── aiSpeechMulti.db   # SQLite 主庫（events / audio_files / transcriptions / FTS5 / keywords）
│   └── audio_archive/     # 🔒 (gitignored)
├── experiments/
│   ├── golden_dataset/    # 63 段黃金語料 + manifest.csv
│   ├── llm_correction_poc/ # CER 評測報告 + cer_history.csv
│   ├── finetune_runs/     # 🔒 LoRA checkpoint
│   └── regression_cases/
├── grafana/
│   ├── docker-compose.yml
│   ├── dashboards/aiSpeechMulti.json
│   └── datasources/
├── static/                # FastAPI 前端 4 頁（landing/capture/monitor/display）
├── docs/
│   ├── INTERFACES.md      # ★ 介面總表，必讀
│   ├── architecture-review-2026-05-07.md
│   ├── architecture.html  # 互動式 Mermaid 架構圖
│   └── finetune_setup_3090.md
├── 離線模式規劃/           # 離線模式 prototype（fork 的 app.py + setup.sh）
├── 調查資料之純語音部份/    # 🔒 (gitignored) 機密原始通訊
├── logs/                  # 🔒 (gitignored) 應用 log
├── requirements.txt
├── .env / .env.example
└── .gitignore
```

🔒 = gitignored，不入 git。

---

## 四、快速啟動

### 1. 環境準備

```bash
# Python 3.11+
python -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 系統依賴
brew install ffmpeg portaudio          # macOS
# sudo apt install ffmpeg portaudio19-dev  # Ubuntu/Debian
```

GPU（fine-tune 需要 RTX 3090+）：見 [docs/finetune_setup_3090.md](docs/finetune_setup_3090.md)。

### 2. 認證設定

複製 `.env.example` → `.env` 並填入：
- `GOOGLE_APPLICATION_CREDENTIALS=./utils/google-speech-key.json`（從 GCP Console 下載 service account JSON）
- `ELEVENLABS_API_KEY=sk_...`（[ElevenLabs dashboard](https://elevenlabs.io/app/settings/api-keys)）

或使用 `utils/api_keys.json`（推薦，runtime fallback）：

```json
{
  "GEMINI_API_KEY": "your-gemini-key",
  "GOOGLE_CLOUD_PROJECT": "your-gcp-project-id"
}
```

### 3. 啟動服務

```bash
# 即時辨識（FastAPI :8000）
python app_api.py
# 或
python -m aispeech serve api

# 研究 Lab（Streamlit :8501）
streamlit run app_lab.py
# 或
python -m aispeech serve lab

# 兩個一起起
python -m aispeech serve all

# Grafana（:3000，admin / aiSpeech2026）
docker compose -f grafana/docker-compose.yml up -d
```

開啟 http://localhost:8000 看 landing 頁，5 個入口卡 + 健康徽章。

---

## 五、常用 CLI 指令

統一入口：`python -m aispeech <cmd>`

| 指令 | 對應腳本 | 用途 |
|---|---|---|
| `infer` | scripts/batch_inference.py | 批次推論 |
| `eval-batch` | scripts/batch_stt_eval.py | 批次跑分（6 引擎 × manifest） |
| `eval` | scripts/eval_finetuned_model.py | fine-tuned 模型評測 |
| `finetune` | scripts/finetune_sensevoice.py | SenseVoice LoRA fine-tune |
| `ensemble` | scripts/ensemble_eval.py | ensemble 評測 |
| `data build-manifest` | scripts/build_golden_manifest.py | 重建黃金語料 manifest |
| `data extract-errors` | scripts/extract_error_pairs.py | 抽錯字配對為 draft overlay |
| `data sync-cer` | scripts/sync_cer_to_sqlite.py | CER CSV → SQLite（給 Grafana） |
| `serve api/lab/all` | — | 起服務 |

未識別的旗標會原樣透傳，例：

```bash
python -m aispeech finetune --mode lora --lora-rank 32 --epochs 60
```

---

## 六、核心資料流

```
Browser ×5 (PCM 16kHz)
    │ WebSocket /ws/stream/{1-5}?mode=dual
    ▼
FastAPI asyncio
    ├─→ Scribe v2 RT  ──→ partial → 前端  (~150ms TTFT)
    └─→ AudioBuffer (15s) → Google STT chirp_3 → confirmed
                                    │
                                    ▼
                            post_process 4 階段
                            ├─ car_norm (regex 數字)
                            ├─ dict (term_filter + engine overlay)
                            ├─ contextual (prefix/suffix 規則)
                            └─ LLM correction (Gemini, 可關)
                                    │
                                    ▼
                            SQLite + FTS5 manual sync
                                    │
                                    ▼
                            Grafana raw SQL → dashboard
```

詳細介面總表：[docs/INTERFACES.md](docs/INTERFACES.md)。

---

## 七、後處理飛輪（資料驅動 CER 優化）

```
✏️ 控制室人工修正
    ↓ Lab 修正歷程頁存進 DB
    ↓ scripts/export_correction_feedback.py
🌱 vocabulary/engines/{engine}.feedback-draft.json
    ↓ review 改名為 .json
    ↓ 重啟服務套用
🔄 下次辨識 CER ↓
```

實證效果：
- gemini-2.5-pro：raw CER 49.34% → 48.03%（含 overlay + 預處理）
- sensevoice：65.84% → 64.97%（contextual rules 6 條）
- scribe：66.15% → 63.23%（5 條 blacklist + 5 條 contextual + LLM）

---

## 八、開發 / 部署文件

| 文件 | 內容 |
|---|---|
| [docs/INTERFACES.md](docs/INTERFACES.md) | ★ 三層介面總表（埠號、UI、用戶、CLI 對應） |
| [docs/architecture.html](docs/architecture.html) | 互動式 Mermaid 架構圖 |
| [docs/architecture-review-2026-05-07.md](docs/architecture-review-2026-05-07.md) | 架構審視報告（已知技術債、優化路線） |
| [docs/finetune_setup_3090.md](docs/finetune_setup_3090.md) | RTX 3090 fine-tune 環境設定 |
| `WORKLOG_*.md` | 每日工作日誌（規劃移到 docs/devlog/） |

---

## 九、已知技術債（簡版）

完整見 [docs/architecture-review-2026-05-07.md](docs/architecture-review-2026-05-07.md)：

- **Critical**：無 schema migration、零自動化測試
- **Important**：無 STT 引擎抽象層、`app_lab.py` 4048 LOC god-file、`app_api.py` 1570 LOC、GCP project ID 硬編碼 8 處、離線模式規劃/ fork 未整合
- **Suggestion**：死檔 `data/aiSpeech.db`、WORKLOG 移到 `docs/devlog/`、清掉沒用的 psycopg2/sqlalchemy

---

## 十、安全注意

- `.env` / `utils/api_keys.json` / `utils/*-key.json` 全部在 `.gitignore`
- 機密通訊資料 `調查資料之純語音部份/` 已 gitignore
- LoRA checkpoint `experiments/finetune_runs/` 已 gitignore（可由 `build_finetune_dataset.py` 重建）
- API 金鑰請使用 `utils/api_keys.json`（權限 0700）優先於 `.env`
- 任何時候 key 進過 git diff/log，**一律視為外洩**，立即 revoke + 重發

---

## 十一、相關連結

- GitHub: [datadigshawn/aiSpeechMulti](https://github.com/datadigshawn/aiSpeechMulti)
- 上游 skill 框架：[datadigshawn/projectArea](https://github.com/datadigshawn/projectArea)
- Obsidian vault MOC：`2nd brain/20_Programming/Projects/aiSpeechMulti/00_Project MOC.md`

---

*最後更新：2026-05-07*
