#!/usr/bin/env python3
"""
雙層覆蓋率評測
================

對 GT + 一或多個 STT 結果，計算三個指標：

1. CER（字元錯誤率）— 既有
2. PhraseSet Coverage（已收錄詞命中率）
   = STT 中正確出現的「PhraseSet 內」詞數 / GT 中「PhraseSet 內」詞數
3. Key Info Coverage（關鍵資訊命中率）
   = STT 中出現的「GT 關鍵詞」數 / GT 關鍵詞數
   GT 關鍵詞 = 自動 regex 抽取（站碼、設備、動作、編號、通訊）

額外輸出：
- PhraseSet 待擴充清單（GT 關鍵詞 - PhraseSet 已收錄）
- 多引擎並排對比表

用法:
    python3 experiments/llm_correction_poc/coverage_eval.py \\
        --gt experiments/Test_TMRT2正確文稿/UltraLog06320251222192724.txt \\
        --stt sensevoice=db:2 \\
        --stt chirp3=experiments/llm_correction_poc/stt_inputs/UltraLog063_chirp3.txt \\
        --stt gemini31pro=experiments/llm_correction_poc/stt_inputs/UltraLog063_gemini31pro.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "aiSpeechMulti.db"
VOCAB_PATH = PROJECT_ROOT / "vocabulary" / "master_vocabulary.csv"
OUTPUT_DIR = Path(__file__).parent

try:
    import jiwer
except ImportError:
    print("❌ 請先安裝: pip install jiwer")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════
# 文本正規化
# ══════════════════════════════════════════════════════════════════════
try:
    from opencc import OpenCC
    _CC = OpenCC("s2twp")
except Exception:
    _CC = None


def to_traditional(text: str) -> str:
    if _CC and text:
        try:
            return _CC.convert(text)
        except Exception:
            return text
    return text


def normalize_for_cer(text: str) -> str:
    """移除標點/講者標記/簡繁差異，保留實質字元"""
    if not text:
        return ""
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"^[A-Z]:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[\s,，。.、:：;；!?！？\-—()（）\"'\"" "]+", "", text)
    return to_traditional(text)


def normalize_for_match(text: str) -> str:
    """為了詞彙比對的正規化：保留英數字、轉繁體、去空白標點"""
    if not text:
        return ""
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"^[A-Z]:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[\s,，。.、:：;；!?！？\-—()（）\"'\"" "]+", "", text)
    return to_traditional(text)


# ══════════════════════════════════════════════════════════════════════
# PhraseSet 載入
# ══════════════════════════════════════════════════════════════════════
def load_phraseset(path: Path) -> set[str]:
    """從 master_vocabulary.csv 載入所有 term"""
    terms = set()
    if not path.exists():
        return terms
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            term = (row.get("term") or "").strip()
            if term and not term.startswith("#"):
                terms.add(term)
    return terms


# ══════════════════════════════════════════════════════════════════════
# 關鍵詞抽取（regex 規則）
# ══════════════════════════════════════════════════════════════════════
KEY_INFO_PATTERNS = {
    "station_code": r"[GgRr]\d{1,2}",                              # G07, R01
    "equipment":    r"\b(OCC|MTC|ATP|ATO|EDRH|MCP|CBTC|NCP|ETF|VVVF|ASR|MCS|RF|AM)\b",
    "platform":     r"[一二三四五12345]月台|月台門|站台|月台",
    "car_number":   r"\d{1,3}\s*/\s*\d{1,3}\s*車|\d+號?車",
    "action":       r"復電|斷電|清車|停準|未停準|開門|關門|引導|呼叫|通告|回報|登上",
    "comm":         r"\bover\b|收到|稍後|完畢",
    "station_name": r"[\u4e00-\u9fff]{2,4}站(?![長員務台房])",     # 九張犁站、高鐵站（排除站長/站員等）
    "track":        r"上行|下行|正線|三軌|岔心|軌道",
}


def extract_key_terms(text: str) -> dict[str, set[str]]:
    """從文本抽出每類關鍵詞（去重，正規化大小寫）"""
    text_norm = to_traditional(text)
    result = {}
    for cat, pat in KEY_INFO_PATTERNS.items():
        matches = re.findall(pat, text_norm, flags=re.IGNORECASE)
        # findall 對含 group 的 regex 會回傳 group 內容，需要重抓 full match
        full = [m.group(0) for m in re.finditer(pat, text_norm, flags=re.IGNORECASE)]
        # 標準化：英數字大寫、移除空白
        normed = set()
        for m in full:
            m = re.sub(r"\s+", "", m)
            if re.fullmatch(r"[A-Za-z0-9/]+", m):
                m = m.upper()
            normed.add(m)
        result[cat] = normed
    return result


def flatten_key_terms(by_cat: dict[str, set[str]]) -> set[str]:
    out = set()
    for v in by_cat.values():
        out |= v
    return out


# ══════════════════════════════════════════════════════════════════════
# 命中率計算
# ══════════════════════════════════════════════════════════════════════
def hit_rate(needles: set[str], haystack: str) -> tuple[int, int, set[str], set[str]]:
    """計算 needles 在 haystack 中的命中率
    回傳: (hit_count, total_count, hits, misses)
    """
    if not needles:
        return 0, 0, set(), set()
    haystack_norm = normalize_for_match(haystack)
    hits, misses = set(), set()
    for n in needles:
        n_norm = normalize_for_match(n)
        # 英數字術語要大小寫不敏感
        if re.fullmatch(r"[A-Za-z0-9/]+", n_norm):
            if n_norm.upper() in haystack_norm.upper():
                hits.add(n)
            else:
                misses.add(n)
        else:
            if n_norm in haystack_norm:
                hits.add(n)
            else:
                misses.add(n)
    return len(hits), len(needles), hits, misses


# ══════════════════════════════════════════════════════════════════════
# STT 來源載入
# ══════════════════════════════════════════════════════════════════════
def load_stt(spec: str) -> tuple[str, str]:
    """spec 格式: label=source
    source 可以是 'db:N'（從 DB 取 transcription id=N）或檔案路徑"""
    if "=" not in spec:
        raise ValueError(f"--stt 需要 label=source 格式: {spec}")
    label, source = spec.split("=", 1)
    if source.startswith("db:"):
        tid = int(source[3:])
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT transcript FROM transcriptions WHERE id=?", (tid,)
        ).fetchone()
        conn.close()
        if not row:
            raise ValueError(f"DB 找不到 transcription id={tid}")
        return label, row[0]
    else:
        path = Path(source)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return label, path.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def run(args):
    print("🔬 雙層覆蓋率評測")
    print(f"   GT: {args.gt}")
    print()

    # 載入 GT
    gt_path = Path(args.gt)
    if not gt_path.is_absolute():
        gt_path = PROJECT_ROOT / gt_path
    gt_text = gt_path.read_text(encoding="utf-8")

    # 載入 PhraseSet
    phraseset = load_phraseset(VOCAB_PATH)
    print(f"📚 PhraseSet: {len(phraseset)} 條（master_vocabulary.csv）")

    # 抽取 GT 關鍵詞
    gt_keys_by_cat = extract_key_terms(gt_text)
    gt_key_terms = flatten_key_terms(gt_keys_by_cat)
    print(f"🔑 GT 關鍵詞: {len(gt_key_terms)} 個")
    for cat, terms in gt_keys_by_cat.items():
        if terms:
            print(f"      {cat:14} ({len(terms):2}): {sorted(terms)}")

    # GT 中「也屬於 PhraseSet 內」的詞
    gt_phraseset_terms = set()
    gt_norm = normalize_for_match(gt_text)
    for t in phraseset:
        t_norm = normalize_for_match(t)
        if not t_norm:
            continue
        if re.fullmatch(r"[A-Za-z0-9/]+", t_norm):
            if t_norm.upper() in gt_norm.upper():
                gt_phraseset_terms.add(t)
        else:
            if t_norm in gt_norm:
                gt_phraseset_terms.add(t)
    print(f"📌 GT ∩ PhraseSet: {len(gt_phraseset_terms)} 個")
    print()

    # 載入並評測各 STT
    sources = [load_stt(s) for s in args.stt]
    rows = []
    all_misses_keyinfo: dict[str, set[str]] = {}

    for label, stt_text in sources:
        print(f"───── {label} ─────")
        # CER
        cer = jiwer.cer(normalize_for_cer(gt_text), normalize_for_cer(stt_text))
        # PhraseSet 覆蓋率
        ps_hit, ps_total, ps_hits, ps_misses = hit_rate(gt_phraseset_terms, stt_text)
        ps_rate = ps_hit / ps_total if ps_total else 0
        # 關鍵資訊覆蓋率
        ki_hit, ki_total, ki_hits, ki_misses = hit_rate(gt_key_terms, stt_text)
        ki_rate = ki_hit / ki_total if ki_total else 0

        all_misses_keyinfo[label] = ki_misses

        print(f"   CER:                 {cer*100:6.2f}%")
        print(f"   PhraseSet 覆蓋率:    {ps_rate*100:6.2f}%   ({ps_hit}/{ps_total})")
        print(f"   關鍵資訊覆蓋率:      {ki_rate*100:6.2f}%   ({ki_hit}/{ki_total})")
        diff = ps_rate - ki_rate
        if abs(diff) > 0.01:
            sign = "↑" if diff > 0 else "↓"
            print(f"   差距 (PS−KI):        {diff*100:+6.2f}%  {sign}")
        if ki_misses:
            print(f"   遺漏關鍵詞 ({len(ki_misses)}): {sorted(ki_misses)[:10]}{'...' if len(ki_misses)>10 else ''}")
        print()

        rows.append({
            "label": label,
            "cer": round(cer, 4),
            "ps_hit": ps_hit, "ps_total": ps_total, "ps_rate": round(ps_rate, 4),
            "ki_hit": ki_hit, "ki_total": ki_total, "ki_rate": round(ki_rate, 4),
            "ps_hits": sorted(ps_hits),
            "ps_misses": sorted(ps_misses),
            "ki_hits": sorted(ki_hits),
            "ki_misses": sorted(ki_misses),
        })

    # PhraseSet 待擴充清單：GT 關鍵詞 - PhraseSet 已收錄
    ps_norm_set = {normalize_for_match(t).upper() if re.fullmatch(r"[A-Za-z0-9/]+", normalize_for_match(t)) else normalize_for_match(t) for t in phraseset}
    gap_terms = []
    for t in sorted(gt_key_terms):
        t_norm = normalize_for_match(t)
        key = t_norm.upper() if re.fullmatch(r"[A-Za-z0-9/]+", t_norm) else t_norm
        if key not in ps_norm_set:
            gap_terms.append(t)

    print("═" * 60)
    print(f"📊 PhraseSet 待擴充清單（GT 關鍵詞 - 已收錄）")
    print(f"   共 {len(gap_terms)} 個未收錄關鍵詞")
    for t in gap_terms[:30]:
        print(f"   + {t}")
    if len(gap_terms) > 30:
        print(f"   ... 還有 {len(gap_terms)-30} 個")

    # 自動匯入功能
    import_result = None
    if getattr(args, "auto_import", False) and gap_terms:
        print()
        print("═" * 60)
        if args.dry_run:
            print(f"🔎 自動匯入預覽（--dry-run 模式，不寫入）")
        else:
            print(f"📥 自動匯入 master_vocabulary.csv")
        import_result = auto_import_to_master_vocab(
            gap_terms, gt_keys_by_cat, dry_run=args.dry_run
        )
        print()
        print(f"   ✅ 新增: {len(import_result['added'])} 條")
        for r in import_result["added"]:
            print(f"      + {r['term']:15} category={r['category']:14} boost={r['boost_value']}")
        if import_result["skipped"]:
            print(f"   ⏭️  略過: {len(import_result['skipped'])} 條")
            for s in import_result["skipped"]:
                print(f"      · {s['term']:15} ({s['reason']})")
        if not args.dry_run:
            print()
            if import_result["regen_ok"]:
                print(f"   ✅ 下游檔案重新生成完成")
                print(f"      · vocabulary/google_phrases.json")
                print(f"      · vocabulary/correction_dict.py")
                print(f"      · vocabulary/alert_keywords.json")
            else:
                print(f"   ❌ 下游檔案重新生成失敗")
                print(import_result["regen_output"])
            print()
            print(f"   ℹ️  建議下一步：手動編輯 master_vocabulary.csv，補上 common_error 欄位")
            print(f"      然後再執行 vocabulary/generate_vocabulary_files.py 一次")

    # 寫出報告
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / f"coverage_{ts}.json"
    md_path = OUTPUT_DIR / f"coverage_{ts}.md"

    json_path.write_text(json.dumps({
        "meta": {
            "timestamp": ts,
            "gt_file": str(gt_path),
            "phraseset_size": len(phraseset),
            "gt_key_terms_count": len(gt_key_terms),
            "gt_phraseset_intersect": len(gt_phraseset_terms),
            "auto_import": import_result,
        },
        "gt_key_terms_by_category": {k: sorted(v) for k, v in gt_keys_by_cat.items()},
        "results": rows,
        "phraseset_gap": gap_terms,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown 報告
    md = [
        f"# 雙層覆蓋率評測報告",
        f"",
        f"- **時間**: {ts}",
        f"- **GT 檔案**: `{gt_path.name}`",
        f"- **PhraseSet 大小**: {len(phraseset)} 條",
        f"- **GT 關鍵詞**: {len(gt_key_terms)} 個（regex 自動抽取）",
        f"- **GT ∩ PhraseSet**: {len(gt_phraseset_terms)} 個",
        f"",
        f"## 📊 三引擎並排對比",
        f"",
        f"| 引擎 | CER | PhraseSet 覆蓋率 | 關鍵資訊覆蓋率 | 差距(PS−KI) |",
        f"|---|---|---|---|---|",
    ]
    for r in rows:
        diff = r["ps_rate"] - r["ki_rate"]
        md.append(
            f"| **{r['label']}** | {r['cer']*100:.2f}% | "
            f"{r['ps_rate']*100:.2f}% ({r['ps_hit']}/{r['ps_total']}) | "
            f"{r['ki_rate']*100:.2f}% ({r['ki_hit']}/{r['ki_total']}) | "
            f"{diff*100:+.2f}% |"
        )

    md += [
        f"",
        f"## 🔑 GT 關鍵詞分類",
        f"",
    ]
    for cat, terms in gt_keys_by_cat.items():
        if terms:
            md.append(f"- **{cat}** ({len(terms)}): " + "、".join(f"`{t}`" for t in sorted(terms)))

    md += [
        f"",
        f"## 📌 PhraseSet 待擴充清單（共 {len(gap_terms)} 個）",
        f"",
        f"以下關鍵詞出現在 GT 中，但**未被 master_vocabulary.csv 收錄**，建議擴充：",
        f"",
    ]
    for t in gap_terms:
        md.append(f"- `{t}`")

    md += [f"", f"## ❌ 各引擎遺漏的關鍵詞", f""]
    for r in rows:
        if r["ki_misses"]:
            md.append(f"### {r['label']} (遺漏 {len(r['ki_misses'])} 個)")
            md.append("")
            md.append("、".join(f"`{t}`" for t in r["ki_misses"]))
            md.append("")

    md_path.write_text("\n".join(md), encoding="utf-8")

    print()
    print(f"📄 JSON: {json_path}")
    print(f"📄 報告: {md_path}")


def auto_import_to_master_vocab(gap_terms: list[str], gt_keys_by_cat: dict[str, set[str]], dry_run: bool = False) -> dict:
    """將未收錄的關鍵字自動匯入 master_vocabulary.csv 並重新生成下游檔案

    Args:
        gap_terms: 未收錄關鍵字清單
        gt_keys_by_cat: GT 關鍵字分類，用於推斷 category
        dry_run: True 時只回傳預覽，不實際寫檔

    Returns:
        {
            "added": [{"term": ..., "category": ..., "boost_value": ..., ...}],
            "skipped": [{"term": ..., "reason": ...}],
            "regen_ok": bool,
            "regen_output": str,
        }
    """
    if not gap_terms:
        return {"added": [], "skipped": [], "regen_ok": True, "regen_output": "（無新詞）"}

    # 從分類反查 category
    cat_lookup = {}
    for cat, terms in gt_keys_by_cat.items():
        for t in terms:
            cat_lookup[t] = cat

    # 規則：類別 → master_vocabulary 的 category + boost_value 預設值
    CATEGORY_DEFAULTS = {
        "station_code": ("station_code", 20, 0),
        "equipment":    ("equipment",    20, 1),
        "platform":     ("location",     15, 0),
        "car_number":   ("equipment",    18, 0),
        "action":       ("action",       15, 1),
        "comm":         ("command",      12, 0),
        "station_name": ("location",     18, 0),
        "track":        ("location",     15, 1),
    }

    added = []
    skipped = []

    # 讀取現有 CSV，避免重複
    existing_terms = set()
    if VOCAB_PATH.exists():
        with open(VOCAB_PATH, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = (row.get("term") or "").strip()
                if t and not t.startswith("#"):
                    existing_terms.add(t)

    new_rows_csv = []
    for term in gap_terms:
        if term in existing_terms:
            skipped.append({"term": term, "reason": "已存在"})
            continue
        cat = cat_lookup.get(term, "other")
        defaults = CATEGORY_DEFAULTS.get(cat, ("other", 12, 0))
        category, boost_value, alert_level = defaults
        # CSV 欄位順序: term,category,boost_value,alert_level,pinyin,common_error,description
        row = {
            "term": term,
            "category": category,
            "boost_value": str(boost_value),
            "alert_level": str(alert_level),
            "pinyin": "",
            "common_error": "",
            "description": f"GT 偵測自動補充（{cat}）",
        }
        new_rows_csv.append(row)
        added.append(row)

    if dry_run or not new_rows_csv:
        return {"added": added, "skipped": skipped, "regen_ok": True, "regen_output": "(dry-run)"}

    # 附加到 CSV 末尾，加上分組註解
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(VOCAB_PATH, "a", encoding="utf-8", newline="") as f:
        f.write(f"\n# ============================================================================\n")
        f.write(f"# GT 偵測自動補充（{timestamp}）\n")
        f.write(f"# 來源: experiments/llm_correction_poc/coverage_eval.py --auto-import\n")
        f.write(f"# ============================================================================\n")
        writer = csv.DictWriter(
            f,
            fieldnames=["term", "category", "boost_value", "alert_level", "pinyin", "common_error", "description"],
        )
        for row in new_rows_csv:
            writer.writerow(row)

    # 自動執行 generate_vocabulary_files.py
    import subprocess
    regen_ok = True
    regen_output = ""
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "vocabulary" / "generate_vocabulary_files.py")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        regen_output = (result.stdout + result.stderr)[-500:]
        regen_ok = result.returncode == 0
    except Exception as e:
        regen_ok = False
        regen_output = f"執行失敗: {e}"

    return {"added": added, "skipped": skipped, "regen_ok": regen_ok, "regen_output": regen_output}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gt", required=True, help="Ground truth 文稿路徑")
    p.add_argument(
        "--stt",
        action="append",
        required=True,
        help="STT 來源，格式: label=source（source 可為檔案路徑或 db:N）",
    )
    p.add_argument(
        "--auto-import",
        action="store_true",
        help="將未收錄的關鍵字自動匯入 master_vocabulary.csv 並重新生成下游檔案",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="搭配 --auto-import 使用：只預覽不實際寫入",
    )
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
