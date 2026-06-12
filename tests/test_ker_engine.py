"""Tests for scripts/ker_engine.py — 關鍵詞錯誤率（KER）。

背景：2026-06-12 北屯根因調查任務 5。CER 對語意關鍵錯誤不敏感
（機廠→機場僅 0.1pp CER 但事故地點全錯），KER 單獨追蹤關鍵詞召回。
"""

from __future__ import annotations

from scripts.ker_engine import calculate_ker, load_keywords


def _kw(*terms, level=2):
    """測試用關鍵詞清單（與 load_keywords 同結構）。"""
    from scripts.cer_engine import normalize_text
    return [
        {"term": t, "norm": normalize_text(t), "alert_level": level, "category": "test"}
        for t in terms
    ]


class TestCalculateKER:
    def test_full_recall(self):
        r = calculate_ker("機廠跟正線三軌都跳", "機廠跟正線三軌都跳", _kw("機廠", "三軌"))
        assert r["ker"] == 0.0
        assert r["recall"] == 1.0
        assert r["n_ref"] == 2
        assert r["n_hit"] == 2

    def test_total_miss(self):
        # 北屯實案：機廠全部辨識成機場
        r = calculate_ker("機廠的軌道電路", "機場的軌道電路", _kw("機廠"))
        assert r["ker"] == 1.0
        assert r["n_ref"] == 1
        assert r["n_hit"] == 0

    def test_partial_recall_weighted_by_occurrence(self):
        # ref 出現 2 次、hyp 只對 1 次 → recall 0.5
        r = calculate_ker("機廠送了，機廠剩一台車", "機廠送了，機場剩一台車", _kw("機廠"))
        assert r["n_ref"] == 2
        assert r["n_hit"] == 1
        assert r["ker"] == 0.5

    def test_hallucination_counted_separately(self):
        # ref 無「機廠」、hyp 有 → 不影響 KER（n_ref=0），記入幻覺數
        r = calculate_ker("列車停靠月台", "機廠列車停靠月台", _kw("機廠"))
        assert r["n_ref"] == 0
        assert r["ker"] == 0.0
        assert r["hallucinations"] == 1

    def test_no_keywords_in_ref_is_perfect(self):
        r = calculate_ker("早安你好", "早安妳好", _kw("機廠", "三軌"))
        assert r["ker"] == 0.0
        assert r["recall"] == 1.0

    def test_normalization_applied(self):
        # 大小寫/標點/空白差異不影響關鍵詞比對（沿用 cer_engine.normalize_text）
        r = calculate_ker("以MCP開啟車門", "以 mcp 開啟車門。", _kw("MCP"))
        assert r["ker"] == 0.0

    def test_by_keyword_detail(self):
        r = calculate_ker("機廠跟三軌", "機場跟三軌", _kw("機廠", "三軌"))
        assert r["by_keyword"]["機廠"] == {
            "ref": 1, "hyp": 0, "hit": 0, "alert_level": 2, "category": "test",
        }
        assert r["by_keyword"]["三軌"]["hit"] == 1

    def test_empty_inputs(self):
        r = calculate_ker("", "", _kw("機廠"))
        assert r["ker"] == 0.0
        assert r["n_ref"] == 0


class TestLoadKeywords:
    def test_loads_from_vocab_with_threshold(self):
        kws = load_keywords(min_alert_level=2)
        terms = [k["term"] for k in kws]
        assert "機廠" in terms          # 任務 1 新增、alert_level 2
        assert "電力異常" in terms      # alert_level 3
        assert "月台" not in terms      # alert_level 0，不該入列
        # 去重：CSV 內「停準」有兩列
        assert terms.count("停準") == 1

    def test_level3_only(self):
        kws = load_keywords(min_alert_level=3)
        assert all(k["alert_level"] >= 3 for k in kws)
        assert any(k["term"] == "電力異常" for k in kws)
