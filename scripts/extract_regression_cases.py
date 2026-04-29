#!/usr/bin/env python3
"""
Regression case 抽取工具
==========================

掃描 stt_outputs/{engine}/*.txt，跑 post_process，找出「raw STT 對的字段，
被後處理改錯」的反例（即 cer_final > cer_raw）。

流程：
  raw STT → post_process → final
       │           │
       ↓           ↓
       └─── diff ──┘ → 抽出每階段改了什麼
                      │
                      └ 對照 GT：哪些 raw 已對的字串被改成 final 的錯字？
                                 → 候選 whitelist 保護

用法：
    # 掃單引擎
    python3 scripts/extract_regression_cases.py --engine gemini25pro

    # 掃所有引擎、含 LLM 後處理（最完整）
    python3 scripts/extract_regression_cases.py --all --enable-llm

    # 寫 CSV 報告 + 候選 whitelist 清單
    python3 scripts/extract_regression_cases.py --all --write-report
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.post_process import post_process  # noqa: E402

try:
    from opencc import OpenCC
    _CC = OpenCC("s2twp")
except Exception:
    _CC = None

MANIFEST_PATH = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"
STT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "stt_outputs"
GT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "ground_truth"
OUT_DIR = PROJECT_ROOT / "experiments" / "regression_cases"


# ══════════════════════════════════════════════════════════════════════
# 文本正規化（同 batch_eval / extract_error_pairs）
# ══════════════════════════════════════════════════════════════════════
def normalize(text: str) -> str:
    if not text:
        return ""
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


def cer(a: str, b: str) -> float:
    if not a:
        return 0.0
    sm = SequenceMatcher(None, a, b)
    similar = sum(blk.size for blk in sm.get_matching_blocks())
    return 1 - similar / max(len(a), 1)


# ══════════════════════════════════════════════════════════════════════
# 反向 diff：找出 raw → final 的替換對
# ══════════════════════════════════════════════════════════════════════
def find_replace_pairs(raw: str, final: str) -> list[tuple[str, str]]:
    """回傳 raw 中被改成 final 的 (wrong, right) — 對 'replace' tag 才抽"""
    pairs = []
    sm = SequenceMatcher(None, raw, final, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            pairs.append((raw[i1:i2], final[j1:j2]))
    return pairs


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def load_manifest() -> list[dict]:
    rows = []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("has_gt") == "Y":
                rows.append(row)
    return rows


def process_engine(
    engine: str,
    enable_llm: bool = False,
    llm_model: str = "gemini-2.5-flash",
) -> tuple[list[dict], Counter, Counter]:
    """
    回傳：
      regression_cases: 每筆退步段的詳細
      misfix_pairs: Counter 累積「導致退步的 (wrong→right) 字串對」
      stage_blame: Counter 累積各 stage 多少次參與了退步段
    """
    cache_dir = STT_DIR / engine
    if not cache_dir.exists():
        print(f"⚠️ {engine}: {cache_dir} 不存在，略過")
        return [], Counter(), Counter()

    manifest = load_manifest()
    regression_cases: list[dict] = []
    misfix_pairs: Counter = Counter()
    stage_blame: Counter = Counter()

    for sample in manifest:
        sid = sample["id"]
        gt_path = PROJECT_ROOT / sample["gt_file"]
        stt_path = cache_dir / f"{sid}.txt"
        if not gt_path.exists() or not stt_path.exists():
            continue

        gt_raw = gt_path.read_text(encoding="utf-8")
        stt_raw = stt_path.read_text(encoding="utf-8")

        try:
            final, report = post_process(
                stt_raw,
                enable_car_norm=True,
                enable_dict=True,
                enable_llm=enable_llm,
                llm_model=llm_model,
                llm_strictness="conservative",
                engine_hint=engine,
                auto_skip_llm_for_high_quality=False,
            )
        except Exception as e:
            print(f"  ⚠️ {sid}: post_process error: {e}")
            continue

        gt_n = normalize(gt_raw)
        raw_n = normalize(stt_raw)
        fin_n = normalize(final)
        cer_raw = cer(gt_n, raw_n)
        cer_final = cer(gt_n, fin_n)
        delta = cer_final - cer_raw

        if delta <= 0:
            continue  # 沒退步

        # 確認確實退步（容忍 1e-4 浮點誤差）
        if delta < 1e-4:
            continue

        # 抽 raw → final 的差異對
        pairs = find_replace_pairs(raw_n, fin_n)

        # 找出哪些 pair 在 GT 裡 raw 是對的但 final 是錯的（誤殺）
        misfixes_in_this_sample = []
        for wrong_in_raw, wrong_in_final in pairs:
            # 「raw 對 / final 錯」的判定：
            #   raw 子字串在 GT 中找得到（OCR 化簡比對），但 final 子字串找不到
            if not wrong_in_raw or not wrong_in_final:
                continue
            in_gt_raw_form = wrong_in_raw in gt_n
            in_gt_final_form = wrong_in_final in gt_n
            if in_gt_raw_form and not in_gt_final_form:
                misfix_pairs[(wrong_in_raw, wrong_in_final)] += 1
                misfixes_in_this_sample.append({
                    "wrong_in_final": wrong_in_final,
                    "should_keep": wrong_in_raw,
                })

        # 累積 stage 責任歸屬
        for st in report["stages"]:
            if st.get("change_count", 0) > 0:
                stage_blame[st["name"]] += 1

        regression_cases.append({
            "id":           sid,
            "engine":       engine,
            "event_type":   sample.get("event_type", ""),
            "cer_raw":      round(cer_raw, 4),
            "cer_final":    round(cer_final, 4),
            "cer_delta":    round(delta, 4),
            "raw":          stt_raw[:200],
            "final":        final[:200],
            "gt":           gt_raw[:200],
            "stages_with_changes": [
                {"stage": s["name"], "count": s["change_count"]}
                for s in report["stages"] if s.get("change_count", 0) > 0
            ],
            "misfixes":     misfixes_in_this_sample,
        })

    return regression_cases, misfix_pairs, stage_blame


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", help="單一引擎（如 gemini25pro / scribe）")
    ap.add_argument("--all", action="store_true", help="掃 4 個主力引擎")
    ap.add_argument("--enable-llm", action="store_true", help="啟用 LLM 後修正（會跑 API）")
    ap.add_argument("--llm-model", default="gemini-2.5-flash")
    ap.add_argument("--write-report", action="store_true", help="寫 CSV + Markdown 報告")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    if args.all:
        engines = ["chirp3", "scribe", "sensevoice", "gemini25pro"]
    elif args.engine:
        engines = [args.engine]
    else:
        ap.error("須指定 --engine 或 --all")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_cases: list[dict] = []
    global_misfix: Counter = Counter()
    global_stage_blame: Counter = Counter()

    for eng in engines:
        print(f"\n━━ engine: {eng} ━━")
        cases, misfixes, stage_blame = process_engine(
            eng, enable_llm=args.enable_llm, llm_model=args.llm_model
        )
        print(f"  退步段: {len(cases)}")
        print(f"  誤殺對: {sum(misfixes.values())} 個 / {len(misfixes)} 種獨特對")
        all_cases.extend(cases)
        global_misfix.update(misfixes)
        global_stage_blame.update(stage_blame)

    print()
    print("━━ 全引擎彙總 ━━")
    print(f"  退步段總數: {len(all_cases)}")
    print(f"  誤殺對總數: {sum(global_misfix.values())} 個 / {len(global_misfix)} 種獨特")
    print()
    print("━━ 各 stage 涉入退步段次數 ━━")
    for stage, n in global_stage_blame.most_common():
        print(f"  {stage:25} {n:3} 次")

    print()
    print(f"━━ Top {args.top} 誤殺對（建議加 whitelist 保護）━━")
    print(f"{'count':>5}  {'被改前 (raw)':<14}  →  {'被改後 (final)':<14}")
    for (wrong, right), c in global_misfix.most_common(args.top):
        print(f"{c:>5}  {wrong:<14}  →  {right:<14}")

    if args.write_report:
        # CSV
        csv_path = OUT_DIR / f"regression_cases_{date.today().isoformat()}.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "engine", "id", "event_type", "cer_raw", "cer_final", "cer_delta",
                "stages", "misfix_count",
            ])
            writer.writeheader()
            for c in all_cases:
                writer.writerow({
                    "engine":       c["engine"],
                    "id":           c["id"],
                    "event_type":   c["event_type"],
                    "cer_raw":      c["cer_raw"],
                    "cer_final":    c["cer_final"],
                    "cer_delta":    c["cer_delta"],
                    "stages":       ",".join(s["stage"] for s in c["stages_with_changes"]),
                    "misfix_count": len(c["misfixes"]),
                })
        print()
        print(f"📊 CSV 報告: {csv_path}")

        # Markdown 報告
        md_path = OUT_DIR / f"regression_cases_{date.today().isoformat()}.md"
        md = [
            f"# Regression cases 報告 — {date.today().isoformat()}",
            "",
            f"- 引擎：{', '.join(engines)}",
            f"- 含 LLM：{'是' if args.enable_llm else '否'}",
            f"- 退步段總數：{len(all_cases)}",
            f"- 誤殺對總數：{sum(global_misfix.values())}",
            "",
            "## Top 誤殺對（建議加 whitelist）",
            "",
            "| 次數 | 被改前 (raw 對) | 被改後 (final 錯) |",
            "|---|---|---|",
        ]
        for (wrong, right), c in global_misfix.most_common(args.top):
            md.append(f"| {c} | `{wrong}` | `{right}` |")
        md.extend([
            "",
            "## 各 stage 涉入退步段次數",
            "",
            "| stage | 次數 |",
            "|---|---|",
        ])
        for stage, n in global_stage_blame.most_common():
            md.append(f"| {stage} | {n} |")
        md.extend([
            "",
            "## 退步段明細（前 20 筆）",
            "",
        ])
        for c in all_cases[:20]:
            md.append(f"### {c['engine']} / {c['id']} ({c['event_type']}) — Δ {c['cer_delta']*100:+.2f}%")
            md.append(f"- CER raw: {c['cer_raw']*100:.2f}% → final: {c['cer_final']*100:.2f}%")
            md.append(f"- Stages with changes: {', '.join(s['stage'] for s in c['stages_with_changes'])}")
            md.append("")
            md.append("```")
            md.append(f"GT:    {c['gt']}")
            md.append(f"raw:   {c['raw']}")
            md.append(f"final: {c['final']}")
            md.append("```")
            if c["misfixes"]:
                md.append("- 誤殺對:")
                for m in c["misfixes"]:
                    md.append(f"  - `{m['should_keep']}` → `{m['wrong_in_final']}`（GT 中是 `{m['should_keep']}`）")
            md.append("")
        md_path.write_text("\n".join(md), encoding="utf-8")
        print(f"📄 Markdown 報告: {md_path}")


if __name__ == "__main__":
    main()
