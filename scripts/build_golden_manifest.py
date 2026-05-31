#!/usr/bin/env python3
"""
黃金語料集 Manifest 自動產生腳本
================================

掃描 experiments/golden_dataset/ 內的 audio/ 與 ground_truth/，
自動配對並產出 manifest.csv 索引清單。

配對規則：
    audio/001_daily_xxx.wav  ↔  ground_truth/001_daily_xxx.txt
    （檔名相同，副檔名不同）

輸出 manifest.csv 欄位：
    id              - 順序編號（從檔名解析，例如 "001"）
    event_type      - 事件類型（從檔名解析，例如 "daily"）
    audio_file      - 音檔相對路徑
    gt_file         - GT 文字檔相對路徑
    duration_sec    - 音檔時長（秒）
    gt_char_count   - GT 字數（不含標點與空白）
    gt_speaker_lines - GT 講者行數
    audio_size_kb   - 音檔大小（KB）
    audio_format    - 音檔格式（wav/mp3/m4a...）
    has_gt          - 是否已有對應的 GT（True/False）
    notes           - 備註欄位（手動編輯用，腳本會保留既有值）

用法：
    # 基本使用
    python3 scripts/build_golden_manifest.py

    # 指定不同的目錄
    python3 scripts/build_golden_manifest.py \\
        --audio-dir experiments/golden_dataset/audio \\
        --gt-dir experiments/golden_dataset/ground_truth \\
        --output experiments/golden_dataset/manifest.csv

    # 只列出未配對的音檔（找出還沒寫 GT 的）
    python3 scripts/build_golden_manifest.py --list-missing
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = PROJECT_ROOT / "experiments" / "golden_dataset"

# ── 支援的音檔格式 ─────────────────────────────────────────────────
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}

# ── 檔名解析正則 ───────────────────────────────────────────────────
# 範例:
#   001_daily_UltraLog063_20260321_154513.wav     ← 原始批次（3 位數字）
#   G0001_emergency_席位1_2025122_192236.wav      ← 後續批次（字母前綴 + 4 位數字）
# 接受兩種：純數字 ≥3 位，或字母前綴後接 ≥3 位數字
FILENAME_PATTERN = re.compile(r"^([A-Z]?\d{3,4})_(\w+?)_(.+)$")

# 已知事件類型（用於驗證）
KNOWN_EVENT_TYPES = {"daily", "door", "track", "emergency", "control"}


def parse_filename(filename: str) -> Optional[dict]:
    """解析檔名取得 id 與 event_type"""
    stem = Path(filename).stem
    match = FILENAME_PATTERN.match(stem)
    if not match:
        return None
    return {
        "id": match.group(1),
        "event_type": match.group(2),
        "rest": match.group(3),
        "stem": stem,
    }


def get_audio_duration(audio_path: Path) -> Optional[float]:
    """嘗試取得音檔時長（用 soundfile 或 wave）"""
    try:
        import soundfile as sf
        info = sf.info(str(audio_path))
        return round(info.duration, 2)
    except Exception:
        pass
    try:
        import wave
        with wave.open(str(audio_path), "rb") as wf:
            return round(wf.getnframes() / wf.getframerate(), 2)
    except Exception:
        return None


def count_gt_chars(gt_path: Path) -> tuple[int, int]:
    """計算 GT 字數（去除標點/空白/講者標記）與講者行數"""
    if not gt_path.exists():
        return 0, 0
    text = gt_path.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    speaker_lines = sum(1 for ln in lines if re.match(r"^[A-Z?]:\s*", ln))

    # 去除講者標記
    clean = re.sub(r"^[A-Z?]:\s*", "", text, flags=re.MULTILINE)
    # 去除標點與空白
    clean = re.sub(r"[\s,，。.、:：;；!?！？\-—()（）\"'\u201c\u201d\[\]【】]+", "", clean)
    return len(clean), speaker_lines


def load_existing_notes(manifest_path: Path) -> dict[str, str]:
    """從現有 manifest.csv 載入 notes 欄位（保留人工編輯內容）"""
    notes = {}
    if not manifest_path.exists():
        return notes
    try:
        with open(manifest_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fid = row.get("id", "")
                note = row.get("notes", "")
                if fid and note:
                    notes[fid] = note
    except Exception:
        pass
    return notes


def scan_dataset(audio_dir: Path, gt_dir: Path, existing_notes: dict[str, str]) -> list[dict]:
    """掃描音檔與 GT，產出記錄清單"""
    if not audio_dir.exists():
        print(f"❌ audio 目錄不存在: {audio_dir}")
        return []

    rows = []
    audio_files = sorted(
        [f for f in audio_dir.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS]
    )

    for audio_path in audio_files:
        parsed = parse_filename(audio_path.name)
        if not parsed:
            print(f"⚠️  跳過格式不符的音檔: {audio_path.name}")
            continue

        # 對應的 GT 檔
        gt_path = gt_dir / f"{parsed['stem']}.txt"
        has_gt = gt_path.exists()

        duration = get_audio_duration(audio_path)
        gt_chars, speaker_lines = count_gt_chars(gt_path)

        row = {
            "id": parsed["id"],
            "event_type": parsed["event_type"],
            "audio_file": str(audio_path.relative_to(PROJECT_ROOT)),
            "gt_file": str(gt_path.relative_to(PROJECT_ROOT)),
            "duration_sec": duration if duration else "",
            "gt_char_count": gt_chars,
            "gt_speaker_lines": speaker_lines,
            "audio_size_kb": round(audio_path.stat().st_size / 1024, 1),
            "audio_format": audio_path.suffix.lstrip("."),
            "has_gt": "Y" if has_gt else "N",
            "notes": existing_notes.get(parsed["id"], ""),
        }

        # 驗證事件類型
        if parsed["event_type"] not in KNOWN_EVENT_TYPES:
            row["notes"] = (row["notes"] + " [⚠️ unknown event_type]").strip()

        rows.append(row)

    return rows


def write_manifest(rows: list[dict], output_path: Path) -> None:
    """寫出 manifest CSV"""
    if not rows:
        print("⚠️  沒有資料可寫入")
        return

    fieldnames = [
        "id", "event_type", "audio_file", "gt_file",
        "duration_sec", "gt_char_count", "gt_speaker_lines",
        "audio_size_kb", "audio_format", "has_gt", "notes",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def print_stats(rows: list[dict]) -> None:
    """列印統計摘要"""
    if not rows:
        return
    total = len(rows)
    with_gt = sum(1 for r in rows if r["has_gt"] == "Y")
    by_type: dict[str, int] = {}
    by_type_with_gt: dict[str, int] = {}
    total_duration = 0.0
    total_gt_chars = 0

    for r in rows:
        et = r["event_type"]
        by_type[et] = by_type.get(et, 0) + 1
        if r["has_gt"] == "Y":
            by_type_with_gt[et] = by_type_with_gt.get(et, 0) + 1
        if isinstance(r["duration_sec"], (int, float)):
            total_duration += r["duration_sec"]
        total_gt_chars += r["gt_char_count"]

    print()
    print("═" * 60)
    print("📊 黃金語料集統計")
    print("═" * 60)
    print(f"   總段數:         {total}")
    print(f"   已有 GT:        {with_gt} / {total} ({with_gt*100//max(total,1)}%)")
    print(f"   總時長:         {total_duration:.1f}s ({total_duration/60:.1f} 分鐘)")
    print(f"   GT 總字數:      {total_gt_chars}")
    print()
    print("   ── 依事件類型分佈 ──")
    for et in sorted(by_type.keys()):
        with_gt_count = by_type_with_gt.get(et, 0)
        print(f"   {et:12} {by_type[et]:3} 段  (已標 {with_gt_count:3})")


def list_missing(rows: list[dict]) -> None:
    """列出尚未配對 GT 的音檔"""
    missing = [r for r in rows if r["has_gt"] == "N"]
    if not missing:
        print("✅ 所有音檔都已有對應 GT")
        return
    print(f"⚠️  尚有 {len(missing)} 個音檔未標註 GT：")
    for r in missing:
        print(f"   - {r['audio_file']}")
        print(f"     需建立: {r['gt_file']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--audio-dir", default=str(DEFAULT_DATASET_DIR / "audio"))
    p.add_argument("--gt-dir", default=str(DEFAULT_DATASET_DIR / "ground_truth"))
    p.add_argument("--output", default=str(DEFAULT_DATASET_DIR / "manifest.csv"))
    p.add_argument("--list-missing", action="store_true",
                   help="只列出尚未配對 GT 的音檔，不寫 manifest")
    args = p.parse_args()

    audio_dir = Path(args.audio_dir)
    gt_dir = Path(args.gt_dir)
    output = Path(args.output)

    print(f"🔍 掃描黃金語料集")
    print(f"   audio dir: {audio_dir}")
    print(f"   gt dir:    {gt_dir}")
    print()

    existing_notes = load_existing_notes(output)
    rows = scan_dataset(audio_dir, gt_dir, existing_notes)

    if args.list_missing:
        list_missing(rows)
        return

    write_manifest(rows, output)
    print(f"✅ Manifest 已產生: {output}")
    print(f"   共 {len(rows)} 筆記錄")

    print_stats(rows)

    # 列出未標註的
    missing = [r for r in rows if r["has_gt"] == "N"]
    if missing:
        print()
        print(f"⚠️  尚有 {len(missing)} 個音檔未標註 GT")
        print(f"   執行 `python3 scripts/build_golden_manifest.py --list-missing` 查看清單")


if __name__ == "__main__":
    main()
