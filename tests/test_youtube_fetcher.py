"""Tests for utils.youtube_fetcher pure functions."""
import json

import pytest

from utils.youtube_fetcher import sanitize_title, estimate_cost_twd


class TestSanitizeTitle:
    def test_basic(self):
        assert sanitize_title("Hello World") == "Hello_World"

    def test_strip_unsafe_chars(self):
        # \\ / : * ? " < > | 全部要剝
        assert sanitize_title('foo/bar:baz*qux?<>"|.md').endswith(".md")  # 只剝禁字
        assert "/" not in sanitize_title("a/b")
        assert ":" not in sanitize_title("a:b")
        assert "*" not in sanitize_title("a*b")

    def test_chinese_preserved(self):
        out = sanitize_title("捷運通訊辨識 OCC 即時")
        assert "捷運通訊辨識" in out
        assert "OCC" in out

    def test_empty_fallback(self):
        assert sanitize_title("") == "untitled"
        assert sanitize_title("///") == "untitled"  # 全是禁字 → fallback

    def test_long_title_truncated(self):
        long_title = "A" * 200
        out = sanitize_title(long_title, max_len=80)
        assert len(out) <= 80

    def test_newlines_stripped(self):
        assert "\n" not in sanitize_title("a\nb\rc\td")


class TestEstimateCostTwd:
    def test_google_chirp_3_60s(self, tmp_path):
        # 60 秒 × $0.000400/sec = $0.024 → NT$0.744
        pricing = {
            "usd_to_twd": 31.0,
            "engines": {"google_stt_chirp_3": {"usd_per_unit": 0.0004, "unit": "audio_seconds", "type": "stt"}},
        }
        p = tmp_path / "pricing.json"
        p.write_text(json.dumps(pricing))
        out = estimate_cost_twd(60, "google_stt_chirp_3", pricing_path=p)
        # impl rounds twd to 2 decimals → 0.744 → 0.74
        assert out["usd"] == pytest.approx(0.024, abs=1e-4)
        assert out["twd"] == pytest.approx(0.74, abs=1e-2)
        assert out["duration_min"] == 1.0

    def test_uses_real_pricing_json(self):
        # 預設 pricing.json 存在且 google_stt_chirp_3 已定義
        out = estimate_cost_twd(60, "google_stt_chirp_3")
        assert out["usd"] > 0
        assert out["twd"] > 0
        assert out["engine"] == "google_stt_chirp_3"

    def test_unknown_engine_raises(self, tmp_path):
        pricing = {"usd_to_twd": 31.0, "engines": {}}
        p = tmp_path / "pricing.json"
        p.write_text(json.dumps(pricing))
        with pytest.raises(KeyError):
            estimate_cost_twd(60, "nonexistent_engine", pricing_path=p)
