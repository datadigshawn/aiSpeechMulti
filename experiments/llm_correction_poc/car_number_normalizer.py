#!/usr/bin/env python3
"""
車廂編號正規化模組
==================

針對 STT 辨識結果中車廂編號的多種變體，正規化為標準格式：

    輸入                       → 輸出
    ──────────────────────────────────────
    2526車                    → 25/26 車
    2526車門                  → 25/26 車門
    25/26 車                  → 25/26 車
    5/6車                     → 05/06 車（補零）
    兩五兩六車                → 25/26 車（中文 → 數字）
    腰洞車                    → 10 車（軍事數字）
    一零車門                  → 10 車門
    G07二月台2526車門         → G07二月台25/26 車門（不誤動 G07）
    車組兩勾三棟              → 車組兩勾三棟（保留車組 ID）

設計原則：
- 只在「車/車門/動車/動車門」前正規化
- 「車組」「車站」「車輛」前的數字不動
- 不確定時保留原文（保守模式）

用法：
    # 模組
    from car_number_normalizer import normalize_car_numbers
    text2 = normalize_car_numbers("STT 結果...")

    # CLI 測試
    python3 car_number_normalizer.py --test
    python3 car_number_normalizer.py --text "G07二月台2526車門"
    python3 car_number_normalizer.py --file path/to/stt.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ── 中文 / 軍事數字對照表 ────────────────────────────────────────────
CHINESE_DIGITS = {
    # 標準中文
    "零": "0", "〇": "0",
    "一": "1", "壹": "1",
    "二": "2", "兩": "2", "貳": "2",
    "三": "3", "參": "3", "叁": "3",
    "四": "4", "肆": "4",
    "五": "5", "伍": "5",
    "六": "6", "陸": "6",
    "七": "7", "柒": "7",
    "八": "8", "捌": "8",
    "九": "9", "玖": "9",
    # 軍事/無線電專用
    "洞": "0",
    "么": "1", "腰": "1",
    "拐": "7",
    "勾": "9",
}

# 中文/軍事數字字元集合（用於 regex）
CHN_DIGIT_CHARS = "".join(CHINESE_DIGITS.keys())
CHN_DIGIT_CLASS = f"[{CHN_DIGIT_CHARS}]"


def chinese_to_arabic(s: str) -> str:
    """將中文/軍事數字字串轉成阿拉伯數字。非數字字元保留。"""
    return "".join(CHINESE_DIGITS.get(c, c) for c in s)


# ══════════════════════════════════════════════════════════════════════
# 主正規化函式
# ══════════════════════════════════════════════════════════════════════
def normalize_car_numbers(text: str) -> tuple[str, list[dict]]:
    """正規化車廂編號

    回傳: (修正後文字, 修正紀錄列表)
    每筆修正紀錄: {"from": "...", "to": "...", "rule": "..."}
    """
    if not text:
        return text, []

    changes: list[dict] = []
    result = text

    # ───────────────────────────────────────────────────────────────
    # Pass 1: 中文/軍事數字 → 阿拉伯數字（僅限「車*」前的連續數字片段）
    # ───────────────────────────────────────────────────────────────
    # 匹配 2-4 個中文數字 + 車/車門/動車/動車門（不含 車組/車站/車輛）
    chn_pattern = re.compile(
        rf"({CHN_DIGIT_CLASS}{{2,4}})\s*(動車門|動車|車門|車(?![組站輛]))"
    )

    def chn_to_arabic_repl(m):
        chn_seq = m.group(1)
        suffix = m.group(2)
        arabic = chinese_to_arabic(chn_seq)
        if not arabic.isdigit():
            return m.group(0)
        new = arabic + suffix
        changes.append({
            "from": m.group(0),
            "to": new,
            "rule": "chn_to_arabic",
        })
        return new

    result = chn_pattern.sub(chn_to_arabic_repl, result)

    # ───────────────────────────────────────────────────────────────
    # Pass 2: 4 位數字 → 拆成 XX/YY 配對
    # ───────────────────────────────────────────────────────────────
    # 順序很重要：先處理長後綴（動車門 → 動車 → 車門 → 車）
    pair_rules = [
        # (suffix_pattern, output_suffix)
        (r"動車門", "動車門"),
        (r"動車",   "動車"),
        (r"車門",   "車門"),
    ]

    for suf_pat, out_suf in pair_rules:
        pattern = re.compile(rf"(?<![\d/])(\d{{2}})(\d{{2}})\s*{suf_pat}")

        def split_repl(m, _out=out_suf):
            a, b = m.group(1), m.group(2)
            new = f"{a}/{b} {_out}"
            changes.append({"from": m.group(0), "to": new, "rule": f"split_4digit_{_out}"})
            return new

        result = pattern.sub(split_repl, result)

    # 「車」單字版本（要排除車組/車站/車輛/車門/車掌/車廂…）
    pattern_car = re.compile(r"(?<![\d/])(\d{2})(\d{2})\s*車(?![組站輛門掌廂])")

    def split_car_repl(m):
        a, b = m.group(1), m.group(2)
        new = f"{a}/{b} 車"
        changes.append({"from": m.group(0), "to": new, "rule": "split_4digit_車"})
        return new

    result = pattern_car.sub(split_car_repl, result)

    # ───────────────────────────────────────────────────────────────
    # Pass 3: 已是 X/Y 格式 → 標準化（補零 + 空格）
    # ───────────────────────────────────────────────────────────────
    slash_pattern = re.compile(
        r"(\d{1,2})\s*[/／]\s*(\d{1,2})\s*(動車門|動車|車門|車(?![組站輛]))"
    )

    def slash_repl(m):
        a, b, suf = m.group(1), m.group(2), m.group(3)
        new = f"{a.zfill(2)}/{b.zfill(2)} {suf}"
        if new != m.group(0):
            changes.append({"from": m.group(0), "to": new, "rule": "slash_normalize"})
        return new

    result = slash_pattern.sub(slash_repl, result)

    # ───────────────────────────────────────────────────────────────
    # Pass 4: 1-2 位數字 + 車* → 補空格（單節車廂）
    # ───────────────────────────────────────────────────────────────
    single_rules = [
        (r"動車門", "動車門"),
        (r"動車",   "動車"),
        (r"車門",   "車門"),
    ]

    for suf_pat, out_suf in single_rules:
        # 注意 (?<![\d/]) 避免 25/26 的 6 又被當成單獨車號
        pattern = re.compile(rf"(?<![\d/])(\d{{1,2}})\s*{suf_pat}")

        def single_repl(m, _out=out_suf):
            num = m.group(1)
            # 已經有空格就不重複加
            new = f"{num} {_out}"
            if new != m.group(0):
                changes.append({"from": m.group(0), "to": new, "rule": f"space_single_{_out}"})
            return new

        result = pattern.sub(single_repl, result)

    # 單獨「車」（排除特殊組合詞）
    pattern_single_car = re.compile(r"(?<![\d/])(\d{1,2})\s*車(?![組站輛門掌廂])")

    def single_car_repl(m):
        num = m.group(1)
        new = f"{num} 車"
        if new != m.group(0):
            changes.append({"from": m.group(0), "to": new, "rule": "space_single_車"})
        return new

    result = pattern_single_car.sub(single_car_repl, result)

    # 去除可能多出的雙空格
    result = re.sub(r"  +", " ", result)

    return result, changes


# ══════════════════════════════════════════════════════════════════════
# 內建測試集
# ══════════════════════════════════════════════════════════════════════
TEST_CASES = [
    # (輸入, 預期輸出, 說明)
    ("2526車門", "25/26 車門", "4 位數字 + 車門"),
    ("2526車",   "25/26 車",   "4 位數字 + 車"),
    ("0506車",   "05/06 車",   "4 位數字含前導 0"),
    ("10車",     "10 車",      "1-2 位數字 + 車"),
    ("10車門",   "10 車門",    "1-2 位數字 + 車門"),
    ("10車門處", "10 車門處",  "車門後接其他字"),
    ("25/26 車", "25/26 車",   "已正規化（不變）"),
    ("25/26車",  "25/26 車",   "X/Y + 車（補空格）"),
    ("5/6車",    "05/06 車",   "X/Y 補零"),
    ("兩五兩六車", "25/26 車", "中文數字 → 拆對"),
    ("一零車",   "10 車",      "中文數字單節"),
    ("腰洞車",   "10 車",      "軍事數字"),
    ("腰洞車門", "10 車門",    "軍事數字 + 車門"),
    ("G07二月台2526車門", "G07二月台25/26 車門", "站碼旁的車號"),
    ("二月台05/06車", "二月台05/06 車", "月台後接車號"),
    ("車組兩勾三棟", "車組兩勾三棟", "車組 ID 不動"),
    ("車站", "車站", "車站不動"),
    ("車輛", "車輛", "車輛不動"),
    ("第一節車廂", "第一節車廂", "車廂不動"),
    ("2526動車", "25/26 動車", "4 位數字 + 動車"),
    ("兩五兩六動車門", "25/26 動車門", "中文 + 動車門"),
    ("拐六車", "76 車", "軍事拐(7) + 6"),
    ("勾洞車", "90 車", "軍事勾(9) + 洞(0)"),
    # 不該誤動的案例
    ("G07", "G07", "純站碼"),
    ("一月台", "一月台", "月台序號"),
    ("二月台", "二月台", "月台序號"),
    # 已是正確格式
    ("05/06 車", "05/06 車", "完全正確輸入"),
]


def run_tests():
    print(f"🧪 執行 {len(TEST_CASES)} 個測試案例")
    print("=" * 70)
    passed = 0
    failed = []
    for i, (inp, expected, desc) in enumerate(TEST_CASES, 1):
        actual, changes = normalize_car_numbers(inp)
        ok = actual == expected
        mark = "✅" if ok else "❌"
        print(f"{mark} #{i:2} [{desc}]")
        print(f"     in:       {inp!r}")
        if not ok:
            print(f"     expected: {expected!r}")
            print(f"     actual:   {actual!r}")
            if changes:
                print(f"     changes:  {changes}")
            failed.append((i, desc, inp, expected, actual))
        else:
            passed += 1
    print()
    print("=" * 70)
    print(f"結果: {passed}/{len(TEST_CASES)} 通過")
    if failed:
        print(f"\n❌ 失敗 {len(failed)} 個:")
        for i, desc, inp, exp, act in failed:
            print(f"  #{i} {desc}: {inp!r} → 期望 {exp!r} 但得 {act!r}")
        return 1
    return 0


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser(description="車廂編號正規化")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--test", action="store_true", help="執行內建測試")
    grp.add_argument("--text", help="正規化單一字串")
    grp.add_argument("--file", help="正規化檔案內容")
    args = p.parse_args()

    if args.test:
        sys.exit(run_tests())

    if args.text:
        text = args.text
    else:
        path = Path(args.file)
        if not path.is_absolute():
            path = Path.cwd() / path
        text = path.read_text(encoding="utf-8")

    result, changes = normalize_car_numbers(text)
    print("─── 原文 ───")
    print(text)
    print()
    print("─── 修正後 ───")
    print(result)
    print()
    print(f"─── 修正紀錄（{len(changes)} 處）───")
    for c in changes:
        print(f"  {c['from']!r} → {c['to']!r}  [{c['rule']}]")


if __name__ == "__main__":
    main()
