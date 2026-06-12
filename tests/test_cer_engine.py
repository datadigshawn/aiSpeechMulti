"""Tests for scripts/cer_engine.py — CER 計算與正規化。"""

from __future__ import annotations

from scripts.cer_engine import (
    _levenshtein_edits,
    calculate_cer,
    calculate_wer,
    normalize_text,
)


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
        # 方括號標註應被剝除（與是否裝 opencc 無關 → 比對「有/無標註」等價）
        assert normalize_text("占線中[noise]請稍候") == normalize_text("占線中請稍候")

    def test_simplified_to_traditional(self):
        # 簡繁統一（與 batch_eval 對齊）：模型吐簡體不應被當錯誤
        from scripts.cer_engine import _CC
        if _CC is None:
            import pytest
            pytest.skip("opencc 未安裝")
        assert normalize_text("确认换车") == normalize_text("確認換車")


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


class TestLevenshteinFallback:
    """無 jiwer 時的純 Python fallback 必須是真最小編輯距離。

    回歸背景（2026-06-12 北屯根因調查）：舊版 fallback 用
    difflib.SequenceMatcher 近似，對吵雜 ASR 文本對齊崩潰，
    把實際 26.58% CER 的檔案算成 100%、北屯批次整體灌水 +13pp。
    """

    def test_basic_edit_counts(self):
        assert _levenshtein_edits("abc", "axc") == (1, 0, 0)
        assert _levenshtein_edits("abc", "ac") == (0, 1, 0)
        assert _levenshtein_edits("abc", "abxc") == (0, 0, 1)
        assert _levenshtein_edits("", "ab") == (0, 0, 2)
        assert _levenshtein_edits("ab", "") == (0, 2, 0)

    def test_noisy_asr_pair_not_inflated(self):
        """260603_正線_074411 實例：difflib 舊版給 100% CER，真值 21/79。"""
        ref = (
            "occ通告全線occ通告全線occ完成g0北屯站至g17高鐵尾軌上下行三軌"
            "復電作業重複通告occ完成g0北屯站至g17高鐵尾軌上下行三軌復電作業通告完畢out"
        )
        hyp = (
            "occ到收消occ到收occ完成g00北通站至g17高鐵回軌上下行三軌"
            "復電作業同步通告occ完成g00北屯站至g17高鐵軌上下行三角復電作業通告表"
        )
        sub, del_, ins = _levenshtein_edits(ref, hyp)
        assert (sub, del_, ins) == (11, 8, 2)
        # 經 calculate_cer（不論 jiwer 或 fallback）總錯誤數應為最小編輯距離
        r = calculate_cer(ref, hyp)
        assert r["n_errors"] == 21
        assert abs(r["cer"] - 21 / 79) < 0.001

    def test_works_on_token_lists(self):
        """WER fallback 傳入 token list，DP 必須支援序列而非僅字串。"""
        assert _levenshtein_edits(["占", "用"], ["占", "領"]) == (1, 0, 0)


class TestCalculateWER:
    """WER 詞錯誤率（次要 API）。"""

    def test_perfect_match(self):
        r = calculate_wer("hello world", "hello world")
        assert r["wer"] == 0.0

    def test_one_word_off(self):
        r = calculate_wer("hello world", "hello there")
        assert r["wer"] > 0
