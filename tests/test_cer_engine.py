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

    def test_strips_speaker_labels(self):
        # 行首講者標記不應洩漏成字元（否則被當漏字誤計）
        assert normalize_text("B: 收到") == "收到"
        assert normalize_text("H: G07站回報") == "g07站回報"
        # 多行多講者
        assert normalize_text("H: 呼叫OCC\nB: 聽到請回答") == "呼叫occ聽到請回答"

    def test_strips_bracket_annotations(self):
        assert normalize_text("占線中[noise]請稍候") == "占線中請稍候"


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

    def test_insertion_counts_exact(self):
        """ref=ab, hyp=abc → ins=1（直接逐字元對齊，不再有空格 join 加倍）。"""
        r = calculate_cer("ab", "abc")
        assert r["ins"] == 1
        assert r["sub"] == 0
        assert r["del_"] == 0

    def test_deletion_counts_exact(self):
        """ref=abc, hyp=ab → del=1（直接逐字元對齊，不再有空格 join 加倍）。"""
        r = calculate_cer("abc", "ab")
        assert r["del_"] == 1
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
