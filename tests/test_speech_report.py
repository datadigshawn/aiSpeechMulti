"""utils.speech_report 純函式單元測試。LLM 呼叫不在此測試範圍。"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from utils.speech_report import (
    parse_audio_time_range,
    format_report_file,
    estimate_gemini_cost_twd,
    safe_filename_fragment,
)


class TestParseAudioTimeRange:
    def test_empty_returns_none_label(self):
        assert parse_audio_time_range({}) == "無"

    def test_single_file(self):
        dt = datetime(2025, 3, 14, 10, 15, 30)
        out = parse_audio_time_range({"foo": dt})
        assert out == "2025-03-14 10:15:30"

    def test_multi_file_range(self):
        out = parse_audio_time_range({
            "a": datetime(2025, 3, 14, 10, 15, 30),
            "b": datetime(2025, 3, 14, 11, 45, 0),
            "c": datetime(2025, 3, 14, 9,  0,  5),
        })
        assert out == "2025-03-14 09:00:05 ~ 11:45:00"


class TestFormatReportFile:
    def test_structure(self):
        md = "## 一句話總結\n核心訊息\n\n## 核心觀點\n- 點 1"
        out = format_report_file(
            md, sources=["abc.wav"], audio_time_range="無",
            generated_at=datetime(2026, 5, 29, 12, 34, 56),
        )
        assert "【語音辨識報告】" in out
        assert "檔名：abc.wav" in out
        assert "產出時間：2026-05-29 12:34:56" in out
        assert "語音時間：無" in out
        assert "【報告內容】" in out
        assert "核心訊息" in out

    def test_multi_source(self):
        out = format_report_file(
            "x", sources=["a.wav", "b.wav"], audio_time_range="無",
            generated_at=datetime(2026, 1, 1, 0, 0, 0),
        )
        assert "檔名：a.wav、b.wav" in out

    def test_empty_sources_fallback(self):
        out = format_report_file("x", sources=[], audio_time_range="無")
        assert "檔名：（未知）" in out


class TestEstimateGeminiCostTwd:
    def test_real_pricing_json_flash(self):
        # 應該讀到專案的 pricing.json，不會 fallback
        out = estimate_gemini_cost_twd(1000, 500, model="gemini-2.5-flash")
        assert out["fallback_pricing"] is False
        assert out["usd"] > 0
        assert out["twd"] > 0
        assert out["model"] == "gemini-2.5-flash"

    def test_real_pricing_json_pro(self):
        out = estimate_gemini_cost_twd(1000, 500, model="gemini-2.5-pro")
        assert out["fallback_pricing"] is False
        # Pro 比 Flash 貴
        flash = estimate_gemini_cost_twd(1000, 500, model="gemini-2.5-flash")
        assert out["usd"] > flash["usd"]

    def test_zero_tokens(self):
        out = estimate_gemini_cost_twd(0, 0)
        assert out["usd"] == 0
        assert out["twd"] == 0

    def test_unknown_model_falls_back(self, tmp_path):
        # 用沒有該模型的空 pricing.json，應 fallback 為內建估價
        p = tmp_path / "empty.json"
        p.write_text(json.dumps({"usd_to_twd": 31.0, "engines": {}}))
        out = estimate_gemini_cost_twd(1000, 500, model="nonexistent", pricing_path=p)
        assert out["fallback_pricing"] is True

    def test_large_input_calculation(self, tmp_path):
        # 100K input tokens, 5K output tokens, flash 價格
        p = tmp_path / "pricing.json"
        p.write_text(json.dumps({
            "usd_to_twd": 31.0,
            "engines": {
                "gemini-2.5-flash": {"usd_per_1m_in": 0.30, "usd_per_1m_out": 2.50}
            },
        }))
        out = estimate_gemini_cost_twd(100_000, 5_000, model="gemini-2.5-flash", pricing_path=p)
        # 100K × $0.30/1M = $0.03  +  5K × $2.50/1M = $0.0125  =  $0.0425
        assert out["usd"] == pytest.approx(0.0425, abs=1e-4)
        # NT$0.0425 × 31 ≈ NT$1.32
        assert out["twd"] == pytest.approx(1.32, abs=0.01)


class TestSafeFilenameFragment:
    def test_basic(self):
        assert safe_filename_fragment("Hello World") == "Hello_World"

    def test_unsafe_chars_stripped(self):
        out = safe_filename_fragment('a/b\\c:d*e?f"g<h>i|j')
        for ch in "/\\:*?\"<>|":
            assert ch not in out

    def test_long_truncated(self):
        out = safe_filename_fragment("A" * 200, max_len=60)
        assert len(out) <= 60

    def test_empty_fallback(self):
        assert safe_filename_fragment("") == "report"
        assert safe_filename_fragment("///") == "report"

    def test_chinese_preserved(self):
        out = safe_filename_fragment("捷運辨識報告")
        assert "捷運辨識報告" in out
