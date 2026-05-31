#!/usr/bin/env python3
"""
Phase 5 B1：fine-tune 訓練資料 pipeline
==========================================

讀 manifest + ground_truth + (可選) DB 累積的人工修正，整理成可訓練格式：
- 預設輸出：HuggingFace `audio + text` jsonl（給 transformers / Whisper LoRA 用）
- 可選：FunASR 原生格式 jsonl（給 SenseVoice fine-tune 用）
- 80/10/10 train/val/test 切分（**依事件類型 stratified split**）

清理：
- 移除 GT 講者標記（B: / H: / G: / T: / ?:）
- 移除元描述（[noise]、(沉默 N 秒) 等）
- 保留實質字元（含標點、含術語）

用法：
    # 預設（HF 格式 + 預設輸出目錄）
    python3 scripts/build_finetune_dataset.py

    # FunASR 格式
    python3 scripts/build_finetune_dataset.py --format funasr

    # 含 DB 人工修正版本（優先於原始 GT）
    python3 scripts/build_finetune_dataset.py --include-corrections

    # 自訂輸出目錄與切分比例
    python3 scripts/build_finetune_dataset.py --out experiments/finetune_v1 \\
        --split 0.7 0.15 0.15 --seed 42
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

# Windows cp950 OEMCP 不能 encode emoji，強制 stdout/stderr 用 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

MANIFEST_PATH = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"
DB_PATH = PROJECT_ROOT / "data" / "aiSpeechMulti.db"
DEFAULT_OUT = PROJECT_ROOT / "experiments" / "finetune_dataset"


# ══════════════════════════════════════════════════════════════════════
# GT 清理
# ══════════════════════════════════════════════════════════════════════
def clean_gt_for_training(text: str) -> str:
    """
    移除訓練時不該學的雜訊（講者標記、元描述），保留實質字元。
    與 normalize_for_cer 不同：訓練要保留標點、術語完整。
    """
    if not text:
        return ""
    # 移除「[B:] [H:] [G:] [T:] [?:]」這類講者標記（行首）
    text = re.sub(r"^[A-Z?]:\s*", "", text, flags=re.MULTILINE)
    # 移除元描述標註：[noise]、[unclear]、(沉默 N 秒) 等
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"[\(（]沉默\s*[\d一二三四五六七八九十]+\s*秒?[\)）]", "", text)
    text = re.sub(r"[\(（](?:笑聲|咳嗽|雜音|noise|laughter|cough|unclear|inaudible)[\)）]", "", text)
    # 多重換行 → 單一空格
    text = re.sub(r"\s*\n\s*", " ", text)
    # 移除多重空白
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ══════════════════════════════════════════════════════════════════════
# 資料載入
# ══════════════════════════════════════════════════════════════════════
def load_manifest() -> list[dict]:
    rows = []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("has_gt") == "Y":
                rows.append(row)
    return rows


def load_corrections_map() -> dict[str, str]:
    """
    從 DB 讀人工修正版本（若有）。
    回傳 {audio_filename: corrected_text}
    """
    if not DB_PATH.exists():
        return {}
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT a.original_filename, t.corrected_transcript
        FROM transcriptions t
        JOIN audio_files a ON a.id = t.audio_file_id
        WHERE t.corrected_transcript IS NOT NULL
    """).fetchall()
    conn.close()
    return {r["original_filename"]: r["corrected_transcript"] for r in rows}


# ══════════════════════════════════════════════════════════════════════
# Stratified split
# ══════════════════════════════════════════════════════════════════════
def stratified_split(
    samples: list[dict],
    ratios: tuple[float, float, float] = (0.8, 0.1, 0.1),
    seed: int = 42,
) -> tuple[list[dict], list[dict], list[dict]]:
    """依 event_type 分層切分，確保各類在 train/val/test 都有合理分佈"""
    rng = random.Random(seed)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        by_type[s["event_type"]].append(s)

    train, val, test = [], [], []
    for et, items in by_type.items():
        items_shuffled = items[:]
        rng.shuffle(items_shuffled)
        n = len(items_shuffled)
        n_train = int(n * ratios[0])
        n_val = int(n * ratios[1])
        # 至少各 split 1 個（事件類型樣本太少時）
        if n >= 3:
            n_train = max(1, n_train)
            n_val = max(1, n_val)
        train.extend(items_shuffled[:n_train])
        val.extend(items_shuffled[n_train:n_train + n_val])
        test.extend(items_shuffled[n_train + n_val:])

    return train, val, test


# ══════════════════════════════════════════════════════════════════════
# 輸出格式
# ══════════════════════════════════════════════════════════════════════
def to_hf_record(sample: dict, audio_path: Path, text: str) -> dict:
    """HuggingFace `audio + text` 格式"""
    return {
        "id":              sample["id"],
        "event_type":      sample["event_type"],
        "audio_filepath":  str(audio_path),
        "text":            text,
        "duration":        float(sample.get("duration_sec") or 0),
        "source":          sample.get("notes", ""),
    }


def to_funasr_record(sample: dict, audio_path: Path, text: str) -> dict:
    """FunASR 原生格式：key / source / target / source_len / target_len"""
    duration_ms = int(float(sample.get("duration_sec") or 0) * 1000)
    return {
        "key":         sample["id"],
        "source":      str(audio_path),
        "source_len":  duration_ms,
        "target":      text,
        "target_len":  len(text),
        "event_type":  sample["event_type"],
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ══════════════════════════════════════════════════════════════════════
# 統計
# ══════════════════════════════════════════════════════════════════════
def print_split_stats(name: str, records: list[dict], format_type: str):
    if not records:
        print(f"  {name:<6}: 0 段")
        return
    by_et: dict[str, int] = defaultdict(int)
    total_chars = 0
    total_dur = 0.0
    for r in records:
        et = r.get("event_type", "?")
        by_et[et] += 1
        if format_type == "hf":
            total_chars += len(r.get("text", ""))
            total_dur += r.get("duration", 0)
        else:
            total_chars += r.get("target_len", 0)
            total_dur += (r.get("source_len", 0) / 1000)
    parts = [f"{et}={n}" for et, n in sorted(by_et.items())]
    print(f"  {name:<6}: {len(records):>3} 段 | {total_dur:6.1f}s | {total_chars:>5} 字 | "
          + ", ".join(parts))


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="輸出目錄")
    ap.add_argument("--format", choices=["hf", "funasr"], default="hf",
                    help="輸出格式：hf（HuggingFace）或 funasr（FunASR 原生）")
    ap.add_argument("--include-corrections", action="store_true",
                    help="包含 DB 累積的人工修正版本（優先於原始 GT）")
    ap.add_argument("--split", type=float, nargs=3, default=[0.8, 0.1, 0.1],
                    metavar=("TRAIN", "VAL", "TEST"),
                    help="train/val/test 比例（預設 0.8 0.1 0.1）")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir

    print(f"🏗️  Phase 5 B1: 訓練資料 Pipeline")
    print(f"   manifest:    {MANIFEST_PATH}")
    print(f"   format:      {args.format}")
    print(f"   include corrections: {args.include_corrections}")
    print(f"   split:       train={args.split[0]} val={args.split[1]} test={args.split[2]}")
    print(f"   seed:        {args.seed}")
    print(f"   out:         {out_dir}")
    print()

    # ── 載入 ─────────────────────────────────────────────
    manifest = load_manifest()
    corrections = load_corrections_map() if args.include_corrections else {}
    if corrections:
        print(f"📝 從 DB 讀到 {len(corrections)} 筆人工修正（將優先使用）")

    # ── 整理 samples ─────────────────────────────────────
    samples = []
    skipped = 0
    for row in manifest:
        sid = row["id"]
        audio_path = PROJECT_ROOT / row["audio_file"]
        gt_path = PROJECT_ROOT / row["gt_file"]
        if not audio_path.exists() or not gt_path.exists():
            print(f"⚠️ {sid}: audio 或 GT 缺失，略過")
            skipped += 1
            continue

        # 優先使用人工修正版本（若有）
        fname = audio_path.name
        if fname in corrections and corrections[fname]:
            raw_text = corrections[fname]
            row["_source"] = "corrected"
        else:
            raw_text = gt_path.read_text(encoding="utf-8")
            row["_source"] = "gt"

        cleaned = clean_gt_for_training(raw_text)
        if not cleaned:
            print(f"⚠️ {sid}: 清理後文字為空，略過")
            skipped += 1
            continue

        row["_audio_path"] = audio_path
        row["_text"] = cleaned
        samples.append(row)

    print(f"📋 可訓練樣本: {len(samples)} 段（略過 {skipped} 段）")
    print()

    # ── Stratified split ─────────────────────────────────
    train, val, test = stratified_split(
        samples,
        ratios=tuple(args.split),
        seed=args.seed,
    )

    # ── 轉格式 + 寫檔 ─────────────────────────────────────
    builder = to_hf_record if args.format == "hf" else to_funasr_record
    train_records = [builder(s, s["_audio_path"], s["_text"]) for s in train]
    val_records   = [builder(s, s["_audio_path"], s["_text"]) for s in val]
    test_records  = [builder(s, s["_audio_path"], s["_text"]) for s in test]

    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "train.jsonl", train_records)
    write_jsonl(out_dir / "val.jsonl", val_records)
    write_jsonl(out_dir / "test.jsonl", test_records)

    # ── 統計 ─────────────────────────────────────────────
    print(f"📊 Split 統計")
    print_split_stats("train", train_records, args.format)
    print_split_stats("val",   val_records,   args.format)
    print_split_stats("test",  test_records,  args.format)
    print()
    total = len(train_records) + len(val_records) + len(test_records)
    print(f"✅ 已輸出 {total} 段至 {out_dir}")
    print(f"   train.jsonl / val.jsonl / test.jsonl")

    # 寫一份 metadata 方便追蹤
    meta = {
        "format":          args.format,
        "include_corrections": args.include_corrections,
        "split_ratios":    args.split,
        "seed":            args.seed,
        "manifest_source": str(MANIFEST_PATH.relative_to(PROJECT_ROOT)),
        "counts": {
            "train": len(train_records),
            "val":   len(val_records),
            "test":  len(test_records),
        },
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
