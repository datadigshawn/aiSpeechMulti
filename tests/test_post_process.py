"""Tests for scripts/post_process.py — 後處理 pipeline 三階段。

涵蓋：
- normalize_car_numbers（車廂編號 4 pass：中文→阿拉伯、4位拆對、補零、加空格）
- apply_correction_dict（同音字/術語修正）
- post_process orchestrator（toggle 各階段、snapshots、回報結構）

不涵蓋（需 mock 外部 API，留 v2）：
- apply_llm_correction
- _check_perplexity_rollback（需 ngram LM 檔）
"""

from __future__ import annotations


from scripts.post_process import (
    normalize_car_numbers,
    apply_correction_dict,
    post_process,
)


# ─────────────────────────────────────────────────────────────────────────────
# normalize_car_numbers — 車廂編號正規化
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeCarNumbers:
    def test_empty_input(self):
        text, changes = normalize_car_numbers("")
        assert text == ""
        assert changes == []

    def test_chinese_digits_to_arabic_for_car(self):
        """洞二零一車門 → 0201 車門 → 02/01 車門"""
        text, changes = normalize_car_numbers("洞二零一車門")
        # 中文轉阿拉伯
        assert "0201" not in text  # 應該已被拆成 02/01
        assert "02/01" in text or "02 / 01" in text
        assert any(c["rule"] == "chn_to_arabic" for c in changes)
        assert any("split_4digit" in c["rule"] for c in changes)

    def test_four_digit_split(self):
        """1205 車 → 12/05 車"""
        text, changes = normalize_car_numbers("1205車")
        assert "12/05" in text
        # 不應再有 1205 連寫
        assert "1205" not in text

    def test_slash_pad_zero(self):
        """1/5 車 → 01/05 車"""
        text, changes = normalize_car_numbers("1/5車")
        assert "01/05" in text
        assert any(c["rule"] == "slash_normalize" for c in changes)

    def test_no_match_returns_original(self):
        """純文字無數字 → 原樣回傳，無 change。"""
        text, changes = normalize_car_numbers("OCC 收到")
        assert text == "OCC 收到"
        assert changes == []

    def test_keeps_non_car_numbers(self):
        """1205 後不接 車/車門/動車 應保持原樣（避免誤改其他數字）。"""
        text, changes = normalize_car_numbers("1205 號站長")
        # 沒接「車」族 → 不該變
        assert "1205" in text


# ─────────────────────────────────────────────────────────────────────────────
# apply_correction_dict — 同音字 / 術語修正
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyCorrectionDict:
    def test_empty_input(self):
        text, changes = apply_correction_dict("")
        assert text == ""
        assert changes == []

    def test_returns_tuple_of_text_and_changes(self):
        """API 形狀：永遠回傳 (str, list)。"""
        text, changes = apply_correction_dict("OCC 收到")
        assert isinstance(text, str)
        assert isinstance(changes, list)

    def test_no_match_returns_original_unchanged(self):
        """完全不在字典裡的句子 → text 不變、changes 空。"""
        text, changes = apply_correction_dict("XYZ 不在任何字典裡")
        assert text == "XYZ 不在任何字典裡"


# ─────────────────────────────────────────────────────────────────────────────
# post_process orchestrator — 各階段 toggle
# ─────────────────────────────────────────────────────────────────────────────

class TestPostProcessOrchestrator:
    def test_returns_tuple_of_text_and_report(self):
        """API 形狀：永遠回傳 (str, dict)。"""
        text, report = post_process("OCC 收到", enable_llm=False)
        assert isinstance(text, str)
        assert isinstance(report, dict)

    def test_report_contains_snapshots(self):
        """report 應有 snapshots 紀錄各階段中間狀態。"""
        text, report = post_process(
            "OCC 1205車", enable_car_norm=True, enable_dict=False, enable_llm=False
        )
        assert "snapshots" in report
        assert "raw" in report["snapshots"]
        assert report["snapshots"]["raw"] == "OCC 1205車"

    def test_all_disabled_keeps_text_unchanged(self):
        """全關 → 文字不變（除非 term_filter 主動改）。"""
        text, report = post_process(
            "OCC 收到",
            enable_car_norm=False,
            enable_dict=False,
            enable_llm=False,
            enable_term_filter=False,
            enable_number_norm=False,
            enable_contextual=False,
        )
        assert text == "OCC 收到"

    def test_car_norm_enabled_changes_text(self):
        """開 car_norm → 1205車 應變 12/05 車。"""
        text, report = post_process(
            "1205車", enable_car_norm=True, enable_dict=False, enable_llm=False,
            enable_term_filter=False, enable_number_norm=False, enable_contextual=False,
        )
        assert "12/05" in text

    def test_empty_input_returns_empty(self):
        text, report = post_process("", enable_llm=False)
        assert text == ""

    def test_llm_disabled_does_not_call_api(self):
        """enable_llm=False → 不應依賴 GEMINI_API_KEY，純離線 pipeline。"""
        # 即使無 API key，這應該也能跑通
        text, report = post_process(
            "OCC 1205車", enable_llm=False
        )
        # 沒爆炸 = 通過
        assert isinstance(text, str)
