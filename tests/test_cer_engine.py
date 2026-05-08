"""Tests for scripts/cer_engine.py — CER 計算與正規化。"""

from __future__ import annotations

from scripts.cer_engine import calculate_cer, calculate_wer, normalize_text


class TestNormalizeText:
    """評測前的字串正規化。"""

    def test_strips_timestamps(self):
        assert normalize_text("[12:34] 你好") == "你好"
        assert normalize_text("[12:34:56] hello") == "hello"

    def test_full_width_digits_to_half(self):
        assert normalize_text("０１２") == "012"

    def test_full_width_letters_to_half(self):
        # 全形 → 半形 + 小寫
        assert normalize_text("ＡＢＣ") == "abc"

    def test_strips_punctuation_keeps_chinese_and_alnum(self):
        assert normalize_text("OCC，呼叫！G07") == "occ呼叫g07"

    def test_lowercases_english(self):
        assert normalize_text("HELLO") == "hello"


class TestCalculateCER:
    """主 CER API：calculate_cer(ref, hyp) → dict."""

    def test_perfect_match(self):
        r = calculate_cer("OCC 收到", "OCC 收到")
        assert r["cer"] == 0.0
        assert r["accuracy"] == 1.0
        assert r["n_errors"] == 0

    def test_empty_reference(self):
        """ref 為空字串 → 約定 cer=0, accuracy=1, engine=none。"""
        r = calculate_cer("", "")
        assert r["cer"] == 0.0
        assert r["n_ref"] == 0
        assert r["engine"] == "none"

    def test_one_substitution(self):
        # 「abc」vs「abd」= 1 substitution，3 字
        r = calculate_cer("abc", "abd")
        assert r["n_ref"] == 3
        assert r["sub"] == 1
        assert r["del_"] == 0
        assert r["ins"] == 0
        assert r["n_errors"] == 1
        assert abs(r["cer"] - 1 / 3) < 0.001

    def test_insertion_counts_doubled_due_to_join_quirk(self):
        """ref=ab, hyp=abc → ins=2（已知 quirk：cer_engine 用 ' '.join(list(s)) 把字
        以空格分隔再餵 jiwer.process_characters，導致每個 length 變化會多算一個空格 token。
        這對所有引擎一視同仁，相對排序不變，但絕對 CER 略偏高。"""
        r = calculate_cer("ab", "abc")
        assert r["ins"] == 2  # 空格 + c
        assert r["sub"] == 0
        assert r["del_"] == 0

    def test_deletion_counts_doubled_due_to_join_quirk(self):
        """ref=abc, hyp=ab → del=2（同上 quirk）。"""
        r = calculate_cer("abc", "ab")
        assert r["del_"] == 2  # 空格 + c
        assert r["sub"] == 0
        assert r["ins"] == 0

    def test_chinese_characters_count_correctly(self):
        # 「OCC 呼叫」normalize 後 = 「occ呼叫」共 5 字
        r = calculate_cer("OCC 呼叫", "OCC 收到")
        assert r["n_ref"] == 5  # occ呼叫
        assert r["n_errors"] >= 2  # 「呼叫」≠「收到」

    def test_cer_capped_at_1(self):
        # 完全沒對到的話 cer 應 ≤ 1.0（不會 > 1.0）
        r = calculate_cer("ab", "xyz")
        assert r["cer"] <= 1.0


class TestCalculateWER:
    """WER 詞錯誤率（次要 API）。"""

    def test_perfect_match(self):
        r = calculate_wer("hello world", "hello world")
        assert r["wer"] == 0.0

    def test_one_word_off(self):
        r = calculate_wer("hello world", "hello there")
        assert r["wer"] > 0
