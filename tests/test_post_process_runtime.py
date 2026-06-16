"""Tests for scripts/post_process_runtime.post_process_realtime — 即時路徑 wrapper。

涵蓋即時路徑安全契約：
- deterministic 規則（station code）確實生效。
- enable_llm 永遠 False，wrapper 不得觸發 LLM 階段。
- engine_hint 原樣傳遞給底層 post_process。
- 空字串 / 純空白原樣回傳且不進 pipeline。
- 已正確文字 idempotent，不被過度改寫。
"""

from __future__ import annotations

from unittest.mock import patch

from scripts.post_process_runtime import post_process_realtime


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic 規則生效（整合，不 mock）
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterministicCorrection:
    def test_station_code_corrected(self):
        """實測高頻錯誤 高鐵=G17：G07 應被站名錨定修正為 G17。

        斷言聚焦「修正有發生」而非完整輸出字串 —— 完整 pipeline
        另有空白正規化等 deterministic 階段，輸出可能含空格。
        """
        corrected, report = post_process_realtime("OCC通告G07高鐵站")
        assert "G17" in corrected
        assert "G07" not in corrected
        assert "高鐵站" in corrected
        assert isinstance(report, dict)

    def test_idempotent_on_processed_output(self):
        """二次處理結果穩定，不被反覆改寫。"""
        once, _ = post_process_realtime("OCC通告G07高鐵站")
        twice, _ = post_process_realtime(once)
        assert twice == once


# ─────────────────────────────────────────────────────────────────────────────
# 空輸入短路：不進 pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestEmptyInput:
    def test_empty_string(self):
        with patch("scripts.post_process_runtime.post_process") as mock_pp:
            corrected, report = post_process_realtime("")
            assert corrected == ""
            assert report == {}
            mock_pp.assert_not_called()

    def test_whitespace_only(self):
        with patch("scripts.post_process_runtime.post_process") as mock_pp:
            corrected, report = post_process_realtime("   \n\t ")
            assert corrected == "   \n\t "
            assert report == {}
            mock_pp.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 安全閘：enable_llm 永遠 False、engine_hint 傳遞
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyContract:
    def test_never_enables_llm(self):
        """即時路徑安全閘：wrapper 一律以 enable_llm=False 呼叫底層。"""
        with patch(
            "scripts.post_process_runtime.post_process",
            return_value=("out", {"ok": True}),
        ) as mock_pp:
            corrected, report = post_process_realtime("某段辨識文字")
            assert corrected == "out"
            assert report == {"ok": True}
            mock_pp.assert_called_once()
            _, kwargs = mock_pp.call_args
            assert kwargs.get("enable_llm") is False

    def test_engine_hint_passed_through(self):
        with patch(
            "scripts.post_process_runtime.post_process",
            return_value=("out", {}),
        ) as mock_pp:
            post_process_realtime("某段辨識文字", engine_hint="google_stream")
            _, kwargs = mock_pp.call_args
            assert kwargs.get("engine_hint") == "google_stream"
            assert kwargs.get("enable_llm") is False
