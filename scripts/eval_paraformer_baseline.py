#!/usr/bin/env python3
"""
Paraformer-zh 零 fine-tune 基準評估
===================================
目的：在**決定要不要投入 Paraformer fine-tune 之前**，先用預訓練 Paraformer-zh
在凍結的 held-out test（eval_set.json）上跑一遍，與 SenseVoice 做 apples-to-apples
比較。零 fine-tune、零標註。

紀律（延續本專案評測底盤）：
- 用與 batch_eval 相同的 normalize_for_cer 計分（繁簡 opencc、剝講者標記）→ 數字可直接比。
- 輸出 batch_eval 相容 JSON（samples[]: id/event_type/cer_raw/cer_final/gt_chars），
  之後可 `python scripts/cer_stats.py compare <sensevoice_json> <此 json>` 做配對檢定。

注意：
- Paraformer-zh 是 16kHz 模型；我們 8kHz 窄頻音檔 FunASR 會自動重採樣（與 SenseVoice 同）。
- 長段用 fsmn-vad 切（Paraformer 標準用法），對齊 SenseVoice 的 chunk_sec=45 推論。
- 首次執行會下載 funasr/paraformer-zh（~1GB），需網路。

用法：
    python scripts/eval_paraformer_baseline.py
    python scripts/eval_paraformer_baseline.py --no-vad --out experiments/llm_correction_poc/paraformer_baseline.json
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

EVAL_SET = PROJECT_ROOT / "experiments" / "golden_dataset" / "eval_set.json"
MANIFEST = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"

_TAG_RE = re.compile(r"<\|[^|]*\|>")


def strip_tags(s: str) -> str:
    return _TAG_RE.sub("", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="funasr/paraformer-zh",
                    help="Paraformer 模型 id（hub=hf）")
    ap.add_argument("--out", default="experiments/llm_correction_poc/paraformer_baseline.json")
    ap.add_argument("--vad", dest="vad", action="store_true", default=True,
                    help="長段用 fsmn-vad 切（預設開，對齊 SenseVoice chunk）")
    ap.add_argument("--no-vad", dest="vad", action="store_false")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 段（除錯用）")
    args = ap.parse_args()

    # 用 batch_eval 同款計分（apples-to-apples）
    from experiments.llm_correction_poc.batch_eval import normalize_for_cer
    import jiwer

    # test ids + manifest
    test_ids = json.loads(EVAL_SET.read_text(encoding="utf-8"))["ids"]
    rows = {}
    with open(MANIFEST, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows[r["id"]] = r
    items = [(sid, rows[sid]) for sid in test_ids if sid in rows]
    if args.limit:
        items = items[:args.limit]
    print(f"📋 評估 {len(items)} 段（eval_set.json held-out test）")

    # device
    import torch
    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else (
            "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
    else:
        device = args.device
    # Paraformer 的 VAD/CIF timestamp 路徑用 float64，Apple MPS 不支援 → 降到 CPU
    if device == "mps":
        print("   ⚠️ Paraformer 在 MPS 會踩 float64 限制 → 自動改用 CPU（cuda/3090 不受影響）")
        device = "cpu"

    from funasr import AutoModel
    print(f"📦 載入 {args.model} (device={device}, vad={'on' if args.vad else 'off'})…")
    kw = dict(model=args.model, hub="hf", device=device, disable_update=True)
    if args.vad:
        kw["vad_model"] = "fsmn-vad"
    model = AutoModel(**kw)

    samples = []
    t0 = time.time()
    for sid, r in items:
        audio = r["audio_file"]
        audio = audio if os.path.isabs(audio) else str(PROJECT_ROOT / audio)
        gt = Path(r["gt_file"] if os.path.isabs(r["gt_file"]) else PROJECT_ROOT / r["gt_file"]).read_text(encoding="utf-8-sig")
        try:
            out = model.generate(input=audio)
            hyp = strip_tags(out[0]["text"])
        except Exception as e:
            print(f"  ⚠️ {sid} 推論失敗: {e}")
            hyp = ""
        ref_n = normalize_for_cer(gt)
        hyp_n = normalize_for_cer(hyp)
        cer = jiwer.cer(ref_n, hyp_n) if ref_n else 0.0
        samples.append({
            "id": sid,
            "event_type": r.get("event_type", ""),
            "cer_raw": round(cer, 6),
            "cer_final": round(cer, 6),   # 無後處理，final=raw
            "gt_chars": len(ref_n),
        })
        print(f"  {sid:<8} {r.get('event_type',''):<10} cer={cer*100:5.1f}%")

    import statistics
    macro = statistics.mean(s["cer_raw"] for s in samples) if samples else 0.0
    micro = (sum(s["cer_raw"] * s["gt_chars"] for s in samples) /
             max(sum(s["gt_chars"] for s in samples), 1))
    report = {
        "engine_label": "paraformer_zh_baseline",
        "post_process_stages": [],
        "sample_count": len(samples),
        "success_count": sum(1 for s in samples if s["gt_chars"] > 0),
        "avg_cer_raw": round(macro, 6),
        "avg_cer_final": round(macro, 6),
        "vad": args.vad,
        "samples": samples,
    }
    out_path = Path(args.out if os.path.isabs(args.out) else PROJECT_ROOT / args.out)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*50}")
    print(f"Paraformer-zh 基準（{len(samples)} 段, {time.time()-t0:.0f}s）")
    print(f"  MACRO CER = {macro*100:.2f}%   MICRO CER = {micro*100:.2f}%")
    print(f"  參考：SenseVoice-ft v2 fresh（同 21 段）raw ≈ 32%（見 v2 快取記憶）")
    print(f"  → 輸出 {out_path}")
    print(f"  → 配對檢定：python scripts/cer_stats.py compare <sensevoice_json> {out_path}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
