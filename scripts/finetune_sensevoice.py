#!/usr/bin/env python3
"""
Phase 5 B2：SenseVoice fine-tune 腳本（CUDA 為主、MPS / CPU fallback）
======================================================================

對 FunAudioLLM/SenseVoiceSmall 做 LoRA / full fine-tune，使用 B1 產生的
jsonl 訓練資料。預設 LoRA 模式（小資料集安全），可選 full fine-tune。

設計：
- 載 FunASR AutoModel 取出底層 torch model
- LoRA 模式：用 peft 包 attention 層（rank=8 預設，輕量）
- Full 模式：解凍全模型（24GB VRAM 適用）
- mixed precision (fp16/bf16) 自動依 device 選
- 早停（val CER 連續 N 個 epoch 不改善）
- 每 epoch 存 checkpoint + training metrics（loss / val_cer）

⚠️ **3090 / RTX 4090 上跑最順**。M2 (MPS) 可跑但慢 5-10x，且部分 op
   會 fallback 到 CPU（更慢）。**強烈建議 CUDA 環境**。

⚠️ FunASR 的 SenseVoice fine-tune 官方教學偏好用 FunASR 自家 trainer
   （`funasr.bin.train`）。本腳本用 torch 自寫 loop 以獲得更多控制
   （LoRA 整合、自訂 metric），代價是不能用 FunASR 的某些優化。

用法：
    # 1. 先用 B1 產生訓練資料（FunASR 格式）
    python3 scripts/build_finetune_dataset.py --format funasr

    # 2. LoRA fine-tune（預設、安全）
    python3 scripts/finetune_sensevoice.py --mode lora

    # 3. Full fine-tune（資料 200+ 段才建議）
    python3 scripts/finetune_sensevoice.py --mode full --batch-size 4

    # 4. 從 checkpoint 繼續
    python3 scripts/finetune_sensevoice.py --resume experiments/finetune_runs/sensevoice_lora_v1/best.pt

依賴（需先 pip install）:
    pip install torch torchaudio funasr peft accelerate
    # CUDA: pip install torch --index-url https://download.pytorch.org/whl/cu121
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


# ══════════════════════════════════════════════════════════════════════
# 環境檢查
# ══════════════════════════════════════════════════════════════════════
def check_env() -> dict:
    info = {"ok": True, "issues": []}
    try:
        import torch
        info["torch"] = torch.__version__
        info["cuda"] = torch.cuda.is_available()
        info["mps"] = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        if info["cuda"]:
            info["device"] = "cuda"
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)
        elif info["mps"]:
            info["device"] = "mps"
        else:
            info["device"] = "cpu"
            info["issues"].append("⚠️ 無 GPU 可用，將跑在 CPU（極慢）")
    except ImportError:
        info["ok"] = False
        info["issues"].append("❌ torch 未安裝")
        return info

    for pkg in ("funasr", "peft", "accelerate", "torchaudio", "soundfile"):
        try:
            __import__(pkg)
            info[pkg] = "✅"
        except ImportError:
            info[pkg] = "❌"
            info["issues"].append(f"❌ {pkg} 未安裝")
            info["ok"] = False

    return info


# ══════════════════════════════════════════════════════════════════════
# Dataset
# ══════════════════════════════════════════════════════════════════════
@dataclass
class TrainSample:
    key: str
    audio_path: str
    text: str
    duration_sec: float


class JSONLDataset:
    """讀 B1 產出的 jsonl（HF 或 FunASR 格式都支援）"""

    def __init__(self, jsonl_path: Path):
        self.path = Path(jsonl_path)
        self.samples: list[TrainSample] = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                # 自動偵測格式
                if "audio_filepath" in d:  # HF 格式
                    self.samples.append(TrainSample(
                        key=d.get("id", ""),
                        audio_path=d["audio_filepath"],
                        text=d["text"],
                        duration_sec=d.get("duration", 0),
                    ))
                elif "source" in d and "target" in d:  # FunASR 格式
                    self.samples.append(TrainSample(
                        key=d.get("key", ""),
                        audio_path=d["source"],
                        text=d["target"],
                        duration_sec=d.get("source_len", 0) / 1000,
                    ))

    def __len__(self):
        return len(self.samples)

    def __iter__(self):
        return iter(self.samples)


# ══════════════════════════════════════════════════════════════════════
# 評估：CER
# ══════════════════════════════════════════════════════════════════════
def compute_cer(refs: list[str], hyps: list[str]) -> float:
    try:
        import jiwer
    except ImportError:
        # fallback
        from difflib import SequenceMatcher
        cers = []
        for r, h in zip(refs, hyps):
            sm = SequenceMatcher(None, r, h)
            sim = sum(b.size for b in sm.get_matching_blocks())
            cers.append(1 - sim / max(len(r), 1))
        return sum(cers) / max(len(cers), 1)
    return jiwer.cer(refs, hyps)


# ══════════════════════════════════════════════════════════════════════
# 訓練主流程（簡化版，依賴 FunASR AutoModel）
# ══════════════════════════════════════════════════════════════════════
def setup_model(device: str, lora_rank: int = 8, mode: str = "lora"):
    """
    載入 SenseVoice 並依模式設定可訓練參數。
    回傳 (model, tokenizer)，model 可用於 forward + backward。
    """
    from funasr import AutoModel

    print(f"📦 載入 SenseVoiceSmall 基礎模型 (device={device})...")
    base = AutoModel(
        model="FunAudioLLM/SenseVoiceSmall",
        hub="hf",
        device=device,
        disable_update=True,
    )
    # FunASR AutoModel 取出底層 torch.nn.Module
    torch_model = base.model

    if mode == "lora":
        print(f"🪶 LoRA 模式 (rank={lora_rank})")
        try:
            from peft import LoraConfig, get_peft_model, TaskType
        except ImportError:
            raise RuntimeError("缺 peft：pip install peft")
        # 對 attention 線性層套 LoRA
        # SenseVoice 是 SAN-M / Conformer 結構，target_modules 需依架構調整
        # 預設嘗試常見的 attention linear name
        lora_config = LoraConfig(
            r=lora_rank,
            lora_alpha=lora_rank * 2,
            target_modules=["q_proj", "k_proj", "v_proj", "out_proj", "linear_q", "linear_k", "linear_v", "linear_out"],
            lora_dropout=0.05,
            bias="none",
            task_type=TaskType.FEATURE_EXTRACTION,
        )
        try:
            torch_model = get_peft_model(torch_model, lora_config)
            torch_model.print_trainable_parameters()
        except Exception as e:
            print(f"⚠️ LoRA 套用失敗（可能 target_modules 與架構不符）: {e}")
            print("   將改為「凍結 encoder + 訓練 decoder」備援模式")
            for name, p in torch_model.named_parameters():
                p.requires_grad = "decoder" in name.lower() or "ctc" in name.lower()
    elif mode == "full":
        print(f"🔓 Full fine-tune 模式（全參數可訓練）")
        for p in torch_model.parameters():
            p.requires_grad = True
    elif mode == "decoder_only":
        print(f"🎯 Decoder-only 模式（凍結 encoder）")
        for name, p in torch_model.named_parameters():
            p.requires_grad = "decoder" in name.lower() or "ctc" in name.lower()
    else:
        raise ValueError(f"未知 mode: {mode}")

    n_train = sum(p.numel() for p in torch_model.parameters() if p.requires_grad)
    n_total = sum(p.numel() for p in torch_model.parameters())
    print(f"   可訓練參數: {n_train:,} / {n_total:,} ({100*n_train/n_total:.2f}%)")

    return base, torch_model


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="experiments/finetune_dataset",
                    help="B1 產出的訓練資料目錄（含 train.jsonl / val.jsonl）")
    ap.add_argument("--out-dir", default="experiments/finetune_runs/sensevoice_lora_v1",
                    help="輸出目錄（checkpoint + metrics）")
    ap.add_argument("--mode", choices=["lora", "full", "decoder_only"], default="lora",
                    help="LoRA（推薦）/ full / decoder_only")
    ap.add_argument("--lora-rank", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--gradient-accum", type=int, default=4)
    ap.add_argument("--early-stop-patience", type=int, default=3)
    ap.add_argument("--device", choices=["auto", "cuda", "mps", "cpu"], default="auto")
    ap.add_argument("--mixed-precision", choices=["auto", "fp16", "bf16", "fp32"], default="auto")
    ap.add_argument("--check-env-only", action="store_true", help="只檢查環境不訓練")
    ap.add_argument("--dry-run", action="store_true", help="載入模型 + 印參數統計後結束（不訓練）")
    args = ap.parse_args()

    # ── 環境檢查 ──────────────────────────────────────────
    print("🔍 環境檢查")
    print("=" * 60)
    env = check_env()
    for k, v in env.items():
        if k != "issues":
            print(f"   {k:18}: {v}")
    if env["issues"]:
        print()
        for issue in env["issues"]:
            print(f"   {issue}")

    if args.check_env_only:
        sys.exit(0 if env["ok"] else 1)
    if not env["ok"]:
        print("\n❌ 環境不滿足、請先安裝缺失套件")
        sys.exit(1)

    # ── device 決定 ───────────────────────────────────────
    if args.device == "auto":
        device = env["device"]
    else:
        device = args.device
    print(f"\n🖥️  使用 device: {device}")

    # ── 載入資料 ──────────────────────────────────────────
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    train_jsonl = data_dir / "train.jsonl"
    val_jsonl = data_dir / "val.jsonl"
    if not train_jsonl.exists():
        print(f"\n❌ {train_jsonl} 不存在，請先跑 build_finetune_dataset.py")
        sys.exit(1)

    train_ds = JSONLDataset(train_jsonl)
    val_ds = JSONLDataset(val_jsonl) if val_jsonl.exists() else None
    print(f"\n📋 訓練資料: {len(train_ds)} 段")
    if val_ds:
        print(f"   驗證資料: {len(val_ds)} 段")

    # ── 載模型 ────────────────────────────────────────────
    base, model = setup_model(device, lora_rank=args.lora_rank, mode=args.mode)

    if args.dry_run:
        print("\n✅ Dry run：模型載入成功、可訓練參數確認，結束")
        return

    # ── 訓練主迴圈 ────────────────────────────────────────
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("⚠️  訓練主迴圈尚未實作（待 B2 v2 完成）")
    print("    當前版本為「環境驗證 + 模型載入 + 參數統計」階段")
    print(f"    輸出目錄已準備：{out_dir}")
    print()
    print("    下一步：寫實際 forward/backward 訓練 loop")
    print("    或：改用 FunASR 官方 finetune.py（funasr.bin.train）")

    # 寫一份 metadata 紀錄這次訓練設定
    meta = {
        "mode":        args.mode,
        "lora_rank":   args.lora_rank,
        "epochs":      args.epochs,
        "batch_size":  args.batch_size,
        "lr":          args.lr,
        "device":      device,
        "data_dir":    str(data_dir.relative_to(PROJECT_ROOT)),
        "train_n":     len(train_ds),
        "val_n":       len(val_ds) if val_ds else 0,
        "env":         env,
    }
    (out_dir / "training_config.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"📝 已寫 training_config.json 至 {out_dir}")


if __name__ == "__main__":
    main()
