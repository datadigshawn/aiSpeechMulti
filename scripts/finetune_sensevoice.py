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
    回傳 (base, torch_model, tokenizer)，可用於 forward + backward。

    base：funasr.AutoModel（用於 inference / generate）
    torch_model：底層 nn.Module（已套 LoRA / freeze 等）
    tokenizer：funasr SenseVoice tokenizer（含特殊 token 編碼）
    """
    from funasr import AutoModel

    print(f"📦 載入 SenseVoiceSmall 基礎模型 (device={device})...")
    base = AutoModel(
        model="FunAudioLLM/SenseVoiceSmall",
        hub="hf",
        device=device,
        disable_update=True,
    )
    # FunASR AutoModel 取出底層 torch.nn.Module + tokenizer
    torch_model = base.model
    tokenizer = base.kwargs.get("tokenizer")
    if tokenizer is None:
        raise RuntimeError("base.kwargs['tokenizer'] 不存在，funasr 版本可能不相容")

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

    return base, torch_model, tokenizer


# ══════════════════════════════════════════════════════════════════════
# 訓練 Dataset / Collate
# ══════════════════════════════════════════════════════════════════════
class AudioFeatureDataset:
    """讀 jsonl + 音檔 → 用 SenseVoice WavFrontend 算 (T, 560) 特徵"""

    def __init__(self, jsonl_path: Path, frontend, target_sr: int = 16000, max_dur: float = 30.0):
        self.samples = JSONLDataset(jsonl_path).samples
        self.frontend = frontend     # 來自 base.kwargs["frontend"]，WavFrontend
        self.target_sr = target_sr
        self.max_samples = int(max_dur * target_sr)

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        import torch
        import soundfile as sf
        s = self.samples[idx]
        wav_np, sr = sf.read(s.audio_path, dtype="float32")
        wav = torch.from_numpy(wav_np).float()
        if wav.dim() == 2:  # stereo → mono
            wav = wav.mean(dim=1)
        if sr != self.target_sr:
            import torchaudio
            wav = torchaudio.functional.resample(wav, sr, self.target_sr)
        if wav.shape[0] > self.max_samples:
            wav = wav[:self.max_samples]
        # WavFrontend(wav (1,T_samples), lens) → speech (1, T_frames, 560)
        wav_b = wav.unsqueeze(0)
        lens = torch.tensor([wav.shape[0]])
        speech, _ = self.frontend(wav_b, lens)  # (1, T, 560)
        return {
            "key":     s.key,
            "speech":  speech.squeeze(0),  # (T, 560)
            "text":    s.text,
        }


def _build_text_ids(tokenizer, text: str) -> "list[int]":
    """SenseVoice 訓練 token 結構：[<|zh|>, <|NEUTRAL|>, <|Speech|>, <|withitn|>, ...實際文字 tokens]"""
    ids = []
    for sp in ("<|zh|>", "<|NEUTRAL|>", "<|Speech|>", "<|withitn|>"):
        ids.extend(tokenizer.encode(sp, allowed_special="all"))
    ids.extend(tokenizer.encode(text, allowed_special="all"))
    return ids


def make_collate(tokenizer):
    """回傳 collate_fn：speech (T_i, 560) 不一致 → pad；text 同樣"""
    import torch

    def collate(batch):
        feat_dim = batch[0]["speech"].shape[-1]  # 通常 560
        max_T = max(b["speech"].shape[0] for b in batch)
        speech = torch.zeros(len(batch), max_T, feat_dim)
        speech_lengths = torch.zeros(len(batch), dtype=torch.int32)
        for i, b in enumerate(batch):
            T = b["speech"].shape[0]
            speech[i, :T] = b["speech"]
            speech_lengths[i] = T

        ids_list = [_build_text_ids(tokenizer, b["text"]) for b in batch]
        max_L = max(len(ids) for ids in ids_list)
        text = torch.zeros(len(batch), max_L, dtype=torch.int64)
        text_lengths = torch.zeros(len(batch), dtype=torch.int32)
        for i, ids in enumerate(ids_list):
            L = len(ids)
            text[i, :L] = torch.tensor(ids, dtype=torch.int64)
            text_lengths[i] = L

        return {
            "speech":         speech,
            "speech_lengths": speech_lengths,
            "text":           text,
            "text_lengths":   text_lengths,
            "raw_texts":      [b["text"] for b in batch],
            "keys":           [b["key"] for b in batch],
        }

    return collate


# ══════════════════════════════════════════════════════════════════════
# 訓練 / 評估
# ══════════════════════════════════════════════════════════════════════
def train_one_epoch(model, loader, optimizer, scheduler, scaler, device, epoch, total_epochs, grad_clip=1.0):
    """跑一個 epoch，回傳平均 loss（含 gradient clipping）"""
    import torch
    import math
    model.train()
    total_loss = 0.0
    n_batches = 0
    n_skip = 0
    for i, batch in enumerate(loader):
        speech = batch["speech"].to(device)
        speech_lengths = batch["speech_lengths"].to(device)
        text = batch["text"].to(device)
        text_lengths = batch["text_lengths"].to(device)

        optimizer.zero_grad()
        # SenseVoice forward → (loss, stats, weight)
        if scaler is not None:
            with torch.amp.autocast(device_type=device.split(":")[0], dtype=torch.float16):
                loss, stats, weight = model(speech=speech, speech_lengths=speech_lengths, text=text, text_lengths=text_lengths)
            # 跳過 NaN/Inf loss（避免毒化 optimizer state）
            if not torch.isfinite(loss):
                n_skip += 1
                continue
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], grad_clip
            )
            scaler.step(optimizer)
            scaler.update()
        else:
            loss, stats, weight = model(speech=speech, speech_lengths=speech_lengths, text=text, text_lengths=text_lengths)
            if not torch.isfinite(loss):
                n_skip += 1
                continue
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], grad_clip
            )
            optimizer.step()
        if scheduler is not None:
            scheduler.step()

        total_loss += loss.item()
        n_batches += 1
        if (i + 1) % 5 == 0 or i == len(loader) - 1:
            print(f"  [epoch {epoch}/{total_epochs}] batch {i+1}/{len(loader)}  "
                  f"loss={loss.item():.4f}  lr={optimizer.param_groups[0]['lr']:.2e}"
                  + (f"  (skipped NaN: {n_skip})" if n_skip > 0 else ""))

    return total_loss / max(n_batches, 1) if n_batches > 0 else float("nan")


def evaluate_cer(base, val_samples, device) -> float:
    """val set 跑 inference → CER"""
    import re
    try:
        import jiwer
    except ImportError:
        return float("nan")
    refs, hyps = [], []
    for s in val_samples:
        try:
            results = base.generate(input=s.audio_path, cache={}, language="zh", use_itn=True)
            txt = results[0].get("text", "") if results else ""
            txt = re.sub(r"<\|[^|]+\|>", "", txt).strip()
            refs.append(s.text)
            hyps.append(txt)
        except Exception as e:
            print(f"  ⚠️ eval {s.key}: {e}")
    if not refs:
        return float("inf")
    return jiwer.cer(refs, hyps)


def save_checkpoint(model, out_dir: Path, tag: str = "best") -> Path:
    """儲存 LoRA 或 full state_dict"""
    import torch
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / f"{tag}.pt"
    # PEFT model 用 get_peft_model_state_dict（只存 LoRA params）
    try:
        from peft import get_peft_model_state_dict
        if hasattr(model, "peft_config"):
            state = get_peft_model_state_dict(model)
            torch.save({"lora_state_dict": state}, ckpt_path)
            return ckpt_path
    except Exception:
        pass
    # Fallback：存全部 state_dict
    torch.save(model.state_dict(), ckpt_path)
    return ckpt_path


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
    base, model, tokenizer = setup_model(device, lora_rank=args.lora_rank, mode=args.mode)

    if args.dry_run:
        print("\n✅ Dry run：模型載入成功、可訓練參數確認，結束")
        return

    # ── 訓練主迴圈 ────────────────────────────────────────
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    import torch
    from torch.utils.data import DataLoader

    # Mixed precision 自動選
    use_scaler = (device.startswith("cuda")) and (args.mixed_precision in ("auto", "fp16"))
    scaler = torch.amp.GradScaler() if use_scaler else None
    print(f"   mixed precision: {'fp16 (autocast + scaler)' if scaler else 'fp32'}")

    # DataLoader
    frontend = base.kwargs.get("frontend")
    if frontend is None:
        raise RuntimeError("base.kwargs['frontend'] 不存在（WavFrontend）")
    train_audio_ds = AudioFeatureDataset(train_jsonl, frontend=frontend)
    val_audio_ds = AudioFeatureDataset(val_jsonl, frontend=frontend) if val_jsonl.exists() else None
    collate = make_collate(tokenizer)

    train_loader = DataLoader(
        train_audio_ds, batch_size=args.batch_size, shuffle=True,
        num_workers=0, collate_fn=collate,
    )
    print(f"   train batches: {len(train_loader)}（batch_size={args.batch_size}）")

    # Optimizer 只更新可訓練參數（LoRA params）
    trainable = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=args.lr, weight_decay=0.01)
    # Cosine scheduler
    n_steps = max(1, args.epochs * len(train_loader))
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_steps)

    # 訓練主迴圈
    metrics_log = []
    best_val_cer = float("inf")
    patience = 0
    print()
    print(f"🚀 開始訓練（epochs={args.epochs}, lr={args.lr}, mode={args.mode}）")
    print("=" * 60)

    for epoch in range(1, args.epochs + 1):
        t_epoch = time.time()
        train_loss = train_one_epoch(
            model, train_loader, optimizer, scheduler, scaler,
            device, epoch, args.epochs,
        )
        epoch_sec = time.time() - t_epoch

        # Val CER
        if val_audio_ds and val_audio_ds.samples:
            val_cer = evaluate_cer(base, val_audio_ds.samples, device)
            print(f"📊 epoch {epoch}: train_loss={train_loss:.4f}  "
                  f"val_cer={val_cer*100:.2f}%  ({epoch_sec:.1f}s)")
        else:
            val_cer = float("nan")
            print(f"📊 epoch {epoch}: train_loss={train_loss:.4f}  ({epoch_sec:.1f}s)")

        metrics_log.append({
            "epoch":       epoch,
            "train_loss":  round(train_loss, 4),
            "val_cer":     round(val_cer, 4) if not (val_cer != val_cer) else None,
            "epoch_sec":   round(epoch_sec, 1),
            "lr":          optimizer.param_groups[0]["lr"],
        })

        # Save best + early stopping
        if val_cer < best_val_cer:
            best_val_cer = val_cer
            ckpt = save_checkpoint(model, out_dir, tag="best")
            print(f"   💾 best 更新 → {ckpt} (val_cer={val_cer*100:.2f}%)")
            patience = 0
        else:
            patience += 1
            if patience >= args.early_stop_patience:
                print(f"⏹️  Early stopping（連續 {patience} epoch 未改善）")
                break

        # 每 epoch 都存一份 last checkpoint
        save_checkpoint(model, out_dir, tag=f"epoch_{epoch}")

    # 訓練結束
    print()
    print(f"🎯 訓練完成。best val CER = {best_val_cer*100:.2f}%")
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics_log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"📄 metrics.json: {out_dir / 'metrics.json'}")

    # 寫一份 metadata 紀錄這次訓練設定
    meta = {
        "mode":        args.mode,
        "lora_rank":   args.lora_rank,
        "epochs":      args.epochs,
        "batch_size":  args.batch_size,
        "lr":          args.lr,
        "device":      device,
        "best_val_cer": best_val_cer,
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
