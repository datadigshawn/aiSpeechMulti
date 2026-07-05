"""regression_guard（A4）單元測試：車廂號抽取 + 三指標計算。"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.regression_guard import (  # noqa: E402
    aggregate_guard,
    car_number_tokens,
    guard_metrics,
)


class TestCarNumberTokens:
    def test_format_normalization(self):
        # 斜線 / 空白 / 軍事數字視為同一 token
        assert (
            car_number_tokens("07/08車")
            == car_number_tokens("0708 車")
            == car_number_tokens("洞拐洞八車")
            == Counter({("0708", "車"): 1})
        )

    def test_prefix_form(self):
        assert car_number_tokens("車組21/22") == Counter({("2122", "車組"): 1})

    def test_no_false_positive(self):
        assert car_number_tokens("G04車站到了") == Counter()
        assert car_number_tokens("車組") == Counter()
        assert car_number_tokens("") == Counter()

    def test_multiple_occurrences(self):
        toks = car_number_tokens("09/10車回報，09/10車已切換")
        assert toks[("0910", "車")] == 2


class TestGuardMetrics:
    def test_keyword_miss_detected(self):
        # 機廠→機場：CER 幾乎看不見，guard 要抓到
        g = guard_metrics("北屯機廠停準", "北屯機場停準")
        assert g["kw"]["ref"] > g["kw"]["hit"]

    def test_car_hit_and_hallucination(self):
        g = guard_metrics("人員已下23/24車", "人員已下2324 車，另見05/06車")
        assert g["car"] == {"ref": 1, "hit": 1, "halluc": 1}

    def test_aggregate(self):
        g1 = guard_metrics("北屯機廠停準", "北屯機廠停準")
        g2 = guard_metrics("北屯機廠停準", "北屯機場停準")
        agg = aggregate_guard([g1, g2])
        assert agg["kw"]["ref"] == g1["kw"]["ref"] * 2
        assert 0 < agg["kw"]["recall"] < 1
        assert agg["car"]["recall"] is None  # ref=0 → n/a
