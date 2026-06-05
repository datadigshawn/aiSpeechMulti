#!/usr/bin/env python3
"""
cer_stats.py — CER 統計底盤（逐段分布 + bootstrap 信賴區間 + 兩 run 顯著性比較）

目的
----
既有 batch_eval 只報「單一平均 CER」，無誤差範圍。在小評測集（如 21 段 test）下，
sub-pp 的改善無法分辨是真進步還是抽樣噪音。本工具直接讀 batch_eval 已序列化的
逐段結果（JSON 報告裡的 samples），補上：

  1. 逐段 CER 輸出（CSV）
  2. macro 平均 CER 的 bootstrap 95% 信賴區間
  3. 兩份報告的 paired bootstrap 差異顯著性（自動取共同 id，控制分母）

不重跑模型、不重造 CER；純讀現成 JSON + 統計，零 GPU、零外部依賴（純標準庫）。

用法
----
  # 單一報告：CER + 95% CI + 逐段 CSV
  python scripts/cer_stats.py report <batch_eval_xxx.json>

  # 限定凍結評測集（只算 eval_set.json 內的 id）
  python scripts/cer_stats.py report <x.json> --eval-set experiments/golden_dataset/eval_set.json

  # 兩報告比較（paired bootstrap，自動取共同 id）
  python scripts/cer_stats.py compare <A.json> <B.json>

  # 指標切換（預設 cer_final，可選 cer_raw）
  python scripts/cer_stats.py report <x.json> --metric cer_raw
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV_DIR = PROJECT_ROOT / "experiments" / "llm_correction_poc"

N_BOOT = 10_000
SEED = 42  # 固定 seed → CI 可重現


# ──────────────────────────────────────────────────────────────────────
# 讀取與篩選
# ──────────────────────────────────────────────────────────────────────
def load_samples(json_path: Path) -> tuple[list[dict], dict]:
    """讀 batch_eval JSON 報告，回傳 (成功樣本 list, 報告 meta)。"""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    samples = [s for s in data.get("samples", []) if not s.get("error")]
    meta = {
        "engine_label": data.get("engine_label", json_path.stem),
        "post_process_stages": data.get("post_process_stages", []),
        "sample_count": data.get("sample_count"),
        "success_count": data.get("success_count"),
    }
    return samples, meta


def load_eval_set(path: Path) -> set[str]:
    """讀凍結評測集（eval_set.json，格式 {"ids": [...]} 或純 list）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = data["ids"] if isinstance(data, dict) else data
    return {str(i) for i in ids}


def filter_by_eval_set(samples: list[dict], ids: set[str] | None) -> list[dict]:
    if ids is None:
        return samples
    return [s for s in samples if str(s["id"]) in ids]


# ──────────────────────────────────────────────────────────────────────
# 統計
# ──────────────────────────────────────────────────────────────────────
def bootstrap_ci(values: list[float], n_boot: int = N_BOOT,
                 ci: float = 0.95, seed: int = SEED) -> tuple[float, float, float]:
    """回傳 (mean, ci_low, ci_high)。純 python，固定 seed 可重現。"""
    n = len(values)
    if n == 0:
        return (0.0, 0.0, 0.0)
    mean = sum(values) / n
    if n == 1:
        return (mean, mean, mean)
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        acc = 0.0
        for _ in range(n):
            acc += values[rng.randrange(n)]
        means.append(acc / n)
    means.sort()
    lo = means[int((1 - ci) / 2 * n_boot)]
    hi = means[int((1 + ci) / 2 * n_boot)]
    return (mean, lo, hi)


def paired_bootstrap_diff(deltas: list[float], n_boot: int = N_BOOT,
                          ci: float = 0.95, seed: int = SEED) -> tuple[float, float, float]:
    """對逐段差異（B - A）做 bootstrap，回傳 (mean_diff, ci_low, ci_high)。"""
    return bootstrap_ci(deltas, n_boot=n_boot, ci=ci, seed=seed)


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def pp(x: float) -> str:
    return f"{x * 100:+.2f}pp"


# ──────────────────────────────────────────────────────────────────────
# 指令：report
# ──────────────────────────────────────────────────────────────────────
def cmd_report(args):
    json_path = Path(args.json)
    samples, meta = load_samples(json_path)
    eval_ids = load_eval_set(Path(args.eval_set)) if args.eval_set else None
    samples = filter_by_eval_set(samples, eval_ids)

    if not samples:
        print("❌ 無可用樣本（檢查 JSON 或 eval-set 篩選）")
        sys.exit(1)

    metric = args.metric
    values = [s[metric] for s in samples]
    mean, lo, hi = bootstrap_ci(values)
    half = (hi - lo) / 2

    print(f"\n=== CER 統計報告 ===")
    print(f"來源       : {json_path.name}")
    print(f"引擎       : {meta['engine_label']}  後處理={meta['post_process_stages']}")
    print(f"指標       : {metric}")
    if eval_ids is not None:
        print(f"凍結評測集 : {len(eval_ids)} ids → 命中 {len(samples)} 段")
    print(f"樣本數 n   : {len(samples)}  (報告原始 success={meta['success_count']}/{meta['sample_count']})")
    print(f"平均 CER   : {pct(mean)}")
    print(f"95% CI     : {pct(lo)} – {pct(hi)}   (±{half * 100:.2f}pp)")

    # 依事件類型
    by_type: dict[str, list[float]] = {}
    for s in samples:
        by_type.setdefault(s["event_type"], []).append(s[metric])
    print(f"\n依事件類型：")
    print(f"  {'類型':<10} {'n':>3} {'CER':>8}")
    for t, vs in sorted(by_type.items()):
        print(f"  {t:<10} {len(vs):>3} {pct(sum(vs) / len(vs)):>8}")

    # 逐段 CSV
    out_csv = Path(args.out) if args.out else DEFAULT_CSV_DIR / f"cer_per_segment_{meta['engine_label']}.csv"
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "event_type", "cer_raw", "cer_final", "gt_chars"])
        for s in sorted(samples, key=lambda x: x[metric], reverse=True):
            w.writerow([s["id"], s["event_type"], s.get("cer_raw"),
                        s.get("cer_final"), s.get("gt_chars")])
    print(f"\n逐段 CSV   : {out_csv}  (依 {metric} 由高到低排序)")

    # 最差 5 段（給 C3/C4 用）
    worst = sorted(samples, key=lambda x: x[metric], reverse=True)[:5]
    print(f"\n最差 5 段（{metric}）：")
    for s in worst:
        print(f"  {s['id']:<8} {s['event_type']:<10} {pct(s[metric]):>8}  (gt {s.get('gt_chars')} 字)")


# ──────────────────────────────────────────────────────────────────────
# 指令：compare
# ──────────────────────────────────────────────────────────────────────
def cmd_compare(args):
    pa, pb = Path(args.json_a), Path(args.json_b)
    sa, ma = load_samples(pa)
    sb, mb = load_samples(pb)
    eval_ids = load_eval_set(Path(args.eval_set)) if args.eval_set else None
    sa = filter_by_eval_set(sa, eval_ids)
    sb = filter_by_eval_set(sb, eval_ids)

    metric = args.metric
    da = {str(s["id"]): s[metric] for s in sa}
    db = {str(s["id"]): s[metric] for s in sb}
    common = sorted(set(da) & set(db))
    if not common:
        print("❌ 兩報告無共同 id，無法配對比較")
        sys.exit(1)

    # 自動控制分母：只用共同 id
    a_vals = [da[i] for i in common]
    b_vals = [db[i] for i in common]
    deltas = [db[i] - da[i] for i in common]  # B - A，負=B 更好

    mean_a = sum(a_vals) / len(a_vals)
    mean_b = sum(b_vals) / len(b_vals)
    mean_d, lo, hi = paired_bootstrap_diff(deltas)
    significant = (lo > 0) or (hi < 0)  # CI 不含 0

    improved = sum(1 for d in deltas if d < -1e-9)
    worsened = sum(1 for d in deltas if d > 1e-9)
    same = len(deltas) - improved - worsened

    print(f"\n=== 兩 run 比較（paired bootstrap）===")
    print(f"A : {ma['engine_label']} {ma['post_process_stages']}  ({pa.name})")
    print(f"B : {mb['engine_label']} {mb['post_process_stages']}  ({pb.name})")
    print(f"指標       : {metric}")
    print(f"共同 id    : {len(common)} 段（A={len(da)} B={len(db)}，已自動取交集控制分母）")
    print(f"A 平均 CER : {pct(mean_a)}")
    print(f"B 平均 CER : {pct(mean_b)}")
    print(f"差異 B-A   : {pp(mean_d)}   (負 = B 更好)")
    print(f"95% CI     : [{pp(lo)}, {pp(hi)}]")
    print(f"逐段       : 改善 {improved} / 退步 {worsened} / 持平 {same}")
    verdict = "✅ 顯著（CI 不含 0）" if significant else "⚠️ 不顯著（CI 跨 0，可能是噪音）"
    print(f"判定       : {verdict}")


# ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="CER 統計底盤：逐段分布 + bootstrap CI + 顯著性比較")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("report", help="單一報告：CER + bootstrap CI + 逐段 CSV")
    r.add_argument("json", help="batch_eval JSON 報告路徑")
    r.add_argument("--eval-set", help="凍結評測集 JSON（只算其中的 id）")
    r.add_argument("--metric", default="cer_final", choices=["cer_final", "cer_raw"])
    r.add_argument("--out", help="逐段 CSV 輸出路徑")
    r.set_defaults(func=cmd_report)

    c = sub.add_parser("compare", help="兩報告 paired bootstrap 差異顯著性")
    c.add_argument("json_a", help="報告 A（baseline）")
    c.add_argument("json_b", help="報告 B（新版）")
    c.add_argument("--eval-set", help="凍結評測集 JSON")
    c.add_argument("--metric", default="cer_final", choices=["cer_final", "cer_raw"])
    c.set_defaults(func=cmd_compare)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
