#!/usr/bin/env python3
"""
Whisper baseline 評估
====================
對 test.jsonl 跑 Whisper inference，輸出到 stt_outputs/{label}/，
之後可用 experiments/llm_correction_poc/batch_eval.py 算 CER。

用法：
    python3 scripts/eval_whisper_baseline.py --model turbo
    python3 scripts/eval_whisper_baseline.py --model large-v3 --label whisper_large_v3
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_TEST_JSONL = PROJECT_ROOT / "experiments" / "finetune_dataset" / "test.jsonl"
STT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "stt_outputs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="turbo", help="whisper model size: turbo / medium / large-v3")
    ap.add_argument("--label", default=None,
                    help="輸出子目錄名（預設 whisper_{model}）")
    ap.add_argument("--test-jsonl", default=str(DEFAULT_TEST_JSONL))
    ap.add_argument("--language", default="zh")
    ap.add_argument("--use-vocabulary", action="store_true", default=True,
                    help="使用 master_vocabulary.csv 產生 initial_prompt（預設 on）")
    args = ap.parse_args()

    label = args.label or f"whisper_{args.model.replace('-', '_')}"
    out_dir = STT_DIR / label
    out_dir.mkdir(parents=True, exist_ok=True)

    test_path = Path(args.test_jsonl)
    if not test_path.is_absolute():
        test_path = PROJECT_ROOT / test_path
    with open(test_path, encoding="utf-8") as f:
        samples = [json.loads(line) for line in f]
    total_dur = sum(s.get("source_len", 0) / 1000 for s in samples)
    print(f"📋 test set: {len(samples)} 段 / 總長 {total_dur:.1f}s ({total_dur/60:.1f}分)")
    print(f"🎯 model: whisper {args.model}")
    print(f"📁 out: {out_dir}")
    print()

    from scripts.models.model_whisper import transcribe_with_whisper

    t0 = time.time()
    success = failed = 0
    for i, s in enumerate(samples, 1):
        sid = s.get("id") or s.get("key", f"unknown_{i}")
        audio_path = s.get("audio_filepath") or s.get("source")
        out_path = out_dir / f"{sid}.txt"
        try:
            ti = time.time()
            text = transcribe_with_whisper(
                str(audio_path),
                model_size=args.model,
                use_vocabulary=args.use_vocabulary,
                language=args.language,
            )
            out_path.write_text(text or "", encoding="utf-8")
            success += 1
            elapsed_i = time.time() - ti
            print(f"  [{i:3}/{len(samples)}] {sid}: {len(text or ''):>4} 字 / {elapsed_i:5.1f}s  {(text or '')[:50]!r}")
        except Exception as e:
            failed += 1
            print(f"  [{i:3}/{len(samples)}] {sid}: ❌ {str(e)[:120]}")

    elapsed = time.time() - t0
    rtf = elapsed / total_dur if total_dur else 0
    print()
    print(f"✅ done: success={success}, failed={failed}")
    print(f"   耗時 {elapsed:.1f}s ({elapsed/60:.1f}分) | RTF={rtf:.2f}x")
    print()
    print(f"📊 評估 CER（下一步）：")
    print(f"   python3 experiments/llm_correction_poc/batch_eval.py \\")
    print(f"     --manifest experiments/golden_dataset/manifest.csv \\")
    print(f"     --stt-cache-dir {out_dir.relative_to(PROJECT_ROOT)} \\")
    print(f"     --engine-label {label}")


if __name__ == "__main__":
    main()
