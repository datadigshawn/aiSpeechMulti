#!/usr/bin/env python3
"""
GT 衛生檢查 + 事後事件分類
==========================
配合「GT 不分講者」決策與擴資料流程：聽打時只管忠實逐字，分類/檢查事後批次補。

兩個功能（預設都跑，可用旗標只跑其一）：
  1. lint     — GT 檔衛生檢查：殘留講者標記、空檔/空行、方括號標註、全形數字、
                疑似亂碼編碼、檔名格式。違反 [[GT 產製標準 — 不分講者]] 者標記。
  2. classify — emergency 篩選（高召回關鍵字）。⚠️ 子類（control/door/track/daily）
                自動分類實測不可靠（詞彙高度重疊），只給「建議」不可當權威；真正可靠
                且有價值的是 emergency vs routine 這條軸。

非破壞性：只輸出報告。可加 --csv 匯出 id→suggested（供 manifest 參考）。

用法：
    python scripts/gt_lint.py                          # 全 ground_truth（legacy 會大量觸發講者標記）
    python scripts/gt_lint.py new1.txt new2.txt        # ★ 只檢查新檔（擴資料時的主用法）
    python scripts/gt_lint.py --only lint --summary    # 只看統計不逐檔列
    python scripts/gt_lint.py --only classify --csv /tmp/events.csv
"""
import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "ground_truth"

# 檔名：([A-Z]?\d{3,4})_(event)_(rest)  —— 與 build_golden_manifest 一致
FILENAME_PATTERN = re.compile(r"^([A-Z]?\d{3,4})_(\w+?)_(.+)$")
KNOWN_EVENT_TYPES = {"daily", "door", "track", "emergency", "control"}

SPEAKER_RE = re.compile(r"^\s*[A-Za-z?]:\s*", re.MULTILINE)
BRACKET_RE = re.compile(r"\[[^\]]*\]|【[^】]*】")
FULLWIDTH_DIGIT_RE = re.compile(r"[０-９]")
# 雙重編碼亂碼的指紋字元（UTF-8 被當 latin-1 顯示時常見）
MOJIBAKE_RE = re.compile(r"[ÂÃÅÆÇÈÉÊÌÍÎÏÐÑÒÓÔÕ×Ø]")

# ── 分類關鍵字（台中捷運無線電領域）────────────────────────────────
# emergency 高召回（最關鍵、最該補的類）；任一命中即判 emergency
EMERGENCY_KW = [
    "故障", "異常", "緊急", "事故", "起火", "冒煙", "火災", "濃煙", "停電", "跳電",
    "斷電", "受傷", "救護", "送醫", "疏散", "撤離", "脫軌", "出軌", "受困", "夾傷",
    "昏倒", "墜", "落軌", "侵入", "闖入", "洩漏", "求救", "警報", "拋錨", "搶修",
    "復點", "無法移動", "煞不住", "救援", "119", "卡住",
]
# 子類（非 emergency 時的建議值；control 詞彙最氾濫，當預設 fallback）
SUBTYPE_KW = {
    "door":  ["月台門", "車門", "開門", "關門", "屏蔽門", "閘門", "psd"],
    "track": ["軌道", "道岔", "轉轍器", "號誌", "股道", "鋼軌", "巡軌", "異物", "路線"],
    "daily": ["巡檢", "例行", "點名", "測試", "交接班", "待命"],
}


def read_text(p: Path):
    """回傳 (text, encoding_ok)。strict utf-8 失敗 → encoding_ok=False（用寬鬆解碼續跑）。"""
    raw = p.read_bytes()
    try:
        return raw.decode("utf-8-sig"), True
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), False


def lint_one(p: Path):
    issues = []
    text, enc_ok = read_text(p)
    if not enc_ok:
        issues.append("編碼非 UTF-8（疑似亂碼）")
    if MOJIBAKE_RE.search(text):
        issues.append("含雙重編碼亂碼指紋字元")
    if not text.strip():
        issues.append("空檔")
    sp = SPEAKER_RE.findall(text)
    if sp:
        issues.append(f"殘留講者標記 ×{len(sp)}（違反不分講者標準）")
    br = BRACKET_RE.findall(text)
    if br:
        issues.append(f"方括號標註 {br[:3]}（全集需一致）")
    if FULLWIDTH_DIGIT_RE.search(text):
        issues.append("含全形數字（應半形）")
    if re.search(r"\n[ \t]*\n", text):
        issues.append("含空行")
    if any(line != line.strip() and line.strip() for line in text.splitlines()):
        issues.append("行首/尾多餘空白")
    # 檔名格式
    m = FILENAME_PATTERN.match(p.stem)
    if not m:
        issues.append("檔名不符格式 id_event_…")
    elif m.group(2) not in KNOWN_EVENT_TYPES:
        issues.append(f"檔名 event_type 非已知值: {m.group(2)}")
    return issues


def classify_one(text: str):
    """回傳 (label, matched, subtype_hint)。
    label = 'emergency'（命中告警關鍵字）或 'routine'。subtype_hint 僅供參考、不可靠。"""
    low = text.lower()
    em = [k for k in EMERGENCY_KW if k.lower() in low]
    if em:
        return "emergency", em, ""
    scores = {et: sum(1 for k in kws if k.lower() in low) for et, kws in SUBTYPE_KW.items()}
    hint = max(scores, key=scores.get) if any(scores.values()) else "control?"
    return "routine", [], hint


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="指定要檢查的 GT 檔（省略則掃 --gt-dir 全集）")
    ap.add_argument("--gt-dir", default=str(DEFAULT_GT_DIR))
    ap.add_argument("--only", choices=["lint", "classify"], help="只跑其一（預設兩者都跑）")
    ap.add_argument("--summary", action="store_true", help="lint 只印統計，不逐檔列")
    ap.add_argument("--csv", default="", help="把 id→label 匯出到 CSV")
    args = ap.parse_args()

    if args.files:
        files = sorted(Path(f) for f in args.files)
    else:
        gt_dir = Path(args.gt_dir)
        if not gt_dir.is_absolute():
            gt_dir = PROJECT_ROOT / gt_dir
        files = sorted(gt_dir.glob("*.txt"))
    if not files:
        print("❌ 找不到 .txt")
        sys.exit(1)
    print(f"📂 共 {len(files)} 檔\n")

    do_lint = args.only in (None, "lint")
    do_cls = args.only in (None, "classify")

    # ── lint ──
    if do_lint:
        print("═" * 60)
        print("① GT 衛生檢查")
        print("═" * 60)
        n_clean = 0
        issue_counter = Counter()
        for p in files:
            issues = lint_one(p)
            if issues:
                if not args.summary:
                    print(f"  ⚠️ {p.stem}")
                    for it in issues:
                        print(f"       - {it}")
                for it in issues:
                    issue_counter[it.split("（")[0].split("×")[0].strip()] += 1
            else:
                n_clean += 1
        print(f"\n  乾淨 {n_clean}/{len(files)}；問題類型統計：{dict(issue_counter)}")
        if issue_counter.get("殘留講者標記"):
            print("  註：legacy 檔含講者標記屬已知可接受（normalization 會剝）；"
                  "此檢查主要針對『新檔』。")
        print()

    # ── classify（emergency 篩選）──
    rows = []
    if do_cls:
        print("═" * 60)
        print("② Emergency 篩選（⚠️ 子類不可靠，僅 emergency vs routine 可信）")
        print("═" * 60)
        n_em = 0
        miss = []   # 檔名=emergency 但無告警關鍵字（可能漏標/關鍵字缺）
        extra = []  # 命中告警關鍵字但檔名≠emergency（可能該升級為 emergency）
        for p in files:
            text, _ = read_text(p)
            label, matched, hint = classify_one(text)
            m = FILENAME_PATTERN.match(p.stem)
            fid = m.group(1) if m else p.stem
            existing = m.group(2) if m else "?"
            rows.append((fid, existing, label, ";".join(matched), hint))
            if label == "emergency":
                n_em += 1
                if existing != "emergency":
                    extra.append((fid, existing, matched[:3]))
            elif existing == "emergency":
                miss.append(fid)
        print(f"  命中告警關鍵字（建議 emergency）：{n_em} 檔")
        if extra:
            print(f"\n  ❗ 檔名非 emergency 但含告警字（複查是否該升級）：")
            for fid, ex, kw in extra:
                print(f"     {fid:<8} 檔名={ex:<10} kw={kw}")
        if miss:
            print(f"\n  🔍 檔名=emergency 但無告警關鍵字（複查標籤或補關鍵字）：{miss}")
        if not extra and not miss:
            print("  ✅ emergency 標籤與內容一致")
        print()

    if args.csv and rows:
        out = Path(args.csv)
        with open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "filename_event", "label", "matched_kw", "subtype_hint"])
            w.writerows(rows)
        print(f"✅ 分類結果匯出至 {out}")


if __name__ == "__main__":
    main()
