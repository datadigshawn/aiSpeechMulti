"""Tests for scripts/contextual_corrector.ContextualCorrector — 生產後處理
pipeline 的上下文敏感修正階段（2026-06-18 tech-debt B-1）。

contextual_corrector 是 post_process 的 Stage 2.5，經 post_process_realtime 跑在
每條生產 final transcript 上，原本只有模組內建的 ad-hoc TEST_CASES、無 pytest。
此檔：(1) 把內建 TEST_CASES 接成 pytest（真實 config 行為釘定），
(2) 用合成 rule 測機制（prefix/suffix/gap、no-match、確認型規則、change-log、overlay）。
"""

from __future__ import annotations

import json

import pytest

from scripts.contextual_corrector import ContextualCorrector, TEST_CASES


def _write_config(tmp_path, rules):
    p = tmp_path / "contextual_corrections.json"
    p.write_text(json.dumps({"rules": rules}, ensure_ascii=False), encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# 真實 config：沿用模組內建 TEST_CASES（作者意圖案例）
# ─────────────────────────────────────────────────────────────────────────────

_REAL_CC = ContextualCorrector()


@pytest.mark.skipif(not _REAL_CC.rules, reason="預設 contextual 規則檔不存在/為空")
@pytest.mark.parametrize("inp, expected, desc", TEST_CASES)
def test_builtin_cases(inp, expected, desc):
    out, _ = _REAL_CC.apply(inp)
    assert out == expected, desc


# ─────────────────────────────────────────────────────────────────────────────
# 合成 rule：測機制（與會變動的生產詞庫解耦）
# ─────────────────────────────────────────────────────────────────────────────

class TestMechanism:
    def test_prefix_rule_applies(self, tmp_path):
        cfg = _write_config(tmp_path, [{"prefix": "車", "wrong": "鬥", "right": "頭", "note": "車頭"}])
        cc = ContextualCorrector(config_path=cfg)
        out, changes = cc.apply("車鬥受損")
        assert out == "車頭受損"
        assert changes[0]["from"] == "鬥"
        assert changes[0]["to"] == "頭"
        assert changes[0]["count"] == 1

    def test_suffix_rule_applies(self, tmp_path):
        cfg = _write_config(tmp_path, [{"wrong": "越台", "suffix": "門", "right": "月台", "note": "月台門"}])
        cc = ContextualCorrector(config_path=cfg)
        out, _ = cc.apply("進入越台門")
        assert out == "進入月台門"

    def test_no_match_when_context_absent(self, tmp_path):
        """無前/後綴上下文時不動（避免過度修正）。"""
        cfg = _write_config(tmp_path, [{"prefix": "車", "wrong": "鬥", "right": "頭"}])
        cc = ContextualCorrector(config_path=cfg)
        out, changes = cc.apply("鬥很大")     # 無 '車' 前綴
        assert out == "鬥很大"
        assert changes == []

    def test_confirm_only_rule_skipped(self, tmp_path):
        """right == wrong 為『上下文確認型』規則，不修改文字。"""
        cfg = _write_config(tmp_path, [{"prefix": "三軌", "wrong": "復電", "right": "復電"}])
        cc = ContextualCorrector(config_path=cfg)
        out, changes = cc.apply("三軌復電")
        assert out == "三軌復電"
        assert changes == []

    def test_gap_allows_intervening_chars(self, tmp_path):
        cfg = _write_config(tmp_path, [{"prefix": "車", "wrong": "鬥", "right": "頭", "gap": 2}])
        cc = ContextualCorrector(config_path=cfg)
        out, _ = cc.apply("車的鬥")          # 前綴與 wrong 間隔 1 字，gap=2 仍命中
        assert out == "車的頭"

    def test_empty_and_no_rules(self, tmp_path):
        cfg = _write_config(tmp_path, [])
        cc = ContextualCorrector(config_path=cfg)
        assert cc.apply("任意文字") == ("任意文字", [])
        assert cc.apply("") == ("", [])


# ─────────────────────────────────────────────────────────────────────────────
# engine overlay：add / remove 規則
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineOverlay:
    def test_overlay_rule_add(self, tmp_path, monkeypatch):
        engines_dir = tmp_path / "engines"
        engines_dir.mkdir()
        (engines_dir / "myeng.json").write_text(
            json.dumps({"contextual_rules_add": [
                {"prefix": "車", "wrong": "鬥", "right": "頭"}
            ]}, ensure_ascii=False),
            encoding="utf-8",
        )
        monkeypatch.setattr("scripts.contextual_corrector.ENGINES_DIR", engines_dir)
        cfg = _write_config(tmp_path, [])     # base 無規則

        cc = ContextualCorrector(config_path=cfg, engine_hint="myeng")
        out, _ = cc.apply("車鬥")
        assert out == "車頭"                  # overlay 規則生效

    def test_overlay_rule_remove(self, tmp_path, monkeypatch):
        engines_dir = tmp_path / "engines"
        engines_dir.mkdir()
        (engines_dir / "myeng.json").write_text(
            json.dumps({"contextual_rules_remove": [{"wrong": "鬥"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        monkeypatch.setattr("scripts.contextual_corrector.ENGINES_DIR", engines_dir)
        cfg = _write_config(tmp_path, [{"prefix": "車", "wrong": "鬥", "right": "頭"}])

        cc = ContextualCorrector(config_path=cfg, engine_hint="myeng")
        out, _ = cc.apply("車鬥")
        assert out == "車鬥"                  # base 規則被 overlay 移除
