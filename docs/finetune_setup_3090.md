# 3090 桌機 fine-tune 環境設定清單

> 本清單為 04-30 規劃，預計晚上 SSH 連線後依序執行（~10-15 分鐘完成）。
> 目標：在 RTX 3090 桌機跑通 SenseVoice LoRA fine-tune PoC。

---

## 0. 前置確認（連線後第一件事）

```bash
# 確認 GPU 識別
nvidia-smi
# 預期：看到 RTX 3090、24576MiB VRAM、Driver Version ≥ 525

# 確認 OS / Python
uname -a
python3 --version  # 建議 3.10+
```

如果 nvidia-smi 失敗 → 先裝 NVIDIA driver / CUDA toolkit。

---

## 1. clone 或 pull repo

### 第一次（clone）

```bash
cd ~
git clone https://github.com/datadigshawn/aiSpeechMulti.git
cd aiSpeechMulti
```

### 已有 repo（pull）

```bash
cd ~/aiSpeechMulti
git pull origin main
```

---

## 2. Python 環境

建議用 conda 或 venv 隔離：

```bash
# 用 miniconda（推薦）
conda create -n aispeech python=3.11 -y
conda activate aispeech

# 或用 venv
python3 -m venv .venv
source .venv/bin/activate
```

---

## 3. 安裝核心套件

```bash
# 基本依賴（與 M2 一致）
pip install -r requirements.txt
```

### CUDA 加速版 PyTorch（**關鍵！替換 CPU 版本**）

```bash
# 移除 CPU 版本
pip uninstall -y torch torchvision torchaudio

# 裝 CUDA 12.1 版本（3090 支援 CUDA 12.x）
pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu121

# 驗證 CUDA 識別
python3 -c "import torch; print(f'cuda={torch.cuda.is_available()} device={torch.cuda.get_device_name(0)}')"
# 預期輸出：cuda=True device=NVIDIA GeForce RTX 3090
```

### Fine-tune 必要套件

```bash
pip install funasr peft accelerate
```

### 加速套件（可選但推薦）

```bash
# Flash Attention 2（提速 + 省 VRAM；需要 CUDA 編譯，大約 5-10 分鐘）
pip install flash-attn --no-build-isolation

# bitsandbytes（8-bit/4-bit 量化，更省 VRAM）
pip install bitsandbytes

# wandb（訓練監控；可選）
pip install wandb
```

---

## 4. 一鍵驗證環境

```bash
# 跑 B2 環境檢查
python3 scripts/finetune_sensevoice.py --check-env-only
```

**期望輸出**：
```
🔍 環境檢查
============================================================
   ok                : True
   torch             : 2.x.x+cu121
   cuda              : True ⭐
   mps               : False
   device            : cuda ⭐
   gpu_name          : NVIDIA GeForce RTX 3090
   vram_gb           : 24.0
   funasr            : ✅
   peft              : ✅
   accelerate        : ✅
   torchaudio        : ✅
   soundfile         : ✅
```

---

## 5. 跑模型載入 dry-run

```bash
python3 scripts/finetune_sensevoice.py --dry-run
```

**期望**：
- 從 HuggingFace 下載 SenseVoiceSmall（首次 ~500MB，約 1-3 分鐘）
- 載入到 cuda
- LoRA 包裝成功
- 印「可訓練參數: 573,440 / 234,572,607 (0.24%)」

---

## 6. 準備訓練資料

```bash
# 從 manifest + GT 建 jsonl（FunASR 格式）
python3 scripts/build_finetune_dataset.py --format funasr
# 或含 DB 累積的人工修正
python3 scripts/build_finetune_dataset.py --format funasr --include-corrections
```

**期望**：在 `experiments/finetune_dataset/` 看到 `train.jsonl` / `val.jsonl` / `test.jsonl` / `metadata.json`。

---

## 7. 啟動訓練（PoC 第一輪）

⚠️ **B2 訓練主迴圈尚待補完**（見 commit `da5c305` 說明）。SSH 上去後我會根據實際 SenseVoice forward API 補上 training loop。

預計訓練命令：
```bash
python3 scripts/finetune_sensevoice.py \
    --mode lora \
    --epochs 10 \
    --batch-size 4 \
    --lr 1e-4 \
    --out-dir experiments/finetune_runs/sensevoice_lora_v1
```

**3090 預估時間**：30-50 分鐘（200 段、10 epoch）

---

## 8. 評估 fine-tuned 模型

```bash
python3 scripts/eval_finetuned_model.py \
    --checkpoint experiments/finetune_runs/sensevoice_lora_v1/best.pt \
    --label sensevoice_ft_v1
```

**期望輸出**：
```
🔬 跑 batch_eval CER 對照...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
model                  pp                  raw CER  final CER
sensevoice_ft_v1       raw                  ?? %    ?? %
sensevoice_ft_v1       car_norm+dict        ?? %    ?? %
sensevoice             raw                65.84%   65.59%
sensevoice             car_norm+dict      64.97%   64.97%
gemini25pro            raw                49.34%   48.35%
gemini25pro            car_norm+dict      48.35%   48.35%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

期望 `sensevoice_ft_v1` 比原始 `sensevoice` 改善 -10~15pp（依 200 段資料估）。

---

## 常見問題排除

### 1. CUDA OOM（記憶體不夠）

```
RuntimeError: CUDA out of memory.
```

**解法**：
- 減 batch_size：`--batch-size 2`
- 增 gradient_accum：`--gradient-accum 8`（等效 batch=16）
- 啟用 fp16：`--mixed-precision fp16`
- 用 8-bit Adam：`pip install bitsandbytes` 後改 optimizer

### 2. ModelScope 下載失敗

```
ConnectionError: ...modelscope.cn... timed out
```

**解法**：腳本預設用 HuggingFace（`hub="hf"`），不應碰到。若失敗：
```bash
export HF_ENDPOINT=https://hf-mirror.com  # 國內 mirror
python3 scripts/finetune_sensevoice.py --dry-run
```

### 3. peft target_modules 不匹配

```
ValueError: Target modules ... not found in the base model.
```

**解法**：B2 已有 fallback 到「凍結 encoder + 訓練 decoder」。若要手動指定：
```bash
python3 scripts/finetune_sensevoice.py --mode decoder_only
```

### 4. nvidia-smi 顯示有 GPU 但 PyTorch 找不到

```python
torch.cuda.is_available()  # False
```

**解法**：通常是 PyTorch 安裝錯版本（裝到 CPU only）：
```bash
pip uninstall -y torch
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

---

## 開發流程建議

### 從 M2 開發、3090 訓練

```
M2 (你的工作機)                    3090 桌機
┌──────────────────┐              ┌──────────────────┐
│ 編輯 scripts/    │              │ 跑 fine-tune     │
│ git push         │ ───────────> │ git pull         │
│                  │              │ python3 ...      │
│ 看結果報告       │ <─────────── │ 上傳 checkpoint  │
└──────────────────┘              └──────────────────┘
```

### 或直接 SSH + VS Code Remote

```bash
# 從 M2 SSH
ssh user@3090-host

# VS Code Remote-SSH 直接編輯桌機檔案
# 享受 M2 的鍵盤 + 3090 的 GPU
```

---

## 附錄：檢查訓練是否真的在 GPU 跑

訓練啟動後另開一個 terminal：
```bash
watch -n 2 nvidia-smi
```

**期望**：
- GPU-Util > 80%（持續高負載）
- Memory-Usage 顯示訓練程序佔用 ~6-10GB（LoRA）或 16-20GB（full fine-tune）

如果 GPU-Util 一直 0% 而 CPU 卻很忙 → 訓練跑在 CPU 上、需 debug device 設定。

---

## 維護紀錄

- 2026-04-30: 初版（v1）
- 規劃晚上 SSH 後執行，補完整訓練 loop
