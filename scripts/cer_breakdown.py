#!/usr/bin/env python3
"""
cer_breakdown.py — CER 錯誤類型拆解（C3）

目的
----
把 CER 拆成錯誤類型（數字 / 術語 / 繁簡 / 同音 / 近音 / 漏字 / 插入 / 其他），
算出每類佔總錯誤的比例，導出「下一個優化作業該攻哪」——哪些規則可救、
哪些卡在 fine-tune / 音訊。

做法
----
- 對齊 GT vs STT(raw) 用 jiwer.process_characters（真正的最小編輯距離，與 cer_engine 的 CER 同引擎）；
  無 jiwer 才退回 difflib（會高估 insert/delete）。
- normalize 沿用 cer_engine.normalize_text，並先剝除 GT 講者標籤（B:/H:）避免灌大 deletion；繁簡用 opencc 偵測。
- 替換類分類優先序：number > term > 繁簡 > homophone > near_homophone > other。
- 報告為 micro（總錯/總字，長段加權）；batch_eval 頭條是 macro（逐段平均），兩者數值會差，但比例可信。

用法
----
  # 需 conda aiSpeech_project_nightly（含 pypinyin / opencc）
  python scripts/cer_breakdown.py --label sensevoice_ft_v2_157gt
  python scripts/cer_breakdown.py --label sensevoice_ft_r32_full --eval-set experiments/golden_dataset/eval_set.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.cer_engine import normalize_text, read_transcript_file  # noqa: E402

MANIFEST = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"
STT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "stt_outputs"
TERM_FILTER = PROJECT_ROOT / "vocabulary" / "term_filter.json"
OUT_DIR = PROJECT_ROOT / "experiments" / "llm_correction_poc"

# ── 選用依賴 ──────────────────────────────────────────────────────────
try:
    from pypinyin import Style, lazy_pinyin
    _PINYIN = True
except ImportError:
    _PINYIN = False

try:
    import opencc
    _T2S = opencc.OpenCC("t2s")  # 繁→簡，兩邊都轉簡比對即可偵測繁簡互換
    _CC = True
except Exception:
    _CC = False

try:
    import jiwer  # 真正的最小編輯距離對齊（與 cer_engine 的 CER 一致）
    _JIWER = True
except ImportError:
    _JIWER = False

NUM_RE = re.compile(r"[0-9零一二三四五六七八九十百千萬兩]")
# GT 行首講者標籤（B: / H: / A: / ?:），非口說內容；cer_engine.normalize_text 不會去除，
# 會被當成漏字而灌大 deletion，故拆解前先剝除。
SPEAKER_RE = re.compile(r"^\s*[A-Za-z?]:\s*", re.MULTILINE)


def clean_norm(text: str) -> str:
    """剝除講者標籤後再做 CER 正規化。"""
    return normalize_text(SPEAKER_RE.sub("", text))

# 類別 → 是否「規則可救」（決策對照用）
RULE_FIXABLE = {
    "number": "規則可救（條件化 number_norm）",
    "term": "規則可救（overlay / prompt）",
    "繁簡": "規則可救（normalize 加繁簡）",
    "homophone": "多半需 fine-tune",
    "near_homophone": "多半需 fine-tune",
    "deletion": "需 fine-tune / 音訊",
    "insertion": "需 fine-tune",
    "other_sub": "待再細分",
}


# ── 載入 ──────────────────────────────────────────────────────────────
def load_terms() -> set[str]:
    if not TERM_FILTER.exists():
        return set()
    d = json.loads(TERM_FILTER.read_text(encoding="utf-8"))
    terms: set[str] = set(d.get("whitelist", []))
    bl = d.get("blacklist", {})
    if isinstance(bl, dict):
        for k, v in bl.items():
            terms.add(k)
            if isinstance(v, str):
                terms.add(v)
    return {normalize_text(t) for t in terms if t}


def load_manifest() -> dict[str, dict]:
    rows = {}
    with MANIFEST.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows[str(r["id"])] = r
    return rows


def load_eval_set(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = data["ids"] if isinstance(data, dict) else data
    return {str(i) for i in ids}


# ── 分類 ──────────────────────────────────────────────────────────────
def _py(s: str, tone: bool) -> list[str]:
    style = Style.TONE3 if tone else Style.NORMAL
    return lazy_pinyin(s, style=style)


def is_variant(wrong: str, right: str) -> bool:
    """繁簡互換：兩邊轉簡體後相等。"""
    return _CC and wrong != right and _T2S.convert(wrong) == _T2S.convert(right)


def classify_sub(wrong: str, right: str, terms: set[str]) -> str:
    """分類一個替換 (wrong→right)。優先序 number > term > 繁簡 > homophone > near > other。"""
    if NUM_RE.search(wrong) or NUM_RE.search(right):
        return "number"
    if right in terms or wrong in terms:
        return "term"
    if is_variant(wrong, right):
        return "繁簡"
    if _PINYIN and len(wrong) == len(right):
        if _py(wrong, True) == _py(right, True):
            return "homophone"
        if _py(wrong, False) == _py(right, False):
            return "near_homophone"
    return "other_sub"


def breakdown_segment(gt: str, hyp: str, terms: set[str]) -> list[dict]:
    """回傳該段每個錯誤：{type, wrong(STT), right(GT), n_err}。

    wrong = STT 產出（錯的），right = GT（正確）。
    優先用 jiwer 真實 Levenshtein 對齊（與 CER 計數一致）；無 jiwer 才退回 difflib。
    """
    ref = clean_norm(gt)   # GT（剝講者標籤）
    hy = clean_norm(hyp)   # STT
    errs = []

    if _JIWER and ref and hy:
        out = jiwer.process_characters(ref, hy)
        for c in out.alignments[0]:
            if c.type == "equal":
                continue
            r = ref[c.ref_start_idx:c.ref_end_idx]   # 正確
            h = hy[c.hyp_start_idx:c.hyp_end_idx]     # STT
            if c.type == "delete":       # GT 有、STT 缺 → 漏字
                errs.append({"type": "deletion", "wrong": "", "right": r, "n_err": len(r)})
            elif c.type == "insert":     # STT 多、GT 無 → 幻覺/重複
                errs.append({"type": "insertion", "wrong": h, "right": "", "n_err": len(h)})
            else:                        # substitute（字元對齊，逐字分類）
                if len(r) == len(h):
                    for rc, hc in zip(r, h):
                        errs.append({"type": classify_sub(hc, rc, terms),
                                     "wrong": hc, "right": rc, "n_err": 1})
                else:
                    errs.append({"type": classify_sub(h, r, terms),
                                 "wrong": h, "right": r, "n_err": max(len(r), len(h))})
        return errs

    # ── fallback：difflib（非最小編輯距離，會高估 insert/delete）──
    sm = SequenceMatcher(None, hy, ref, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        wrong, right = hy[i1:i2], ref[j1:j2]
        if tag == "delete":
            errs.append({"type": "insertion", "wrong": wrong, "right": "", "n_err": i2 - i1})
        elif tag == "insert":
            errs.append({"type": "deletion", "wrong": "", "right": right, "n_err": j2 - j1})
        else:
            errs.append({"type": classify_sub(wrong, right, terms),
                         "wrong": wrong, "right": right, "n_err": max(i2 - i1, j2 - j1)})
    return errs


# ── 主流程 ────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="CER 錯誤類型拆解")
    ap.add_argument("--label", required=True, help="stt_outputs/{label}/ 子目錄名")
    ap.add_argument("--eval-set", help="凍結評測集 JSON（只算其中 id）")
    ap.add_argument("--out", help="逐錯誤 CSV 輸出路徑")
    args = ap.parse_args()

    if not _PINYIN:
        print("⚠️ 無 pypinyin → homophone/near_homophone 無法分類（會落入 other_sub）")
    if not _CC:
        print("⚠️ 無 opencc → 繁簡無法分類")

    terms = load_terms()
    manifest = load_manifest()
    eval_ids = load_eval_set(Path(args.eval_set)) if args.eval_set else None
    label_dir = STT_DIR / args.label
    if not label_dir.is_dir():
        print(f"❌ 找不到 {label_dir}")
        sys.exit(1)

    cat_err = Counter()          # 類別 → 錯誤字數
    cat_cnt = Counter()          # 類別 → 錯誤 block 數
    by_event = defaultdict(Counter)
    rows = []
    n_seg = 0
    seg_cer = []  # (id, n_err, n_ref)

    for sid, mrow in manifest.items():
        if eval_ids is not None and sid not in eval_ids:
            continue
        stt_file = label_dir / f"{sid}.txt"
        gt_file = PROJECT_ROOT / mrow["gt_file"]
        if not stt_file.exists() or not gt_file.exists():
            continue
        gt = read_transcript_file(gt_file)
        hyp = read_transcript_file(stt_file)
        n_ref = len(clean_norm(gt))
        if n_ref == 0:
            continue
        n_seg += 1
        errs = breakdown_segment(gt, hyp, terms)
        seg_err = sum(e["n_err"] for e in errs)
        seg_cer.append((sid, seg_err, n_ref))
        for e in errs:
            cat_err[e["type"]] += e["n_err"]
            cat_cnt[e["type"]] += 1
            by_event[mrow["event_type"]][e["type"]] += e["n_err"]
            rows.append({"id": sid, "event_type": mrow["event_type"], **e})

    total_err = sum(cat_err.values())
    if total_err == 0:
        print("❌ 無錯誤可拆（檢查 label / eval-set）")
        sys.exit(1)

    # ── 輸出報告 ──
    print(f"\n=== CER 錯誤類型拆解：{args.label} ===")
    scope = f"凍結集 {len(eval_ids)} ids" if eval_ids else "全部有 cache 的段"
    print(f"範圍：{scope} → 命中 {n_seg} 段，總錯誤 {total_err} 字\n")
    print(f"  {'類別':<14} {'錯誤字':>7} {'佔比':>7} {'block':>6}  決策")
    for cat, ne in cat_err.most_common():
        print(f"  {cat:<14} {ne:>7} {ne / total_err * 100:>6.1f}% {cat_cnt[cat]:>6}  {RULE_FIXABLE.get(cat,'')}")

    # 規則可救 vs 需 fine-tune 匯總
    fixable = sum(ne for c, ne in cat_err.items() if c in ("number", "term", "繁簡"))
    model = sum(ne for c, ne in cat_err.items() if c in ("homophone", "near_homophone", "deletion", "insertion"))
    print(f"\n  → 規則可救合計：{fixable / total_err * 100:.1f}%（number+term+繁簡）")
    print(f"  → 需 fine-tune/音訊：{model / total_err * 100:.1f}%（同音+近音+漏字+插入）")
    print(f"  → other_sub：{cat_err.get('other_sub',0) / total_err * 100:.1f}%")

    # 最差 5 段
    seg_cer.sort(key=lambda x: x[1] / x[2], reverse=True)
    print(f"\n最差 5 段（CER）：")
    for sid, ne, nr in seg_cer[:5]:
        print(f"  {sid:<8} CER {ne / nr * 100:>5.1f}%  ({ne}/{nr} 字)")

    # 逐錯誤 CSV
    out_csv = Path(args.out) if args.out else OUT_DIR / f"cer_breakdown_{args.label}.csv"
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["id", "event_type", "type", "wrong", "right", "n_err"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["n_err"], reverse=True))
    print(f"\n逐錯誤 CSV：{out_csv}")


if __name__ == "__main__":
    main()
