#!/usr/bin/env python3
"""
CER 趨勢索引建構工具
=======================

掃描 experiments/llm_correction_poc/batch_eval_*.json，抽出每次跑分的指標
（timestamp / engine / post_process / sample_count / cer_raw / cer_final / improvement），
聚合到 experiments/llm_correction_poc/cer_history.csv（append-only，git tracked）。

供 dashboard 趨勢頁與 batch_eval.py 自動 append 共用。

用法：
    # 重建（從零掃所有 JSON）
    python3 scripts/build_cer_index.py --rebuild

    # 增量同步（預設）：只 append 尚未索引的
    python3 scripts/build_cer_index.py

    # 顯示目前索引摘要
    python3 scripts/build_cer_index.py --show
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, asdict, fields
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

REPORTS_DIR = PROJECT_ROOT / "experiments" / "llm_correction_poc"
HISTORY_CSV = REPORTS_DIR / "cer_history.csv"


@dataclass
class CERRow:
    """每次 batch_eval 跑分一筆"""
    timestamp:        str   # YYYYMMDD_HHMMSS
    timestamp_iso:    str   # ISO 8601
    engine_label:     str
    post_process:     str   # 用 + 連接的階段（如 'car_norm+dict' / 'raw'）
    sample_count:     int
    success_count:    int
    avg_cer_raw:      float
    avg_cer_final:    float
    avg_improvement:  float
    avg_wer_final:    float
    source_json:      str   # 原始檔名（debug 用）


# ══════════════════════════════════════════════════════════════════════
# 抽取邏輯
# ══════════════════════════════════════════════════════════════════════
def _ts_to_iso(ts: str) -> str:
    """20260428_115027 → 2026-04-28T11:50:27"""
    try:
        dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
        return dt.isoformat()
    except Exception:
        return ts


def parse_one(json_path: Path) -> CERRow | None:
    try:
        d = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if "engine_label" not in d or "avg_cer_final" not in d:
        return None
    stages = d.get("post_process_stages") or []
    pp_label = "+".join(stages) if stages else "raw"
    return CERRow(
        timestamp=       d.get("timestamp", ""),
        timestamp_iso=   _ts_to_iso(d.get("timestamp", "")),
        engine_label=    d.get("engine_label", ""),
        post_process=    pp_label,
        sample_count=    int(d.get("sample_count", 0)),
        success_count=   int(d.get("success_count", 0)),
        avg_cer_raw=     round(float(d.get("avg_cer_raw", 0)), 4),
        avg_cer_final=   round(float(d.get("avg_cer_final", 0)), 4),
        avg_improvement= round(float(d.get("avg_improvement", 0)), 4),
        avg_wer_final=   round(float(d.get("avg_wer_final", 0)), 4),
        source_json=     json_path.name,
    )


# ══════════════════════════════════════════════════════════════════════
# CSV 讀寫
# ══════════════════════════════════════════════════════════════════════
def load_existing() -> dict[str, dict]:
    """key = source_json，避免重複"""
    if not HISTORY_CSV.exists():
        return {}
    rows: dict[str, dict] = {}
    with open(HISTORY_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows[r.get("source_json", "")] = r
    return rows


def write_csv(rows: list[dict]) -> None:
    rows_sorted = sorted(rows, key=lambda r: (r["timestamp"], r["engine_label"], r["post_process"]))
    field_names = [f.name for f in fields(CERRow)]
    with open(HISTORY_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=field_names)
        writer.writeheader()
        writer.writerows(rows_sorted)


def append_row(row: CERRow) -> None:
    """供 batch_eval.py 跑完直接 append 一筆（不掃所有 JSON）"""
    existing = load_existing()
    existing[row.source_json] = asdict(row)
    write_csv(list(existing.values()))


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="從零掃所有 JSON 重建（覆寫 CSV）")
    ap.add_argument("--show", action="store_true", help="顯示目前索引摘要")
    args = ap.parse_args()

    json_files = sorted(REPORTS_DIR.glob("batch_eval_*.json"))
    print(f"📂 掃描 {REPORTS_DIR}：{len(json_files)} 個 JSON 報告")

    if args.rebuild or not HISTORY_CSV.exists():
        existing = {}
        print("🔄 模式：重建（覆寫 CSV）")
    else:
        existing = load_existing()
        print(f"➕ 模式：增量（既有 {len(existing)} 筆）")

    new_rows = []
    skipped = 0
    failed = 0
    for jp in json_files:
        if jp.name in existing and not args.rebuild:
            skipped += 1
            continue
        row = parse_one(jp)
        if row is None:
            failed += 1
            continue
        new_rows.append(asdict(row))

    if args.rebuild:
        all_rows = new_rows
    else:
        all_rows = list(existing.values()) + new_rows

    write_csv(all_rows)
    print(f"✅ 已寫入 {HISTORY_CSV}")
    print(f"   新增 {len(new_rows)} 筆 / 略過 {skipped} 筆 / 失敗 {failed} 筆 / 共 {len(all_rows)} 筆")

    if args.show or args.rebuild:
        print()
        print(f"━━ 各引擎最新 CER（取每引擎最新一筆 final 最好的）━━")
        by_engine: dict[str, dict] = {}
        for r in all_rows:
            eng = r["engine_label"]
            if eng not in by_engine or float(r["avg_cer_final"]) < float(by_engine[eng]["avg_cer_final"]):
                by_engine[eng] = r
        for eng, r in sorted(by_engine.items(), key=lambda kv: float(kv[1]["avg_cer_final"])):
            print(f"  {eng:15} CER raw={float(r['avg_cer_raw'])*100:6.2f}%  "
                  f"final={float(r['avg_cer_final'])*100:6.2f}%  "
                  f"pp={r['post_process']:30}  ({r['timestamp']})")


if __name__ == "__main__":
    main()
