"""Tests for utils/pricing.py — pricing.json 載入與成本計算。"""

from __future__ import annotations

import json
import pytest

from utils.pricing import (
    load_pricing,
    calc_cost,
    alert_level,
    PricingError,
)


class TestLoadPricing:
    def test_loads_default_pricing_json(self):
        p = load_pricing()
        assert "usd_to_twd" in p
        assert p["usd_to_twd"] == 31.0
        assert "engines" in p
        assert "scribe_rt" in p["engines"]
        assert "google_stt_chirp_3" in p["engines"]

    def test_load_raises_on_missing_usd_to_twd(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text('{"engines": {}}')  # 缺 usd_to_twd
        with pytest.raises(PricingError, match="missing required key 'usd_to_twd'"):
            load_pricing(bad)

    def test_load_raises_on_missing_engines(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text('{"usd_to_twd": 31.0}')  # 缺 engines
        with pytest.raises(PricingError, match="missing required key 'engines'"):
            load_pricing(bad)

    def test_load_raises_on_engine_missing_unit(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text('{"usd_to_twd": 31.0, "engines": {"foo": {"usd_per_unit": 0.001}}}')
        with pytest.raises(PricingError, match="engine 'foo' config missing required key 'unit'"):
            load_pricing(bad)


class TestCalcCost:
    @pytest.fixture
    def sample_pricing(self):
        return {
            "usd_to_twd": 31.0,
            "engines": {
                "scribe_rt": {"type": "stt", "unit": "audio_seconds", "usd_per_unit": 0.000111},
                "google_stt_chirp_3": {"type": "stt", "unit": "audio_seconds", "usd_per_unit": 0.000400},
            },
        }

    def test_scribe_60_seconds(self, sample_pricing):
        usd, twd = calc_cost("scribe_rt", {"audio_seconds": 60.0}, sample_pricing)
        assert abs(usd - 60 * 0.000111) < 1e-9
        assert abs(twd - usd * 31.0) < 1e-9

    def test_google_100_seconds(self, sample_pricing):
        usd, twd = calc_cost("google_stt_chirp_3", {"audio_seconds": 100.0}, sample_pricing)
        assert abs(usd - 100 * 0.000400) < 1e-9
        assert abs(twd - 0.04 * 31.0) < 1e-9

    def test_unknown_engine_raises(self, sample_pricing):
        with pytest.raises(PricingError, match="not in pricing"):
            calc_cost("nonexistent", {"audio_seconds": 10}, sample_pricing)

    def test_missing_unit_raises(self, sample_pricing):
        with pytest.raises(PricingError, match="missing required key"):
            calc_cost("scribe_rt", {"input_tokens": 100}, sample_pricing)


class TestAlertLevel:
    @pytest.fixture
    def alerts_pricing(self):
        return {
            "alerts": {
                "daily_warning_pct": 80,
                "daily_critical_pct": 100,
                "daily_budget_twd": 100,
            }
        }

    def test_ok_under_warning(self, alerts_pricing):
        assert alert_level(50.0, alerts_pricing) == "ok"
        assert alert_level(79.99, alerts_pricing) == "ok"

    def test_warning_at_80_pct(self, alerts_pricing):
        assert alert_level(80.0, alerts_pricing) == "warning"
        assert alert_level(99.99, alerts_pricing) == "warning"

    def test_critical_at_100_pct(self, alerts_pricing):
        assert alert_level(100.0, alerts_pricing) == "critical"
        assert alert_level(150.0, alerts_pricing) == "critical"

    def test_zero_budget_always_ok(self):
        """daily_budget_twd <= 0 邊界：alarm 全程禁用。"""
        p = {"alerts": {"daily_budget_twd": 0, "daily_warning_pct": 80, "daily_critical_pct": 100}}
        assert alert_level(99999.0, p) == "ok"
