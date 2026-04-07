# LLM 後修正層 PoC

驗證使用 Gemini 對歷史辨識結果進行後修正的效果。

## 用法

```bash
# 預設：抽 10 筆，gemini-2.5-flash，conservative 模式
python3 experiments/llm_correction_poc/poc_llm_correction.py

# 抽 20 筆 + 平衡修正強度
python3 experiments/llm_correction_poc/poc_llm_correction.py \
    --limit 20 \
    --strictness balanced

# 用 gemini-2.5-pro 做高品質測試
python3 experiments/llm_correction_poc/poc_llm_correction.py \
    --model gemini-2.5-pro \
    --limit 5
```

## 參數

| 參數 | 預設 | 說明 |
|---|---|---|
| `--limit` | 10 | 從 DB 隨機抽樣的筆數 |
| `--model` | `gemini-2.5-flash` | Gemini 模型名稱 |
| `--strictness` | `conservative` | `conservative` / `balanced` / `aggressive` |
| `--vocab-size` | 60 | 載入 master_vocabulary.csv 前 N 條（依 boost_value 排序） |

## 前置條件

1. 安裝 Gemini SDK：
   ```bash
   pip install google-generativeai
   ```
2. 設定 API key（擇一）：
   - 環境變數 `GEMINI_API_KEY`
   - `utils/api_keys.json`（含 `gemini_api_key` 鍵）
   - `.env` 內 `GEMINI_API_KEY=...`

## 輸出

每次執行會在本目錄產生兩個檔案：

- `results_<timestamp>.json` — 完整結構化結果（含原文、修正、changes、耗時）
- `results_<timestamp>.md` — 人類可讀對照報告（含每筆 diff、修正項目）

## 評估指標

- **修正次數**：LLM 回報的 changes 陣列長度
- **字元變動**：使用 difflib SequenceMatcher 計算的字元級差異數
- **CER vs 原**：以原文為基準的字元錯誤率（純參考用，沒有 ground truth）
- **耗時**：每句平均 API 呼叫時間

## 下一步

若效果良好（修正集中在已知錯字、未過度改寫），即可進入正式 Sprint 1：
- 將 `call_gemini()` 與 `build_prompts()` 抽到 `scripts/models/llm_corrector.py`
- 加入批次模式（每次 10 句 + 上下文）
- 整合到 `app_dashboard.py` 的 Step 7 UI
