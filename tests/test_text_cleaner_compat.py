"""Tests for utils/text_cleaner.fix_radio_jargon — 收斂為 canonical 相容 wrapper。

2026-06-16 第二波：fix_radio_jargon 不再跑自己那套與 post_process 重複的
deterministic 規則，改為轉呼叫 canonical 核心 post_process_realtime()。
本測試鎖定該相容契約：
- fix_radio_jargon(text) 等價於 post_process_realtime(text)[0]。
- 仍回傳 str；空字串安全。
- 站碼 / 車號等 deterministic 修正確實生效。
"""

from __future__ import annotations

import pytest

from utils.text_cleaner import fix_radio_jargon
from scripts.post_process_runtime import post_process_realtime


CASES = [
    "OCC通告G07高鐵站",
    "洞二零一車門",
    "正常一句話",
    "",
    "   ",
]


class TestFixRadioJargonCompat:
    @pytest.mark.parametrize("text", CASES)
    def test_equivalent_to_canonical_core(self, text):
        """與 canonical 核心輸出一致 —— 杜絕兩套規則漂移。"""
        assert fix_radio_jargon(text) == post_process_realtime(text)[0]

    @pytest.mark.parametrize("text", CASES)
    def test_returns_str(self, text):
        assert isinstance(fix_radio_jargon(text), str)

    def test_empty_safe(self):
        assert fix_radio_jargon("") == ""

    def test_station_code_corrected(self):
        out = fix_radio_jargon("OCC通告G07高鐵站")
        assert "G17" in out
        assert "G07" not in out
