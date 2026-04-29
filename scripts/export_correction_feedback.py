#!/usr/bin/env python3
"""
匯出人工修正回饋 → 候選規則
=============================

從 transcriptions 表的 (transcript, corrected_transcript) 對抽錯字對。
依 engine_hint 分組，沿用 extract_error_pairs.py 的安全過濾邏輯，
產出每個引擎的 draft overlay 候選與 CSV 報告。

用法：
    # 全部引擎匯出
    python3 scripts/export_correction_feedback.py

    # 僅匯出特定引擎
    python3 scripts/export_correction_feedback.py --engine sensevoice

    # 也產出 draft overlay
    python3 scripts/export_correction_feedback.py --write-overlay
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.db_manager import DBManager  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "aiSpeechMulti.db"
ENGINES_DIR = PROJECT_ROOT / "vocabulary" / "engines"
OUT_DIR = PROJECT_ROOT / "experiments" / "correction_feedback"


def normalize(text: str) -> str:
    """去掉雜訊但保留字元順序，與 extract_error_pairs 一致"""
    if not text:
        return ""
    text = re.sub(r"^[A-Z?]:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"[\s,，。.、:：;；!?！？\-—()（）\"'“”]+", "", text)
    return text


def extract_pairs(raw: str, corrected: str, max_len: int = 8) -> list[tuple[str, str]]:
    pairs = []
    sm = SequenceMatcher(None, raw, corrected, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        wrong = raw[i1:i2]
        right = corrected[j1:j2]
        if not wrong or not right:
            continue
        if len(wrong) > max_len or len(right) > max_len:
            continue
        pairs.append((wrong, right))
    return pairs


def is_safe_pair(wrong: str, right: str) -> bool:
    if not wrong or not right or wrong == right:
        return False
    if len(wrong) < 3:
        return False
    if not re.match(r"^[一-鿿0-9A-Za-z/]+$", wrong):
        return False
    if not re.match(r"^[一-鿿0-9A-Za-z/]+$", right):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", help="只匯出此引擎")
    ap.add_argument("--limit", type=int, default=10000)
    ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument("--write-overlay", action="store_true",
                    help="同時寫 vocabulary/engines/{engine}.feedback-draft.json")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    db = DBManager(DB_PATH)
    rows = db.get_correction_pairs(engine_hint=args.engine, limit=args.limit)
    if not rows:
        print(f"❌ 尚無人工修正紀錄"
              + (f"（engine={args.engine}）" if args.engine else ""))
        return

    print(f"📋 共 {len(rows)} 筆修正紀錄")

    # 依引擎分組
    by_engine: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        eng = r["engine_hint"] or "_unknown"
        by_engine[eng].append(dict(r))

    summary_csv = OUT_DIR / f"correction_feedback_{date.today().isoformat()}.csv"
    csv_rows = []

    for eng, items in by_engine.items():
        print()
        print(f"━━ engine: {eng}  ({len(items)} 筆修正) ━━")
        counter: Counter = Counter()
        for it in items:
            raw_n = normalize(it["transcript"] or "")
            cor_n = normalize(it["corrected_transcript"] or "")
            for p in extract_pairs(raw_n, cor_n):
                counter[p] += 1

        total_pairs = sum(counter.values())
        unique_pairs = len(counter)
        print(f"  → 抽出 {total_pairs} 個替換對 / {unique_pairs} 種獨特對")

        safe_candidates: dict[str, str] = {}
        for (wrong, right), c in counter.most_common(50):
            if c < args.min_count:
                break
            safe = is_safe_pair(wrong, right)
            mark = "✅" if safe else "—"
            csv_rows.append({
                "engine":  eng,
                "wrong":   wrong,
                "right":   right,
                "count":   c,
                "safe":    "Y" if safe else "N",
            })
            if safe and wrong not in safe_candidates:
                safe_candidates[wrong] = right
            print(f"    {c:3}  {wrong!r:14} → {right!r:14}  {mark}")

        if args.write_overlay and safe_candidates and eng != "_unknown":
            out_path = ENGINES_DIR / f"{eng}.feedback-draft.json"
            payload = {
                "_description": f"{eng} feedback-draft overlay — 由人工修正回饋抽出，需 review 後合併到 {eng}.json",
                "_version": f"feedback-draft ({date.today().isoformat()})",
                "_source": "scripts/export_correction_feedback.py",
                "_corrections_count": len(items),
                "_safe_filter": "len>=3 + 中英數斜線字元",
                "blacklist_add": safe_candidates,
                "blacklist_remove": [],
                "whitelist_add": [],
                "whitelist_remove": [],
                "protected_patterns_add": [],
                "contextual_rules_add": [],
                "contextual_rules_remove": []
            }
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  📝 已寫 draft overlay: {out_path}")
            print(f"     候選 {len(safe_candidates)} 條（請 review 後合併到 {eng}.json）")

    # 匯出 CSV
    if csv_rows:
        with open(summary_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["engine", "wrong", "right", "count", "safe"])
            writer.writeheader()
            writer.writerows(csv_rows)
        print()
        print(f"📊 CSV 報告: {summary_csv}（{len(csv_rows)} 對）")


if __name__ == "__main__":
    main()
