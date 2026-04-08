# 黃金語料集（Golden Dataset）

aiSpeechMulti 語音辨識改善的**真實世界基準資料集**，用於：
1. 量化各引擎與後處理層的真實效益（CER / WER）
2. 防止「直覺改善」實際上是退步（如 04-07 發現的 dict NET NEGATIVE）
3. 累積資料飛輪，作為未來 fine-tune / n-gram LM 的訓練源

---

## 📁 資料夾結構

```
experiments/golden_dataset/
├── README.md                ← 本文件
├── audio/                   ← 音檔（WAV / MP3 / M4A）
│   ├── 001_daily_xxx.wav
│   ├── 002_door_xxx.wav
│   └── ...
├── ground_truth/            ← 對應的人工標註文字檔
│   ├── 001_daily_xxx.txt
│   ├── 002_door_xxx.txt
│   └── ...
├── manifest.csv             ← 索引清單（由 scripts/build_golden_manifest.py 自動產生）
└── notes/                   ← 標註過程的備忘
    └── difficult_cases.md
```

**重要**：`audio/` 與 `ground_truth/` 內的檔案**檔名相同，副檔名不同**，這樣 manifest 腳本才能自動配對。

---

## 🎯 目標規模

| 階段 | 目標段數 | 預估完成時間 |
|---|---|---|
| MVP | **30 段** | 6 天（每天 5 段）|
| 階段 2 | 60 段 | 額外 6 天 |
| 階段 3 | 100+ 段 | 額外 8 天 |

---

## 📝 檔案命名規範

### 命名格式
```
{順序編號:03d}_{事件類型}_{原檔名簡化}.{副檔名}
```

### 命名範例

| 編號 | 事件類型 | 完整檔名 |
|---|---|---|
| 001 | daily | `001_daily_UltraLog063_20260321_154513.wav` |
| 002 | door | `002_door_UltraLog063_20251222_192724.wav` |
| 003 | track | `003_track_UltraLog061_20260321_165823.wav` |
| 004 | emergency | `004_emergency_UltraLog063_20260401_120000.wav` |
| 005 | control | `005_control_UltraLog061_20260321_155711.wav` |

### 事件類型代碼

| 代碼 | 中文 | 內容 |
|---|---|---|
| `daily` | 日常通訊 | 站長回報、車輛點檢、班次調度 |
| `door` | 車門事件 | 月台門/EDRH/MCP 操作 |
| `track` | 軌道作業 | 三軌復電、清車、進站確認 |
| `emergency` | 緊急事件 | 火災、出軌、受傷、異物入侵 |
| `control` | 列車控制 | ATP/ATO/MCS 模式切換 |

### 建議分佈

| 事件類型 | MVP 段數 | 階段 2 段數 |
|---|---|---|
| daily | 6 | 12 |
| door | 6 | 12 |
| track | 6 | 12 |
| emergency | 6 | 12 |
| control | 6 | 12 |
| **總計** | **30** | **60** |

---

## ✏️ Ground Truth 文字檔格式

### 格式規範

```
[講者代號]: [對話內容]
```

每位講者一句一行。

### 講者代號定義

| 代號 | 角色 | 說明 |
|---|---|---|
| `B` | OCC 行控中心（Base） | 負責全線通告、調度 |
| `H` | 站長/站員（Host） | 站務員回報 |
| `G` | 車長/司機員（Guard） | 列車操作員 |
| `T` | 維修/技術人員（Technician） | 設備維修 |
| `?` | 無法辨識/雜訊 | 標註為 `?` |

### 內容書寫規範

| 規則 | ✅ 正確 | ❌ 錯誤 |
|---|---|---|
| 站碼補零 | `G07` | `G7` |
| 車廂編號 | `25/26 車` | `2526車` |
| 月台 | `2 月台` | `二月台` |
| 英文術語 | `OCC` `EDRH` | `occ` `edrh` |
| 通訊用語 | `over` | `oveR` `OVER` |
| 標點符號 | 全形 `，。？！` | 半形 `,.?!` |
| 不確定字 | `[?]` | （留白） |
| 雜訊段 | `[noise]` `[unclear]` | （略過） |

### GT 完整範例

```
B: OCC 通告全線，目前在進行 G07 中清不含月台以南，正線上下行三軌復電作業，請站長至月台協助引導旅客，通告完畢
H: G17 高鐵站呼叫 OCC，二月台列車 25/26 車門未開啟，是否使用 EDRH 開啟車門？over
B: OCC 回復，跟你確認月台，列車是否停準？over
H: 25/26 車門未停準，over
B: 跟你確認列車是否停準？over
G: 高鐵站長回復 OCC，列車未停準、未停準，over
B: OCC 呼叫 G17 高鐵站長，請人員至 10 車門處以 EDRH 登上列車，以 MCS 模式開啟月台側車門，引導旅客下車
```

---

## 🛠️ 工作流程

### Step 1：選音檔（30 段）

```bash
# 列出所有可用音檔
find experiments/61001 experiments/61003 experiments/MTC \
     -name "UltraLog*.wav" 2>/dev/null
```

選擇原則：
- ✅ 涵蓋 5 種事件類型（每類 6 段）
- ✅ 時長 10-60 秒（避免太長）
- ✅ 音質良好
- ✅ 內容多樣

### Step 2：複製音檔到 audio/

```bash
cp experiments/61003/UltraLog06320260321154513.wav \
   experiments/golden_dataset/audio/001_daily_UltraLog063_20260321_154513.wav
```

### Step 3：人工標註 GT

每段音檔：
1. **第一遍**：聽寫內容
2. **第二遍**：標註講者代號（B/H/G/T）
3. **第三遍**：檢查術語拼寫（站碼、英文、阿拉伯數字）
4. **存檔**：放到 `ground_truth/` 對應檔名

**輔助技巧**：
- 用 Gemini 2.5 Pro 跑底稿（不可直接信任，要逐字對照修正）
- 不確定的字寫 `[?]`，過程中的疑問記到 `notes/difficult_cases.md`

### Step 4：產生 manifest.csv

```bash
~/miniforge3/bin/python scripts/build_golden_manifest.py
```

### Step 5：跑首次 baseline 評測

```bash
~/miniforge3/bin/python experiments/llm_correction_poc/batch_eval.py \
    --manifest experiments/golden_dataset/manifest.csv \
    --engine chirp_3
```

---

## 💡 加速建置技巧

### 技巧 1：用 Gemini 跑底稿
Gemini 對長段中文辨識相對準確，先跑出底稿後人工修正比從零開始快 5~10 倍。

### 技巧 2：分批標註
- 每天標 5 段，6 天完成
- 每次只標同一類事件（連續 6 段同類比較專注）

### 技巧 3：兩人交叉驗證
若有同事可協助，**每段請兩人各標一次**，再交叉比對差異 → 用於計算「人工標註的天花板 CER」

### 技巧 4：建立術語速查表
標註時開一個 cheat sheet 視窗：
```
G01-G17, R01-R20  → 站碼
OCC MTC EDRH ATP ATO MCP CBTC NCP ETF  → 設備
復電 清車 引導 登上 通告 回報  → 動作
```

---

## 📊 評測目標

| 指標 | 日常通訊 | 緊急事件 |
|---|---|---|
| **CER 目標** | < 10% | < 5% |
| **WER 目標** | < 15% | < 8% |

當前 baseline（2026-04-07）：
- chirp_3 + 後處理: CER ~55%
- Gemini 3.1 Pro + 後處理: CER ~27%

---

## 🔗 相關工具

- 建立 manifest: `scripts/build_golden_manifest.py`
- 批次評測: `experiments/llm_correction_poc/batch_eval.py`
- A/B 測試: `experiments/llm_correction_poc/ab_test.py`
- 覆蓋率評測: `experiments/llm_correction_poc/coverage_eval.py`
