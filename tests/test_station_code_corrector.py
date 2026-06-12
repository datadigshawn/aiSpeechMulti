"""Tests for scripts/station_code_corrector.py — 站碼閉集約束修正。

背景：2026-06-12 北屯根因調查任務 4。站碼 G0–G17 為封閉集合，
站碼+站名成對出現時可互為錨點。離線評測（240 檔黃金語料）：
95 處修正、58 檔改善、0 檔變差、整體 CER −0.30pp。
"""

from __future__ import annotations

from scripts.station_code_corrector import correct_station_codes


class TestRuleNameAnchor:
    """Rule N：站名完全命中 → 修站碼。"""

    def test_fixes_code_by_name(self):
        # 實測最高頻錯誤（×28）：高鐵=G17
        text, changes = correct_station_codes("OCC通告G07高鐵站")
        assert text == "OCC通告G17高鐵站"
        assert changes[0]["rule"] == "station_name_anchor"

    def test_preserves_gap_and_padding_width(self):
        text, _ = correct_station_codes("G01 九德站")
        assert text == "G15 九德站"
        text, _ = correct_station_codes("G00市府站")
        assert text == "G09市府站"  # 原寬度 2 → 補零成 09

    def test_three_digit_code_collapses_to_two(self):
        # 合法站碼最多兩位，不還原成不存在的三位形式
        text, _ = correct_station_codes("G107高鐵站")
        assert text == "G17高鐵站"

    def test_subcode_station(self):
        text, _ = correct_station_codes("G11森林站")
        assert text == "G10a森林站"


class TestRuleCodeAnchor:
    """Rule F：站碼合法、站名同長僅差 1 字 → 修站名。"""

    def test_fixes_name_by_code(self):
        # 實測 ×10：市維 → 四維
        text, changes = correct_station_codes("請G05市維站回報")
        assert text == "請G05四維站回報"
        assert changes[0]["rule"] == "station_code_anchor"

    def test_name_two_chars_off_not_touched(self):
        # 差 2 字（車車 vs 舊社）→ 信心不足，不修
        text, changes = correct_station_codes("G03車車站")
        assert text == "G03車車站"
        assert changes == []


class TestSafetyBoundaries:
    """安全邊界：寧可不修，不可修錯。"""

    def test_zero_padding_variants_untouched(self):
        # GT 慣例 G9/G09、G0/G00 混用，補零差異不是錯誤
        for s in ("G09市府站", "G9市府站", "G00北屯站", "G0北屯站"):
            text, changes = correct_station_codes(s)
            assert text == s
            assert changes == []

    def test_ambiguous_hamming1_station_pair_skipped(self):
        # G11北屯站：南屯誤聽 or 站碼誤聽，無法分辨 → 不修
        text, changes = correct_station_codes("G11北屯站")
        assert text == "G11北屯站"
        assert changes == []

    def test_both_wrong_skipped(self):
        # 站碼站名皆錯（G94 無效、五站非站名）→ 留給 LLM 層
        text, changes = correct_station_codes("G94五站")
        assert text == "G94五站"
        assert changes == []

    def test_code_without_name_untouched(self):
        # 純站碼無站名錨點，即使無效也不猜
        text, changes = correct_station_codes("請G94回報")
        assert text == "請G94回報"
        assert changes == []

    def test_empty_text(self):
        assert correct_station_codes("") == ("", [])

    def test_range_expression(self):
        # 區間句型：各站碼獨立判斷，正確的不動
        text, _ = correct_station_codes("G0北屯站至G9市府站")
        assert text == "G0北屯站至G9市府站"
