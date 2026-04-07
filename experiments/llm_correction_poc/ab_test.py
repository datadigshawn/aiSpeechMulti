#!/usr/bin/env python3
"""
A/B 比對腳本 — 後處理 Pipeline 各層真實貢獻分析
================================================

固定 STT raw 輸入，跑過 4 種設定組合，分別計算 CER vs Ground Truth：

    Config            car_norm   dict    LLM
    ─────────────────────────────────────────
    baseline             ❌       ❌      ❌
    +car_norm            ✅       ❌      ❌
    +car_norm+dict       ✅       ✅      ❌
    full (含 LLM)        ✅       ✅      ✅

特性：
- 完全消除 STT 變異干擾（每次用相同 raw 文字）
- 顯示每層的「絕對 CER 改善」與「相對改善」
- 列出每層實際做的修正項目（diff）
- 可批次處理多個 STT/GT 對

用法：
    # 單樣本
    python3 experiments/llm_correction_poc/ab_test.py \\
        --gt experiments/Test_TMRT2正確文稿/UltraLog06320251222192724.txt \\
        --stt experiments/llm_correction_poc/stt_inputs/UltraLog063_chirp3.txt \\
        --label chirp3

    # 啟用 LLM
    python3 experiments/llm_correction_poc/ab_test.py \\
        --gt ... --stt ... --label gemini --with-llm

    # 多樣本批次
    python3 experiments/llm_correction_poc/ab_test.py \\
        --pair "chirp3=gt.txt::stt_chirp3.txt" \\
        --pair "gemini=gt.txt::stt_gemini.txt" \\
        --with-llm
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = Path(__file__).parent

try:
    import jiwer
except ImportError:
    print("❌ 請先安裝: pip install jiwer")
    sys.exit(1)

try:
    from opencc import OpenCC
    _CC = OpenCC("s2twp")
except Exception:
    _CC = None

from scripts.post_process import post_process


# ══════════════════════════════════════════════════════════════════════
# CER 正規化
# ══════════════════════════════════════════════════════════════════════
def normalize_for_cer(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"^[A-Z]:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[\s,，。.、:：;；!?！？\-—()（）\"'\u201c\u201d]+", "", text)
    if _CC:
        try:
            text = _CC.convert(text)
        except Exception:
            pass
    return text


def compute_cer(reference: str, hypothesis: str) -> float:
    ref = normalize_for_cer(reference)
    hyp = normalize_for_cer(hypothesis)
    if not ref:
        return 0.0
    return jiwer.cer(ref, hyp)


# ══════════════════════════════════════════════════════════════════════
# 4 種設定組合
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Config:
    name: str
    car_norm: bool
    dict_: bool
    llm: bool


CONFIGS_NO_LLM = [
    Config("baseline",        False, False, False),
    Config("+car_norm",       True,  False, False),
    Config("+car_norm+dict",  True,  True,  False),
]

CONFIG_LLM = Config("full(含 LLM)", True, True, True)


@dataclass
class StageResult:
    config: str
    text: str
    cer: float
    cer_delta_abs: float = 0.0   # 相對於 baseline
    cer_delta_rel_pct: float = 0.0
    stage_changes: dict = field(default_factory=dict)
    elapsed_sec: float = 0.0


# ══════════════════════════════════════════════════════════════════════
# 單樣本 A/B 比對
# ══════════════════════════════════════════════════════════════════════
def run_pair(label: str, gt_path: Path, stt_path: Path, with_llm: bool,
             llm_model: str, llm_strict: str) -> dict:
    print()
    print("═" * 70)
    print(f"📦 樣本: {label}")
    print(f"   GT:  {gt_path.name}")
    print(f"   STT: {stt_path.name}")
    print("═" * 70)

    gt = gt_path.read_text(encoding="utf-8")
    stt_raw = stt_path.read_text(encoding="utf-8")

    print(f"   GT 長度:  {len(gt)} 字（正規化後 {len(normalize_for_cer(gt))}）")
    print(f"   STT 長度: {len(stt_raw)} 字（正規化後 {len(normalize_for_cer(stt_raw))}）")

    configs = list(CONFIGS_NO_LLM)
    if with_llm:
        configs.append(CONFIG_LLM)

    results = []
    baseline_cer = None

    for cfg in configs:
        text, report = post_process(
            stt_raw,
            enable_car_norm=cfg.car_norm,
            enable_dict=cfg.dict_,
            enable_llm=cfg.llm,
            llm_model=llm_model,
            llm_strictness=llm_strict,
        )
        cer = compute_cer(gt, text)
        if baseline_cer is None:
            baseline_cer = cer
            delta_abs, delta_rel = 0.0, 0.0
        else:
            delta_abs = baseline_cer - cer
            delta_rel = (delta_abs / baseline_cer * 100) if baseline_cer > 0 else 0.0

        stage_changes = {
            s["name"]: s["change_count"]
            for s in report["stages"] if s.get("change_count", 0) > 0
        }
        # LLM 失敗時記錄錯誤
        llm_error = None
        for s in report["stages"]:
            if s["name"] == "llm" and s.get("error"):
                llm_error = s["error"]

        result = StageResult(
            config=cfg.name,
            text=text,
            cer=round(cer, 4),
            cer_delta_abs=round(delta_abs, 4),
            cer_delta_rel_pct=round(delta_rel, 2),
            stage_changes=stage_changes,
            elapsed_sec=report["elapsed_sec"],
        )
        results.append(result)

        marker = "📍" if cfg.name == "baseline" else "  "
        warn = f"  ⚠️ {llm_error}" if llm_error else ""
        print(f"{marker} {cfg.name:18} CER={cer*100:6.2f}%  Δ={delta_abs*100:+6.2f}%  ({delta_rel:+6.2f}%)  耗時={report['elapsed_sec']:.3f}s{warn}")
        if stage_changes:
            print(f"     stages: {stage_changes}")

    # 計算每個增量階段的「邊際貢獻」
    print()
    print("   ─── 邊際貢獻（相對前一個 config）───")
    for i in range(1, len(results)):
        delta = results[i-1].cer - results[i].cer
        sign = "↓" if delta > 0 else ("↑" if delta < 0 else "—")
        print(f"   {results[i-1].config:20} → {results[i].config:18} CER 變化 {delta*100:+.3f}% {sign}")

    return {
        "label": label,
        "gt_file": str(gt_path),
        "stt_file": str(stt_path),
        "gt_len_norm": len(normalize_for_cer(gt)),
        "stt_len_norm": len(normalize_for_cer(stt_raw)),
        "results": [asdict(r) for r in results],
        "baseline_cer": round(baseline_cer or 0, 4),
    }


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def parse_pair(spec: str) -> tuple[str, Path, Path]:
    """label=gt::stt 格式解析"""
    if "=" not in spec or "::" not in spec:
        raise ValueError(f"--pair 格式錯誤，需要 label=gt::stt: {spec}")
    label, paths = spec.split("=", 1)
    gt_str, stt_str = paths.split("::", 1)
    gt = Path(gt_str)
    stt = Path(stt_str)
    if not gt.is_absolute():
        gt = PROJECT_ROOT / gt
    if not stt.is_absolute():
        stt = PROJECT_ROOT / stt
    return label, gt, stt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gt", help="單樣本：ground truth 路徑（搭配 --stt 與 --label）")
    p.add_argument("--stt", help="單樣本：STT 結果路徑")
    p.add_argument("--label", help="單樣本標籤")
    p.add_argument("--pair", action="append", default=[],
                   help="批次：label=gt::stt 格式，可重複使用")
    p.add_argument("--with-llm", action="store_true", help="額外跑一輪含 LLM 的 config")
    p.add_argument("--llm-model", default="gemini-2.5-flash")
    p.add_argument("--llm-strictness", default="conservative",
                   choices=["strict", "conservative", "balanced"])
    args = p.parse_args()

    # 收集所有 pair
    pairs = []
    if args.gt and args.stt:
        label = args.label or Path(args.stt).stem
        gt = Path(args.gt) if Path(args.gt).is_absolute() else PROJECT_ROOT / args.gt
        stt = Path(args.stt) if Path(args.stt).is_absolute() else PROJECT_ROOT / args.stt
        pairs.append((label, gt, stt))
    for spec in args.pair:
        pairs.append(parse_pair(spec))

    if not pairs:
        print("❌ 至少需要一組 --gt + --stt 或 --pair")
        sys.exit(1)

    print(f"🔬 A/B 後處理比對 — 共 {len(pairs)} 個樣本")
    if args.with_llm:
        print(f"   ✨ 含 LLM 設定: {args.llm_model} / {args.llm_strictness}")

    # 執行
    all_results = []
    for label, gt, stt in pairs:
        if not gt.exists():
            print(f"❌ GT 不存在: {gt}")
            continue
        if not stt.exists():
            print(f"❌ STT 不存在: {stt}")
            continue
        result = run_pair(
            label, gt, stt, args.with_llm,
            args.llm_model, args.llm_strictness,
        )
        all_results.append(result)

    if not all_results:
        return

    # 跨樣本總表
    print()
    print("═" * 70)
    print("📊 跨樣本總表（CER %）")
    print("═" * 70)
    config_names = [r["config"] for r in all_results[0]["results"]]
    header = f"{'樣本':20} | " + " | ".join(f"{c:>16}" for c in config_names)
    print(header)
    print("-" * len(header))
    for r in all_results:
        row = f"{r['label']:20} | " + " | ".join(
            f"{stage['cer']*100:>15.2f}%" for stage in r["results"]
        )
        print(row)

    # 平均改善
    if len(all_results) > 1:
        print()
        print("─── 平均 CER 改善（vs baseline）───")
        n_configs = len(all_results[0]["results"])
        for i in range(1, n_configs):
            avg_abs = sum(r["results"][i]["cer_delta_abs"] for r in all_results) / len(all_results)
            avg_rel = sum(r["results"][i]["cer_delta_rel_pct"] for r in all_results) / len(all_results)
            cfg_name = all_results[0]["results"][i]["config"]
            print(f"   {cfg_name:20} 絕對改善 {avg_abs*100:+.2f}%   相對改善 {avg_rel:+.2f}%")

    # 寫出 JSON 與 Markdown 報告
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / f"ab_test_{ts}.json"
    json_path.write_text(json.dumps({
        "meta": {
            "timestamp": ts,
            "with_llm": args.with_llm,
            "llm_model": args.llm_model if args.with_llm else None,
            "llm_strictness": args.llm_strictness if args.with_llm else None,
            "sample_count": len(all_results),
        },
        "samples": all_results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        f"# A/B 後處理比對報告",
        f"",
        f"- **時間**: {ts}",
        f"- **樣本數**: {len(all_results)}",
        f"- **含 LLM**: {'是 (' + args.llm_model + ' / ' + args.llm_strictness + ')' if args.with_llm else '否'}",
        f"",
        f"## 📊 跨樣本 CER 對比",
        f"",
    ]
    md.append("| 樣本 | " + " | ".join(config_names) + " |")
    md.append("|---" * (len(config_names) + 1) + "|")
    for r in all_results:
        cells = " | ".join(
            f"**{s['cer']*100:.2f}%**" if i == 0 else
            f"{s['cer']*100:.2f}% ({s['cer_delta_rel_pct']:+.1f}%)"
            for i, s in enumerate(r["results"])
        )
        md.append(f"| {r['label']} | {cells} |")

    md += [f"", f"## 📋 各樣本詳細"]
    for r in all_results:
        md += [
            f"",
            f"### {r['label']}",
            f"",
            f"- GT 檔案: `{Path(r['gt_file']).name}`（正規化後 {r['gt_len_norm']} 字）",
            f"- STT 檔案: `{Path(r['stt_file']).name}`（正規化後 {r['stt_len_norm']} 字）",
            f"- Baseline CER: **{r['baseline_cer']*100:.2f}%**",
            f"",
            f"| Config | CER | Δ vs baseline | Stages | 耗時 |",
            f"|---|---|---|---|---|",
        ]
        for s in r["results"]:
            stages_str = ", ".join(f"{k}={v}" for k, v in s["stage_changes"].items()) or "—"
            md.append(
                f"| {s['config']} | {s['cer']*100:.2f}% | "
                f"{s['cer_delta_abs']*100:+.2f}% ({s['cer_delta_rel_pct']:+.1f}%) | "
                f"{stages_str} | {s['elapsed_sec']:.3f}s |"
            )

    md_path = OUTPUT_DIR / f"ab_test_{ts}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    print()
    print(f"📄 JSON: {json_path}")
    print(f"📄 報告: {md_path}")


if __name__ == "__main__":
    main()
