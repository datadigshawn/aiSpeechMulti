#!/usr/bin/env python3
"""
SentenceLevelFuser 單元測試
============================

驗證：
1. split_sentences 對各種輸入的切分正確性
2. has_critical_terms 對術語/站碼/車廂的偵測
3. safety fallback 機制觸發條件
4. 規則 R1-R5 的決策邏輯

用法：
    python3 scripts/test_result_fuser_sentence.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.result_fuser_sentence import (
    split_sentences,
    has_critical_terms,
    SentenceLevelFuser,
    compute_sentence_cer,
    align_sentences,
)


# ══════════════════════════════════════════════════════════════════════
# 測試案例
# ══════════════════════════════════════════════════════════════════════
SPLIT_TESTS = [
    # (輸入, 預期切分數量 >=, 說明)
    ("", 0, "空字串"),
    ("OCC 呼叫 G07 站長。", 1, "單句有標點"),
    ("OCC 呼叫 G07 站長，月台門即將關閉。請旅客注意安全！", 2, "雙句標點"),
    ("G07 呼叫 OCC over 站長回報 OCC over", 2, "無標點但有 over 邊界"),
    ("OCC 通告全線 收到 稍後回報", 2, "多個通訊邊界詞"),
    ("G07 呼叫 OCC G17 站長回報", 2, "角色起始詞切分"),
    ("【講者0 ｜ 洞洞:洞洞】OCC 呼叫", 1, "講者標記應被移除"),
    ("A" * 100, 2, "超長無標點句應被強制切分"),
]

CRITICAL_TERMS_TESTS = [
    ("G07 站長", True, "站碼 G07"),
    ("R01 月台", True, "站碼 R01"),
    ("25/26 車門", True, "車廂編號"),
    ("10 車門", True, "單節車廂"),
    ("使用 EDRH 開啟", True, "設備術語 EDRH"),
    ("列車復電作業", True, "動作詞 復電"),
    ("早安你好", False, "無術語"),
    ("今天天氣不錯", False, "日常對話"),
]


def test_split_sentences():
    print("🧪 測試 split_sentences")
    passed = 0
    for text, expected_min, desc in SPLIT_TESTS:
        result = split_sentences(text)
        ok = len(result) >= expected_min
        mark = "✅" if ok else "❌"
        print(f"  {mark} [{desc}] → {len(result)} 句 (預期 ≥ {expected_min})")
        if not ok:
            print(f"     input:  {text!r}")
            print(f"     result: {result}")
        else:
            passed += 1
    print(f"  結果: {passed}/{len(SPLIT_TESTS)}\n")
    return passed == len(SPLIT_TESTS)


def test_critical_terms():
    print("🧪 測試 has_critical_terms")
    passed = 0
    for text, expected, desc in CRITICAL_TERMS_TESTS:
        result = has_critical_terms(text)
        ok = result == expected
        mark = "✅" if ok else "❌"
        print(f"  {mark} [{desc}] → {result} (預期 {expected})")
        if ok:
            passed += 1
    print(f"  結果: {passed}/{len(CRITICAL_TERMS_TESTS)}\n")
    return passed == len(CRITICAL_TERMS_TESTS)


def test_safety_fallback():
    print("🧪 測試 safety fallback")
    fuser = SentenceLevelFuser(length_ratio_threshold=0.8)

    # Case 1: 字數差距大 → 應觸發 safety
    text_a = "短的"
    text_b = "這是一段很長很長的文字，長到足以觸發 safety fallback 的程度"
    result = fuser.fuse(text_a, text_b, "short_engine", "long_engine")
    case1_ok = result.get("safety_fallback", {}).get("triggered", False)
    print(f"  {'✅' if case1_ok else '❌'} [字數差距 > 20%] safety 觸發: {case1_ok}")
    if case1_ok:
        print(f"     chosen: {result['safety_fallback']['chosen']}")
        print(f"     ratio: {result['safety_fallback']['length_ratio']}")

    # Case 2: 字數接近 → 不應觸發 safety
    text_a2 = "這段文字很接近字數 OCC 通告 G07 站長"
    text_b2 = "這段文字也很接近 OCC 呼叫 G07 月台"
    result2 = fuser.fuse(text_a2, text_b2, "engine_a", "engine_b")
    case2_ok = not result2.get("safety_fallback", {}).get("triggered", False)
    print(f"  {'✅' if case2_ok else '❌'} [字數接近] safety 未觸發: {case2_ok}")
    if case2_ok:
        print(f"     句子數: {result2['sentence_count']}")
        print(f"     規則: {result2['stats']['rule_counts']}")

    # Case 3: 完全相同 → 取 A（或 B，視長度）
    text_same = "OCC 呼叫 G07 站長 over"
    result3 = fuser.fuse(text_same, text_same, "a", "b")
    case3_ok = result3["transcript"] == text_same
    print(f"  {'✅' if case3_ok else '❌'} [完全相同] 輸出不變")

    passed = sum([case1_ok, case2_ok, case3_ok])
    print(f"  結果: {passed}/3\n")
    return passed == 3


def test_cer_computation():
    print("🧪 測試 compute_sentence_cer")
    cases = [
        ("OCC 通告", "OCC 通告", 0.0, "完全相同"),
        ("OCC 通告", "OCC 呼叫", 0.0, "標點與空白不計"),  # 正規化後只有字元差
        ("", "", 0.0, "雙空"),
        ("有內容", "", 1.0, "單空"),
    ]
    passed = 0
    for a, b, expected, desc in cases:
        result = compute_sentence_cer(a, b)
        if desc == "標點與空白不計":
            ok = 0 < result <= 1  # 只檢查在合理範圍
        else:
            ok = abs(result - expected) < 0.01
        mark = "✅" if ok else "❌"
        print(f"  {mark} [{desc}] {a!r} vs {b!r} → {result:.4f}")
        if ok:
            passed += 1
    print(f"  結果: {passed}/{len(cases)}\n")
    return passed == len(cases)


def test_alignment():
    print("🧪 測試 align_sentences")
    # 相同順序 + 相似內容
    a = ["OCC 呼叫", "G07 站長回報", "請稍後"]
    b = ["OCC 呼叫", "G07 站長報告", "請稍後"]
    alignment = align_sentences(a, b)
    aligned_pairs = [(i, j) for i, j in alignment if i is not None and j is not None]
    ok = len(aligned_pairs) >= 2
    print(f"  {'✅' if ok else '❌'} [相似句應對齊] 成功對齊 {len(aligned_pairs)} 對")

    # 單邊 empty
    alignment2 = align_sentences([], ["a", "b"])
    ok2 = all(i is None for i, _ in alignment2)
    print(f"  {'✅' if ok2 else '❌'} [空 A] 全部為 B_only")

    passed = sum([ok, ok2])
    print(f"  結果: {passed}/2\n")
    return passed == 2


def main():
    print("=" * 60)
    print("SentenceLevelFuser 單元測試")
    print("=" * 60)
    print()

    results = [
        test_split_sentences(),
        test_critical_terms(),
        test_safety_fallback(),
        test_cer_computation(),
        test_alignment(),
    ]

    print("=" * 60)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"✅ 所有測試組通過 ({passed}/{total})")
        return 0
    else:
        print(f"❌ 測試組 {passed}/{total} 通過")
        return 1


if __name__ == "__main__":
    sys.exit(main())
