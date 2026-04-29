#!/usr/bin/env python3
"""
音訊預處理工具（baseline 評測用）
=====================================

對 manifest 中所有音檔做預處理，產出可重跑 STT 的標準化版本。

預設處理：
1. **resample**     ─ 統一 16kHz / mono / 16-bit PCM WAV
2. **loudnorm**     ─ ffmpeg EBU R128 音量正規化（避免過小聲漏字）
3. (可選) **bandpass** ─ 窄頻無線電帶通（300~3400Hz，模擬電話頻寬清乾淨）
4. (可選) **highpass** ─ 高通去低頻底噪

不切段、不降噪（避免過度處理導致失真，保留與 GT 對齊）。

用法：
    # 對 manifest 所有音檔做 loudnorm
    python3 scripts/audio_preprocess.py

    # 含 bandpass（窄頻無線電場景）
    python3 scripts/audio_preprocess.py --bandpass

    # 自訂輸出目錄
    python3 scripts/audio_preprocess.py --out experiments/golden_dataset/audio_v2
"""

from __future__ import annotations

import argparse
import csv
import shlex
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"
DEFAULT_OUT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "audio_preprocessed"


def build_filter_chain(bandpass: bool, highpass: bool) -> str:
    """組 ffmpeg -af filter chain"""
    chain = []
    # 高通 80Hz：去除低頻底噪（如電源嗡鳴、空調聲）
    if highpass:
        chain.append("highpass=f=80")
    # 帶通 300~3400Hz：模擬電話頻寬，對窄頻無線電通話有用
    # 與 highpass 互斥（chain 會重疊）
    if bandpass and not highpass:
        chain.append("highpass=f=300")
        chain.append("lowpass=f=3400")
    elif bandpass:
        # 已有 highpass=80，再加上界 lowpass
        chain.append("lowpass=f=3400")
    # loudnorm（EBU R128 podcast 標準）：I 目標響度 / TP 真峰值 / LRA 動態範圍
    chain.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    return ",".join(chain)


def preprocess_one(in_path: Path, out_path: Path, filter_chain: str, sample_rate: int = 16000) -> tuple[bool, str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(in_path),
        "-af", filter_chain,
        "-ar", str(sample_rate),
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return False, proc.stderr.splitlines()[-1] if proc.stderr else "ffmpeg failed"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(MANIFEST_PATH))
    ap.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="輸出目錄")
    ap.add_argument("--bandpass", action="store_true", help="加 300~3400Hz 帶通（窄頻無線電場景）")
    ap.add_argument("--highpass", action="store_true", help="加 80Hz 高通（去低頻底噪）")
    ap.add_argument("--sample-rate", type=int, default=16000)
    ap.add_argument("--force", action="store_true", help="強制重做（覆寫已存在）")
    args = ap.parse_args()

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = PROJECT_ROOT / manifest_path

    rows = []
    with open(manifest_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get("has_gt") == "Y"]

    filter_chain = build_filter_chain(args.bandpass, args.highpass)
    print(f"🎧 音訊預處理（{len(rows)} 段）")
    print(f"   filter chain: {filter_chain}")
    print(f"   輸出目錄:     {out_dir}")
    print(f"   target SR:    {args.sample_rate}Hz mono PCM16")
    print()

    success = 0
    skipped = 0
    failed = 0
    total_t = 0.0

    for i, row in enumerate(rows, 1):
        sid = row["id"]
        in_path = PROJECT_ROOT / row["audio_file"]
        out_path = out_dir / in_path.name

        if not in_path.exists():
            print(f"[{i:3}/{len(rows)}] {sid} ❌ source not found")
            failed += 1
            continue
        if out_path.exists() and not args.force:
            print(f"[{i:3}/{len(rows)}] {sid} ⏭️  cached")
            skipped += 1
            continue

        t0 = time.time()
        ok, err = preprocess_one(in_path, out_path, filter_chain, args.sample_rate)
        elapsed = time.time() - t0
        total_t += elapsed

        if ok:
            success += 1
            size_kb = out_path.stat().st_size / 1024
            print(f"[{i:3}/{len(rows)}] {sid} ✅ {elapsed:4.1f}s  {size_kb:6.1f}KB")
        else:
            failed += 1
            print(f"[{i:3}/{len(rows)}] {sid} ❌ {elapsed:4.1f}s  err: {err[:120]}")

    print()
    print(f"📊 預處理結果：success={success}  skipped={skipped}  failed={failed}")
    print(f"   總耗時：{total_t:.1f}s")
    print(f"   輸出：{out_dir}")


if __name__ == "__main__":
    main()
