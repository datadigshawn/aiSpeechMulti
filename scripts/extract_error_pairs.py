#!/usr/bin/env python3
"""
錯字對抽取工具
==============

從 GT 與指定引擎 STT 結果做字元級對齊，
抽出常見的（wrong → right）替換對，依出現頻率排序。
作為 blacklist / contextual rules 擴充的依據。

用法：
    # 只列出統計，不寫檔
    python3 scripts/extract_error_pairs.py --engine gemini25pro --top 50

    # 直接產出 overlay JSON 到 vocabulary/engines/{engine}.draft.json
    python3 scripts/extract_error_pairs.py --engine scribe --write-overlay
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


def _is_safe_pair(wrong: str, right: str) -> bool:
    """判斷一對 (wrong, right) 是否適合放 blacklist：
    - 太短的字元（1-2 字）容易誤殺，排除
    - wrong / right 必須非空、不相同
    - 只允許中文 / 英數 / 斜線（避免規則含奇怪符號）
    """
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
    ap.add_argument("--engine", default="gemini25pro")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument("--write-overlay", action="store_true",
                    help="把候選規則（出現 ≥ min_count 且通過安全過濾）寫入 vocabulary/engines/{engine}.draft.json")
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
    print(f"{'count':>5}  {'wrong':<14}  {'→':<2}  {'right':<14}  {'safe':<4}  {'sample_ids'}")
    print("-" * 90)
    safe_candidates: dict[str, str] = {}
    for (wrong, right), c in counter.most_common(args.top):
        if c < args.min_count:
            break
        safe = _is_safe_pair(wrong, right)
        if safe and wrong not in safe_candidates:
            safe_candidates[wrong] = right
        ids = ",".join(sample_ids[(wrong, right)][:5])
        mark = "✅" if safe else "—"
        more = "..." if len(sample_ids[(wrong, right)]) > 5 else ""
        print(f"{c:>5}  {wrong:<14}  →   {right:<14}  {mark}     ({ids}{more})")

    if args.write_overlay:
        out_path = PROJECT_ROOT / "vocabulary" / "engines" / f"{args.engine}.draft.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        from datetime import date
        payload = {
            "_description": f"{args.engine} draft overlay — extracted automatically，需人工 review 後改名為 {args.engine}.json",
            "_version": f"draft ({date.today().isoformat()})",
            "_source": f"scripts/extract_error_pairs.py --engine {args.engine} --min-count {args.min_count}",
            "_safe_filter": "len>=3 + 中英數斜線字元；通用單字（1-2 字）已排除避免誤殺",
            "_review_checklist": [
                "確認每條規則在實際語境不會誤殺正常字串",
                "若某條規則需要上下文限制，移到 contextual_corrections.json 而非 blacklist",
                "完成 review 後將檔名從 *.draft.json 改為 *.json"
            ],
            "blacklist_add": safe_candidates,
            "blacklist_remove": [],
            "whitelist_add": [],
            "whitelist_remove": [],
            "protected_patterns_add": []
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print()
        print(f"📝 已寫入 draft overlay: {out_path}")
        print(f"   候選規則 {len(safe_candidates)} 條（安全過濾後）")
        print(f"   ⚠️ 請人工 review 後改名為 {args.engine}.json")


if __name__ == "__main__":
    main()
