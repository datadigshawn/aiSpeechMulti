#!/usr/bin/env python3
"""
錯字對抽取工具
==============

從 GT 與指定引擎 STT 結果做字元級對齊，
抽出常見的（wrong → right）替換對，依出現頻率排序。
作為 blacklist / contextual rules 擴充的依據。

用法：
    python3 scripts/extract_error_pairs.py \
        --engine gemini25pro \
        --top 50
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

MANIFEST_PATH = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"
STT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "stt_outputs"

try:
    from opencc import OpenCC
    _CC = OpenCC("s2twp")
except Exception:
    _CC = None


def normalize(text: str) -> str:
    """去掉講者標籤 / 標點 / 統一繁簡，但保留字元順序"""
    text = re.sub(r"^[A-Z?]:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"[\s,，。.、:：;；!?！？\-—()（）\"'“”]+", "", text)
    if _CC:
        try:
            text = _CC.convert(text)
        except Exception:
            pass
    return text


def extract_pairs(gt: str, stt: str, max_len: int = 8) -> list[tuple[str, str]]:
    """
    對齊 GT 與 STT，回傳 [(stt_substring, gt_substring), ...] 替換對。
    只收集替換段（'replace'），不含純插入或純刪除。
    """
    pairs = []
    sm = SequenceMatcher(None, stt, gt, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        wrong = stt[i1:i2]
        right = gt[j1:j2]
        if not wrong or not right:
            continue
        if len(wrong) > max_len or len(right) > max_len:
            continue
        pairs.append((wrong, right))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="gemini25pro")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--min-count", type=int, default=2)
    args = ap.parse_args()

    cache_dir = STT_DIR / args.engine
    if not cache_dir.exists():
        print(f"❌ STT 目錄不存在: {cache_dir}")
        return

    rows = []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("has_gt") == "Y":
                rows.append(row)

    print(f"🔍 引擎: {args.engine}  /  樣本數: {len(rows)}")
    print()

    counter: Counter = Counter()
    sample_ids: dict[tuple, list[str]] = {}

    for row in rows:
        sid = row["id"]
        gt_path = PROJECT_ROOT / row["gt_file"]
        stt_path = cache_dir / f"{sid}.txt"
        if not gt_path.exists() or not stt_path.exists():
            continue
        gt = normalize(gt_path.read_text(encoding="utf-8"))
        stt = normalize(stt_path.read_text(encoding="utf-8"))
        pairs = extract_pairs(gt, stt)
        for p in pairs:
            counter[p] += 1
            sample_ids.setdefault(p, []).append(sid)

    print(f"📊 共抽出 {sum(counter.values())} 個替換對  /  {len(counter)} 種獨特對")
    print()
    print(f"━━ Top {args.top}（出現 ≥{args.min_count} 次）━━")
    print(f"{'count':>5}  {'wrong':<14}  {'→':<2}  {'right':<14}  {'sample_ids'}")
    print("-" * 80)
    for (wrong, right), c in counter.most_common(args.top):
        if c < args.min_count:
            break
        ids = ",".join(sample_ids[(wrong, right)][:5])
        print(f"{c:>5}  {wrong:<14}  →   {right:<14}  ({ids}{'...' if len(sample_ids[(wrong, right)]) > 5 else ''})")


if __name__ == "__main__":
    main()
