#!/usr/bin/env python3
"""
嚴格版文本正規化（GT 風格分歧分析用）
========================================

延伸現有 batch_eval.normalize_for_cer 的基礎正規化，加上：
1. 全形 ↔ 半形統一（１２３ → 123, ＯＣＣ → OCC）
2. 元描述移除（沉默N秒、笑聲、咳嗽 等）
3. 同義詞容忍表（OCC ≈ 行控 ≈ 行控中心 等）
4. 車組編號格式統一（25/26 = 2526 = 25-26）

目的：量化「目前 CER 中有多少是 GT 與 STT 風格不一致造成的『假 CER』」，
而非真實辨識錯誤。

用法：
    # 對單個引擎跑：base CER vs strict CER 對照
    python3 scripts/normalize_strict.py --engine gemini25pro

    # 對所有 4 引擎跑（產出 markdown 報告）
    python3 scripts/normalize_strict.py --all --write-report
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import jiwer
except ImportError:
    print("❌ 請先安裝 pip install jiwer")
    sys.exit(1)

try:
    from opencc import OpenCC
    _CC = OpenCC("s2twp")
except Exception:
    _CC = None

MANIFEST_PATH = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"
STT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "stt_outputs"


# ══════════════════════════════════════════════════════════════════════
# 同義詞容忍表（重點術語多樣寫法統一）
# ══════════════════════════════════════════════════════════════════════
# (variants) → canonical
SYNONYMS = {
    "OCC": ["行控", "行控中心", "行控站", "OCC"],
    "月台": ["月台", "月臺"],
    "復電": ["復電", "復位電", "回復電"],
    "清車": ["清車", "清空"],
    "進站": ["進站", "進場"],
    "司機員": ["司機員", "司機", "駕駛員"],
    "站長": ["站長", "站務長"],
    "over": ["over", "OVER", "Over"],
}

# 元描述/環境音描述（GT 與 STT 寫法常不一致）
META_DESCRIPTIONS = [
    r"\(沉默\s*[\d一二三四五六七八九十]+\s*秒\)",
    r"\(沉默\s*[\d一二三四五六七八九十]+s\)",
    r"\(silence\s*[\d]+s?\)",
    r"\(笑聲\)", r"\(咳嗽\)", r"\(雜音\)",
    r"\(noise\)", r"\(laughter\)", r"\(cough\)",
    r"\(unclear\)", r"\(inaudible\)",
    r"\[noise\]", r"\[unclear\]",
    r"（沉默[^）]*）",
]


# ══════════════════════════════════════════════════════════════════════
# 正規化主函數
# ══════════════════════════════════════════════════════════════════════
def _normalize_base(text: str) -> str:
    """同 batch_eval.normalize_for_cer，作為基準對照"""
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


def _full_to_half(text: str) -> str:
    """全形 ↔ 半形統一（數字、英文、符號）"""
    out = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            # 全形 ASCII 範圍 → 半形（差 0xFEE0）
            out.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            # 全形空格
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _remove_meta_descriptions(text: str) -> str:
    """移除元描述（沉默 N 秒、笑聲、咳嗽 等）"""
    for pat in META_DESCRIPTIONS:
        text = re.sub(pat, "", text)
    return text


def _apply_synonyms(text: str) -> str:
    """把同義詞統一為 canonical（按長度排序避免短詞先替換）"""
    for canonical, variants in SYNONYMS.items():
        # 把所有變體統一為 canonical
        for v in sorted(variants, key=lambda x: -len(x)):
            if v != canonical:
                text = text.replace(v, canonical)
    return text


def normalize_strict(text: str, apply_synonyms: bool = True) -> str:
    """
    嚴格正規化：基底 + 全形半形 + 元描述移除 + 同義詞容忍
    apply_synonyms=False 用於對照（純格式統一不容忍同義詞）
    """
    if not text:
        return ""
    text = _full_to_half(text)
    text = _remove_meta_descriptions(text)
    if apply_synonyms:
        text = _apply_synonyms(text)
    text = _normalize_base(text)
    return text


# ══════════════════════════════════════════════════════════════════════
# CER 計算
# ══════════════════════════════════════════════════════════════════════
def cer_base(ref: str, hyp: str) -> float:
    r, h = _normalize_base(ref), _normalize_base(hyp)
    if not r:
        return 0.0
    return jiwer.cer(r, h)


def cer_format_only(ref: str, hyp: str) -> float:
    """格式統一（全形半形 + 元描述）但不容忍同義詞"""
    r = normalize_strict(ref, apply_synonyms=False)
    h = normalize_strict(hyp, apply_synonyms=False)
    if not r:
        return 0.0
    return jiwer.cer(r, h)


def cer_strict(ref: str, hyp: str) -> float:
    """完整嚴格版（含同義詞容忍）"""
    r = normalize_strict(ref, apply_synonyms=True)
    h = normalize_strict(hyp, apply_synonyms=True)
    if not r:
        return 0.0
    return jiwer.cer(r, h)


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


def analyze_engine(engine: str, stt_subdir: str | None = None) -> dict:
    """
    對單一引擎跑三種 CER 對照：base / format_only / strict
    回傳 {engine, samples, base_cer, format_cer, strict_cer, deltas}
    """
    cache_dir = STT_DIR / (stt_subdir or engine)
    if not cache_dir.exists():
        print(f"⚠️ {engine}: {cache_dir} 不存在")
        return {"engine": engine, "error": "stt_outputs not found"}

    manifest = load_manifest()
    base_cers = []
    format_cers = []
    strict_cers = []
    n = 0

    for sample in manifest:
        sid = sample["id"]
        gt_path = PROJECT_ROOT / sample["gt_file"]
        stt_path = cache_dir / f"{sid}.txt"
        if not gt_path.exists() or not stt_path.exists():
            continue
        gt = gt_path.read_text(encoding="utf-8")
        stt = stt_path.read_text(encoding="utf-8")

        base_cers.append(cer_base(gt, stt))
        format_cers.append(cer_format_only(gt, stt))
        strict_cers.append(cer_strict(gt, stt))
        n += 1

    if not n:
        return {"engine": engine, "error": "no samples"}

    base_avg = sum(base_cers) / n
    fmt_avg = sum(format_cers) / n
    strict_avg = sum(strict_cers) / n

    return {
        "engine":           engine,
        "samples":          n,
        "base_cer":         round(base_avg, 4),
        "format_cer":       round(fmt_avg, 4),
        "strict_cer":       round(strict_avg, 4),
        "delta_format":     round(base_avg - fmt_avg, 4),     # 格式統一可救多少
        "delta_synonym":    round(fmt_avg - strict_avg, 4),    # 同義詞再可救多少
        "delta_total":      round(base_avg - strict_avg, 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", help="單引擎")
    ap.add_argument("--all", action="store_true", help="跑 4 主力引擎")
    ap.add_argument("--write-report", action="store_true", help="寫 markdown 報告")
    args = ap.parse_args()

    if args.all:
        engines = ["chirp3", "scribe", "sensevoice", "gemini25pro"]
    elif args.engine:
        engines = [args.engine]
    else:
        ap.error("須指定 --engine 或 --all")

    results = []
    print(f"{'engine':<14} {'base':>8} {'+format':>9} {'+synonym':>10} {'總可救':>8}")
    print("-" * 60)
    for eng in engines:
        r = analyze_engine(eng)
        if "error" in r:
            print(f"{eng:<14} ❌ {r['error']}")
            continue
        results.append(r)
        print(
            f"{eng:<14} "
            f"{r['base_cer']*100:>6.2f}%  "
            f"{r['format_cer']*100:>7.2f}%  "
            f"{r['strict_cer']*100:>8.2f}%  "
            f"-{r['delta_total']*100:>5.2f}pp"
        )

    print()
    print("分項拆解：")
    print(f"  delta_format  = 全形/半形/元描述移除 可救")
    print(f"  delta_synonym = 同義詞容忍（OCC≈行控等）再救")
    print(f"  delta_total   = 兩者合計 = base - strict")

    if args.write_report and results:
        from datetime import date
        out_dir = PROJECT_ROOT / "experiments" / "regression_cases"
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / f"gt_style_divergence_{date.today().isoformat()}.md"
        md = [
            f"# GT 風格分歧分析 — {date.today().isoformat()}",
            "",
            f"目的：量化「目前 CER 有多少是 GT 與 STT 風格不一致造成」",
            "",
            "## 對照表",
            "",
            "| 引擎 | 樣本 | base CER | +format | +synonym | 總可救 |",
            "|---|---|---|---|---|---|",
        ]
        for r in results:
            md.append(
                f"| {r['engine']} | {r['samples']} | "
                f"{r['base_cer']*100:.2f}% | "
                f"{r['format_cer']*100:.2f}% | "
                f"{r['strict_cer']*100:.2f}% | "
                f"-{r['delta_total']*100:.2f}pp |"
            )
        md.extend([
            "",
            "## 分項拆解說明",
            "",
            "- **base CER**：用既有 batch_eval.normalize_for_cer 計算（含簡繁統一、移除標點）",
            "- **+format**：在 base 之上再做：",
            "  - 全形 ↔ 半形統一（１２３ → 123、ＯＣＣ → OCC）",
            "  - 元描述移除（沉默 N 秒、笑聲、咳嗽 等）",
            "- **+synonym**：在 +format 之上再容忍同義詞表：",
            "  - OCC ≈ 行控 ≈ 行控中心",
            "  - 月台 ≈ 月臺",
            "  - 復電 ≈ 復位電 ≈ 回復電",
            "  - 清車 ≈ 清空 / over ≈ OVER ≈ Over",
            "  - 等",
            "- **總可救**：base - strict，代表「格式 + 同義詞統一可消除的 CER」",
            "",
            "## 解讀",
            "",
            "- 若**總可救 > 5pp**：GT 風格分歧顯著，下個 sprint 應先統一 GT 標註規範",
            "- 若**總可救 < 2pp**：規則庫已不是瓶頸，必須走 fine-tune 路線",
            "- delta_format 偏高 → GT 與 STT 用了不同符號/格式（容易修）",
            "- delta_synonym 偏高 → 業務術語沒有統一規範（需與業務方協調）",
        ])
        md_path.write_text("\n".join(md), encoding="utf-8")
        print()
        print(f"📄 Markdown 報告: {md_path}")


if __name__ == "__main__":
    main()
