"""Tests for scripts/number_normalizer.py — 數字編號正規化。"""

from __future__ import annotations

from scripts.number_normalizer import (
    normalize_numbers,
    normalize_station_code,
    normalize_platform,
)


class TestStationCode:
    """G7 → G07，補零站碼。"""

    def test_pad_single_digit(self):
        text, changes = normalize_station_code("G7 站長")
        assert "G07" in text
        assert len(changes) >= 1

    def test_keep_already_padded(self):
        text, changes = normalize_station_code("G07 站長")
        assert "G07" in text
        # 不應改 G07
        assert "G007" not in text

    def test_red_line_R(self):
        text, changes = normalize_station_code("R1 月台")
        assert "R01" in text


class TestPlatform:
    """二月台 → 2 月台 / 二號月台 → 2 號月台。"""

    def test_chinese_to_arabic(self):
        text, changes = normalize_platform("請到二月台")
        assert "2 月台" in text or "2月台" in text


class TestNormalizeNumbersIntegration:
    """normalize_numbers 是統合 entry，全部 enable 跑一次。"""

    def test_full_pipeline_returns_changes(self):
        text, changes = normalize_numbers(
            "G7 站長呼叫，請到二月台",
            enable_time=True,
            enable_station_code=True,
            enable_spacing=True,
            enable_duration=True,
        )
        # 應有至少一筆 change（站碼或月台）
        assert isinstance(text, str)
        assert isinstance(changes, list)
        # G7 應變 G07
        assert "G07" in text

    def test_empty_input_returns_empty(self):
        text, changes = normalize_numbers("")
        assert text == ""
        assert changes == []

    def test_no_changes_when_all_disabled(self):
        text, changes = normalize_numbers(
            "G7 站長",
            enable_time=False,
            enable_station_code=False,
            enable_spacing=False,
            enable_duration=False,
        )
        assert text == "G7 站長"
        assert changes == []
