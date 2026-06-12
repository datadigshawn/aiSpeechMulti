#!/usr/bin/env python3
"""
KER 批次評測 — 黃金語料上的關鍵詞錯誤率報告
=============================================
對 golden_dataset 的 ref/hyp 檔對計算 KER，輸出逐詞彙總 + 逐檔明細 CSV。

用法：
    # raw hyp（不經後處理）
    python scripts/ker_eval.py \
        --hyp-dir "experiments/golden_dataset/手動跑senseVoice_fine-tuned"

    # 經完整後處理 pipeline（不含 LLM）
    python scripts/ker_eval.py --hyp-dir ... --pipeline

    # 輸出 CSV
    python scripts/ker_eval.py --hyp-dir ... --out-prefix experiments/ker_report
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPTS_DIR.parent
for p in (str(PROJECT_ROOT), str(_SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from cer_engine import read_transcript_file  # noqa: E402
from ker_engine import calculate_ker, load_keywords  # noqa: E402

DEFAULT_REF_DIR = PROJECT_ROOT / "experiments/golden_dataset/ground_truth"


def main() -> int:
    ap = argparse.ArgumentParser(description="KER 關鍵詞錯誤率批次評測")
    ap.add_argument("--hyp-dir", required=True, help="辨識結果目錄（.txt，檔名須與 ref 對應）")
    ap.add_argument("--ref-dir", default=str(DEFAULT_REF_DIR), help="人工聽打目錄")
    ap.add_argument("--pipeline", action="store_true", help="hyp 先過 post_process（不含 LLM）再評")
    ap.add_argument("--min-alert-level", type=int, default=2, help="關鍵詞 alert_level 門檻（預設 2）")
    ap.add_argument("--out-prefix", default="", help="輸出 CSV 路徑前綴（產生 *_by_keyword.csv 與 *_by_file.csv）")
    args = ap.parse_args()

    keywords = load_keywords(min_alert_level=args.min_alert_level)
    hyp_dir, ref_dir = Path(args.hyp_dir), Path(args.ref_dir)

    post = None
    if args.pipeline:
        from scripts.post_process import post_process
        post = post_process

    agg = defaultdict(lambda: {"ref": 0, "hyp": 0, "hit": 0, "alert_level": 0, "category": ""})
    file_rows = []
    n_ref_total = n_hit_total = halluc_total = 0

    for hyp_path in sorted(hyp_dir.glob("*.txt")):
        ref_path = ref_dir / hyp_path.name
        if not ref_path.exists():
            continue
        hyp_text = read_transcript_file(hyp_path)
        if post is not None:
            hyp_text, _ = post(hyp_text, enable_llm=False)
        r = calculate_ker(read_transcript_file(ref_path), hyp_text, keywords)
        n_ref_total += r["n_ref"]
        n_hit_total += r["n_hit"]
        halluc_total += r["hallucinations"]
        file_rows.append({
            "file": hyp_path.name,
            "n_ref": r["n_ref"],
            "n_hit": r["n_hit"],
            "ker": r["ker"],
            "hallucinations": r["hallucinations"],
        })
        for term, d in r["by_keyword"].items():
            a = agg[term]
            a["ref"] += d["ref"]
            a["hyp"] += d["hyp"]
            a["hit"] += d["hit"]
            a["alert_level"] = d["alert_level"]
            a["category"] = d["category"]

    if not file_rows:
        print("❌ 沒有任何 ref/hyp 檔名配對，檢查 --hyp-dir / --ref-dir")
        return 1

    overall_ker = 1 - (n_hit_total / n_ref_total) if n_ref_total else 0.0
    print(f"檔數: {len(file_rows)}  關鍵詞集: {len(keywords)} 詞（alert_level>={args.min_alert_level}）")
    print(f"整體 KER: {overall_ker:.2%}（命中 {n_hit_total}/{n_ref_total}）  幻覺: {halluc_total}")
    print()
    print(f"{'關鍵詞':　<10s} {'L':>2s} {'ref':>5s} {'hit':>5s} {'recall':>8s}")
    for term, a in sorted(agg.items(), key=lambda kv: (kv[1]["hit"] / kv[1]["ref"]) if kv[1]["ref"] else 1.0):
        if a["ref"] == 0:
            continue
        print(f"{term:　<10s} {a['alert_level']:>2d} {a['ref']:>5d} {a['hit']:>5d} {a['hit']/a['ref']:>8.1%}")
    halluc_only = [(t, a) for t, a in agg.items() if a["ref"] == 0 and a["hyp"] > 0]
    if halluc_only:
        print("\n幻覺詞（ref 無、hyp 有）:")
        for t, a in sorted(halluc_only, key=lambda kv: -kv[1]["hyp"]):
            print(f"  {t} ×{a['hyp']}")

    if args.out_prefix:
        kw_path = Path(f"{args.out_prefix}_by_keyword.csv")
        with open(kw_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["term", "alert_level", "category", "ref", "hyp", "hit", "recall"])
            for term, a in sorted(agg.items()):
                recall = (a["hit"] / a["ref"]) if a["ref"] else ""
                w.writerow([term, a["alert_level"], a["category"], a["ref"], a["hyp"], a["hit"], recall])
        file_path = Path(f"{args.out_prefix}_by_file.csv")
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["file", "n_ref", "n_hit", "ker", "hallucinations"])
            w.writeheader()
            w.writerows(file_rows)
        print(f"\n已輸出: {kw_path} / {file_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
