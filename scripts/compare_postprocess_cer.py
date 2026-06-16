#!/usr/bin/env python3
"""第二波驗證工具：比較 fix_radio_jargon 收斂前後在 golden set 上的 CER。

背景：2026-06-16 第二波把 fix_radio_jargon 從「舊版 RadioTextCleaner.clean
(aggressive=True)」收斂為「canonical 核心 post_process_realtime」。batch_inference
透過 fix_radio_jargon 吃到新行為，輸出會變，需確認 CER 非退步。

本腳本在同一 process 內同時跑：
  - OLD：utils.text_cleaner._default_cleaner.clean(raw, aggressive=True)（收斂前行為，
         該路徑已標記 dead 但尚未移除，故仍可呼叫做對照）
  - NEW：utils.text_cleaner.fix_radio_jargon(raw)（收斂後 = canonical deterministic）
對每個 golden case 各算一次 CER（對 GT），輸出 old/new 平均與逐案 delta，標出退步案例。

用法：
  python scripts/compare_postprocess_cer.py \
      --raw-dir path/to/raw_stt_txt \
      --manifest experiments/golden_dataset/manifest.csv

raw-dir 內每個 case 的「原始 STT 輸出」純文字檔，檔名需能對應 manifest 的 id：
優先找 "{id}.txt"，否則找以 "{id}_" 開頭的檔。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.cer_engine import calculate_cer  # noqa: E402
from utils.text_cleaner import fix_radio_jargon, _default_cleaner  # noqa: E402


def _old_clean(text: str) -> str:
    """收斂前的 fix_radio_jargon 行為（對照組）。"""
    return _default_cleaner.clean(text, aggressive=True)


def _find_raw(raw_dir: Path, case_id: str) -> Path | None:
    exact = raw_dir / f"{case_id}.txt"
    if exact.exists():
        return exact
    matches = sorted(raw_dir.glob(f"{case_id}_*"))
    return matches[0] if matches else None


def main() -> int:
    ap = argparse.ArgumentParser(description="比較 fix_radio_jargon 收斂前後 CER")
    ap.add_argument("--raw-dir", required=True, type=Path,
                    help="原始 STT 輸出 txt 目錄（檔名對應 manifest id）")
    ap.add_argument("--manifest", type=Path,
                    default=PROJECT_ROOT / "experiments/golden_dataset/manifest.csv")
    ap.add_argument("--regression-eps", type=float, default=0.0,
                    help="new_cer - old_cer 超過此值才算退步（預設 0.0）")
    args = ap.parse_args()

    if not args.raw_dir.is_dir():
        print(f"❌ raw-dir 不存在：{args.raw_dir}")
        return 2
    if not args.manifest.exists():
        print(f"❌ manifest 不存在：{args.manifest}")
        return 2

    rows = []
    with args.manifest.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("has_gt", "").strip().upper() != "Y":
                continue
            gt_path = PROJECT_ROOT / r["gt_file"]
            raw_path = _find_raw(args.raw_dir, r["id"])
            if not gt_path.exists() or raw_path is None:
                continue
            rows.append((r["id"], gt_path, raw_path))

    if not rows:
        print("⚠️ 找不到任何可對照的 case（raw-dir 檔名需對應 manifest id）。")
        return 1

    old_sum = new_sum = 0.0
    regressions, improvements = [], []
    print(f"{'id':<6} {'old_cer':>8} {'new_cer':>8} {'delta':>8}")
    print("-" * 34)
    for case_id, gt_path, raw_path in rows:
        gt = gt_path.read_text(encoding="utf-8")
        raw = raw_path.read_text(encoding="utf-8")
        old_cer = calculate_cer(gt, _old_clean(raw))["cer"]
        new_cer = calculate_cer(gt, fix_radio_jargon(raw))["cer"]
        delta = new_cer - old_cer
        old_sum += old_cer
        new_sum += new_cer
        if delta > args.regression_eps:
            regressions.append((case_id, old_cer, new_cer, delta))
        elif delta < -args.regression_eps:
            improvements.append((case_id, old_cer, new_cer, delta))
        print(f"{case_id:<6} {old_cer:>8.4f} {new_cer:>8.4f} {delta:>+8.4f}")

    n = len(rows)
    print("-" * 34)
    print(f"\nN={n}  mean old_cer={old_sum/n:.4f}  mean new_cer={new_sum/n:.4f}  "
          f"delta={ (new_sum-old_sum)/n:+.4f}")
    print(f"退步 {len(regressions)} 案、改善 {len(improvements)} 案、持平 "
          f"{n - len(regressions) - len(improvements)} 案")
    if regressions:
        print("\n⚠️ 退步案例（new 比 old 差）：")
        for cid, o, nw, d in regressions:
            print(f"  {cid}: {o:.4f} → {nw:.4f} ({d:+.4f})")
    # 平均退步 → 非 0 退出碼，方便 CI / 人工把關
    return 1 if (new_sum - old_sum) / n > args.regression_eps else 0


if __name__ == "__main__":
    raise SystemExit(main())
