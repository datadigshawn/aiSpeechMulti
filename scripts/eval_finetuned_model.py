#!/usr/bin/env python3
"""
Phase 5 B4：fine-tuned 模型評估腳本
=====================================

對 fine-tune 完成的 SenseVoice checkpoint 在 test set 跑 CER，
並與基準（原始 SenseVoice + gemini25pro）對照。

預設流程：
1. 載入指定 checkpoint
2. 對 test.jsonl 中所有段做推論 → 寫到 stt_outputs/{label}/
3. 對該目錄跑 batch_eval CER 比對 GT
4. 與既有的 sensevoice / gemini25pro baseline 對照
5. 寫一份 markdown 報告 + 同時 append 到 cer_history.csv

用法：
    # 評估某個 checkpoint
    python3 scripts/eval_finetuned_model.py \\
        --checkpoint experiments/finetune_runs/sensevoice_lora_v1/best.pt \\
        --label sensevoice_ft_v1

    # 純對照模式（用既有 stt_outputs/{label}/ 已有的結果）
    python3 scripts/eval_finetuned_model.py --label sensevoice_ft_v1 --skip-inference

⚠️ 推論部分需 SenseVoice 環境（funasr）。在沒有 fine-tuned checkpoint 之前，
   可用 --label sensevoice 對既有原始 SenseVoice 結果跑此腳本驗證 pipeline。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

MANIFEST_PATH = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"
STT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "stt_outputs"
DATASET_DIR = PROJECT_ROOT / "experiments" / "finetune_dataset"
REPORTS_DIR = PROJECT_ROOT / "experiments" / "finetune_runs"


# ══════════════════════════════════════════════════════════════════════
# 推論
# ══════════════════════════════════════════════════════════════════════
def _apply_lora(model, checkpoint_path: Path, device: str):
    """把 fine-tuned checkpoint 套進 AutoModel（in-place）。checkpoint 不存在則用原始模型。"""
    import torch
    if not checkpoint_path.exists():
        print(f"   ⚠️ checkpoint 不存在，改用原始 FunAudioLLM/SenseVoiceSmall")
        return
    try:
        state_dict = torch.load(checkpoint_path, map_location=device, weights_only=False)
        if isinstance(state_dict, dict) and "lora_state_dict" in state_dict:
            from peft import LoraConfig, get_peft_model, TaskType, set_peft_model_state_dict
            lora_config = LoraConfig(
                r=32, lora_alpha=64,
                target_modules=["q_proj", "k_proj", "v_proj", "out_proj",
                                "linear_q", "linear_k", "linear_v", "linear_out"],
                lora_dropout=0.05, bias="none",
                task_type=TaskType.FEATURE_EXTRACTION,
            )
            wrapped = get_peft_model(model.model, lora_config)
            set_peft_model_state_dict(wrapped, state_dict["lora_state_dict"])
            model.model = wrapped
            print(f"   ✅ LoRA checkpoint 載入成功")
        else:
            model.model.load_state_dict(state_dict, strict=False)
            print(f"   ✅ full state_dict 載入成功")
    except Exception as e:
        print(f"   ⚠️ 載入 checkpoint 失敗: {e}；改用原始模型繼續")


def _audio_duration_sec(sample: dict, audio_path: str) -> float:
    """取音檔長度（秒）。優先用 funasr jsonl 的 source_len(ms)，否則探測檔案，失敗回 0。"""
    sl = sample.get("source_len")
    if sl:
        return float(sl) / 1000.0
    try:
        import soundfile as sf
        info = sf.info(audio_path)
        return info.frames / info.samplerate
    except Exception:
        return 0.0


def run_inference(
    checkpoint_path: Path,
    test_samples: list[dict],
    out_dir: Path,
    device: str = "auto",
    chunk_sec: int = 45,
) -> dict:
    """
    用 fine-tuned checkpoint 對 test_samples 跑推論，輸出至 out_dir/{id}.txt
    回傳 {success, failed, elapsed_sec}

    chunk_sec: 依長度閘控的 VAD 切段門檻（秒）。音檔 > chunk_sec 才走 fsmn-vad 切段
        （max_single_segment_time=chunk_sec）+ merge_vad，治長段 under-generation；
        短段不切（實測 VAD 對短段反而傷，見 S1a devlog）。0=一律不切（舊行為）。
    """
    try:
        from funasr import AutoModel
        import torch
    except ImportError:
        return {"error": "funasr / torch 未安裝", "success": 0, "failed": len(test_samples)}

    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    print(f"📦 載入 checkpoint: {checkpoint_path} (device={device}, "
          f"chunk_sec={chunk_sec}{'（一律不切）' if chunk_sec <= 0 else f'：>{chunk_sec}s 才切段'})")
    base = AutoModel(model="FunAudioLLM/SenseVoiceSmall", hub="hf",
                     device=device, disable_update=True)
    _apply_lora(base, checkpoint_path, device)

    # 長段專用（VAD 切段）模型：lazy 載入，僅在遇到長段時才建立
    _vad_model = {"m": None}

    def get_vad_model():
        if _vad_model["m"] is None:
            print(f"   ↳ 載入長段 VAD 切段模型（max_single_segment_time={chunk_sec}s）")
            m = AutoModel(model="FunAudioLLM/SenseVoiceSmall", hub="hf",
                          device=device, disable_update=True,
                          vad_model="fsmn-vad",
                          vad_kwargs={"max_single_segment_time": chunk_sec * 1000})
            _apply_lora(m, checkpoint_path, device)
            _vad_model["m"] = m
        return _vad_model["m"]

    out_dir.mkdir(parents=True, exist_ok=True)
    success = failed = 0
    n_chunked = 0
    t0 = time.time()
    for i, s in enumerate(test_samples, 1):
        # 兼容 jsonl 兩種格式：HF (id/audio_filepath) 與 FunASR (key/source)
        sid = s.get("id") or s.get("key", f"unknown_{i}")
        audio_path = s.get("audio_filepath") or s.get("source")
        out_path = out_dir / f"{sid}.txt"
        dur = _audio_duration_sec(s, audio_path)
        use_vad = chunk_sec > 0 and dur > chunk_sec
        if use_vad:
            n_chunked += 1
        try:
            model = get_vad_model() if use_vad else base
            results = model.generate(
                input=audio_path,
                cache={},
                language="zh",
                use_itn=True,
                merge_vad=use_vad,
            )
            if not results:
                txt = ""
            else:
                r0 = results[0]
                txt = r0.get("text", "") if isinstance(r0, dict) else str(r0)
            # SenseVoice 輸出可能含 <emo|> tag，移除
            import re
            txt = re.sub(r"<\|[^|]+\|>", "", txt).strip()
            out_path.write_text(txt, encoding="utf-8")
            success += 1
            tag = " ✂️chunk" if use_vad else ""
            print(f"  [{i:3}/{len(test_samples)}] {sid}: {len(txt)} 字{tag}  {txt[:36]!r}")
        except Exception as e:
            failed += 1
            print(f"  [{i:3}/{len(test_samples)}] {sid}: ❌ {str(e)[:80]}")

    return {
        "success":     success,
        "failed":      failed,
        "chunked":     n_chunked,
        "elapsed_sec": round(time.time() - t0, 1),
    }


# ══════════════════════════════════════════════════════════════════════
# 評估（重用 batch_eval 邏輯）
# ══════════════════════════════════════════════════════════════════════
def evaluate_label(label: str, post_process: str = "") -> dict | None:
    """
    對 stt_outputs/{label}/ 跑 batch_eval，回傳 (raw_cer, final_cer)
    """
    import subprocess
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "experiments" / "llm_correction_poc" / "batch_eval.py"),
        "--manifest", str(MANIFEST_PATH),
        "--stt-cache-dir", str(STT_DIR / label),
        "--engine-label", label,
        "--post-process", post_process,
    ]
    # Windows 預設 subprocess encoding = OEMCP (cp950)，emoji 會炸 UnicodeDecodeError
    # 顯式指定 utf-8 + errors=replace，跨平台都安全
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=600,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print(f"  ⚠️ batch_eval 失敗 ({label}): {(proc.stderr or '')[-200:]}")
        return None
    out = proc.stdout or ""
    raw_cer = final_cer = None
    for line in out.splitlines():
        if "平均 CER raw" in line:
            raw_cer = float(line.split(":")[1].strip().rstrip("%")) / 100
        elif "平均 CER final" in line:
            final_cer = float(line.split(":")[1].strip().rstrip("%")) / 100
    return {"raw_cer": raw_cer, "final_cer": final_cer}


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", help="fine-tuned checkpoint 路徑（.pt 或 .bin）")
    ap.add_argument("--label", required=True, help="輸出子目錄名（stt_outputs/{label}/）")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--skip-inference", action="store_true",
                    help="跳過推論、直接用既有 stt_outputs/{label}/ 跑評估")
    ap.add_argument("--test-jsonl", default=str(DATASET_DIR / "test.jsonl"),
                    help="test set jsonl 路徑（B1 產出）")
    ap.add_argument("--baselines", default="sensevoice,gemini25pro",
                    help="對照基準引擎（逗號分隔）")
    ap.add_argument("--chunk-sec", type=int, default=45,
                    help="依長度閘控的 VAD 切段門檻（秒）：音檔 >此值才切段（治長段 under-generation）；"
                         "短段不切（VAD 對短段反而傷）。0=一律不切（舊行為）")
    args = ap.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── 推論（除非 skip）──────────────────────────────────
    if not args.skip_inference:
        test_path = Path(args.test_jsonl)
        if not test_path.is_absolute():
            test_path = PROJECT_ROOT / test_path
        if not test_path.exists():
            print(f"❌ {test_path} 不存在，請先跑 build_finetune_dataset.py")
            return
        with open(test_path, encoding="utf-8") as f:
            test_samples = [json.loads(line) for line in f]
        print(f"📋 test set: {len(test_samples)} 段")

        ckpt_path = Path(args.checkpoint) if args.checkpoint else Path("(none)")
        out_dir = STT_DIR / args.label
        info = run_inference(ckpt_path, test_samples, out_dir, device=args.device,
                             chunk_sec=args.chunk_sec)
        print()
        print(f"📊 推論結果: success={info.get('success')}/{len(test_samples)} "
              f"failed={info.get('failed')} 耗時={info.get('elapsed_sec')}s")
    else:
        print(f"⏭️ 跳過推論，直接評估 stt_outputs/{args.label}/")

    # ── 評估 ──────────────────────────────────────────────
    print()
    print("🔬 跑 batch_eval CER 對照...")
    rows = []
    # 1. 評估 fine-tuned 模型
    for pp in ["", "car_norm,dict"]:
        r = evaluate_label(args.label, pp)
        if r:
            rows.append({
                "model":       args.label,
                "post_process": pp or "raw",
                "raw_cer":     r["raw_cer"],
                "final_cer":   r["final_cer"],
            })

    # 2. 評估 baselines
    for base_label in args.baselines.split(","):
        base_label = base_label.strip()
        if not base_label:
            continue
        for pp in ["", "car_norm,dict"]:
            r = evaluate_label(base_label, pp)
            if r:
                rows.append({
                    "model":       base_label,
                    "post_process": pp or "raw",
                    "raw_cer":     r["raw_cer"],
                    "final_cer":   r["final_cer"],
                })

    # ── 輸出對照表 ────────────────────────────────────────
    print()
    print("━" * 65)
    print(f"{'model':<25} {'pp':<18} {'raw CER':>10} {'final CER':>12}")
    print("━" * 65)
    for r in rows:
        print(
            f"{r['model']:<25} {r['post_process']:<18} "
            f"{r['raw_cer']*100:>8.2f}%  {r['final_cer']*100:>10.2f}%"
        )

    # ── 寫 markdown 報告 ──────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = REPORTS_DIR / f"eval_{args.label}_{ts}.md"
    md = [
        f"# fine-tune 評估報告 — {args.label}",
        "",
        f"- 時間：{ts}",
        f"- checkpoint：{args.checkpoint or '（無、用原始模型）'}",
        f"- 對照基準：{args.baselines}",
        "",
        "## CER 對照",
        "",
        "| model | post_process | raw CER | final CER |",
        "|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            f"| {r['model']} | {r['post_process']} | "
            f"{r['raw_cer']*100:.2f}% | {r['final_cer']*100:.2f}% |"
        )
    md_path.write_text("\n".join(md), encoding="utf-8")
    print()
    print(f"📄 報告: {md_path}")


if __name__ == "__main__":
    main()
