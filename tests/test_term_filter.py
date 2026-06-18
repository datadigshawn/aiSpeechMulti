"""Tests for scripts/term_filter.TermFilter — 生產後處理 pipeline 的 blacklist /
whitelist 保護階段（2026-06-18 tech-debt B-1）。

term_filter 是 post_process 的 Stage 0（blacklist）與 LLM 前後（whitelist
protect/restore），經 post_process_realtime 跑在每條生產 final transcript 上，
原本零測試。此檔以「合成 config 測機制 + 真實 config 煙霧」鎖定其行為。
"""

from __future__ import annotations

import json

from scripts.term_filter import TermFilter


def _write_config(tmp_path, blacklist=None, whitelist=None, protected_patterns=None):
    cfg = {
        "blacklist": blacklist or {},
        "whitelist": whitelist or [],
        "protected_patterns": protected_patterns or [],
    }
    p = tmp_path / "term_filter.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# blacklist：強制替換 + change log
# ─────────────────────────────────────────────────────────────────────────────

class TestBlacklist:
    def test_replaces_and_logs(self, tmp_path):
        cfg = _write_config(tmp_path, blacklist={"歐西": "OCC"})
        tf = TermFilter(config_path=cfg)
        out, changes = tf.apply_blacklist_with_log("歐西通告全線，歐西")
        assert out == "OCC通告全線，OCC"
        assert len(changes) == 1
        c = changes[0]
        assert c.original == "歐西"
        assert c.replaced == "OCC"
        assert c.count == 2          # 出現兩次

    def test_longest_key_first_avoids_short_mis_trigger(self, tmp_path):
        """長詞優先：'月台門' 先被整體替換，'月台' 不再誤觸。"""
        cfg = _write_config(tmp_path, blacklist={"月台門": "X", "月台": "Y"})
        tf = TermFilter(config_path=cfg)
        out, _ = tf.apply_blacklist_with_log("月台門")
        assert out == "X"           # 若短詞優先會變成 "Y門"

    def test_skips_identity_rule(self, tmp_path):
        cfg = _write_config(tmp_path, blacklist={"OCC": "OCC"})
        tf = TermFilter(config_path=cfg)
        out, changes = tf.apply_blacklist_with_log("OCC通告")
        assert out == "OCC通告"
        assert changes == []

    def test_empty_and_no_match(self, tmp_path):
        cfg = _write_config(tmp_path, blacklist={"歐西": "OCC"})
        tf = TermFilter(config_path=cfg)
        assert tf.apply_blacklist_with_log("") == ("", [])
        assert tf.apply_blacklist_with_log("正常文字") == ("正常文字", [])

    def test_apply_blacklist_simple_equals_logged(self, tmp_path):
        cfg = _write_config(tmp_path, blacklist={"歐西": "OCC"})
        tf = TermFilter(config_path=cfg)
        assert tf.apply_blacklist("歐西") == "OCC"


# ─────────────────────────────────────────────────────────────────────────────
# whitelist / protected_patterns：placeholder 保護 → 還原 round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestWhitelistProtectRestore:
    def test_round_trip_recovers_original(self, tmp_path):
        cfg = _write_config(
            tmp_path,
            whitelist=["月台門"],
            protected_patterns=[r"G\d\d"],
        )
        tf = TermFilter(config_path=cfg)
        text = "在G07月台門等候"
        protected, pmap = tf.protect_whitelist(text)
        # 受保護內容已被 placeholder 取代（原字串不再出現）
        assert "G07" not in protected
        assert "月台門" not in protected
        assert pmap                      # 有對應表
        # 還原回原文
        assert tf.restore_whitelist(protected, pmap) == text

    def test_protected_term_survives_surrounding_edit(self, tmp_path):
        """模擬 LLM 改了非 placeholder 的周邊字，受保護術語仍能精確還原。"""
        cfg = _write_config(tmp_path, whitelist=["月台門"], protected_patterns=[r"G\d\d"])
        tf = TermFilter(config_path=cfg)
        protected, pmap = tf.protect_whitelist("G07月台門附近")
        mangled = protected.replace("附近", "周邊")     # 動非 placeholder 部分
        restored = tf.restore_whitelist(mangled, pmap)
        assert restored == "G07月台門周邊"

    def test_restore_noop_without_map(self, tmp_path):
        cfg = _write_config(tmp_path)
        tf = TermFilter(config_path=cfg)
        assert tf.restore_whitelist("文字", {}) == "文字"


# ─────────────────────────────────────────────────────────────────────────────
# engine overlay：base + engines/{engine}.json 合併
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineOverlay:
    def test_overlay_blacklist_add(self, tmp_path, monkeypatch):
        engines_dir = tmp_path / "engines"
        engines_dir.mkdir()
        (engines_dir / "myeng.json").write_text(
            json.dumps({"blacklist_add": {"哦西": "OCC"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        monkeypatch.setattr("scripts.term_filter.ENGINES_DIR", engines_dir)
        cfg = _write_config(tmp_path, blacklist={"歐西": "OCC"})

        tf = TermFilter(config_path=cfg, engine_hint="myeng")
        out, _ = tf.apply_blacklist_with_log("歐西與哦西")
        assert out == "OCC與OCC"     # base + overlay 都生效


# ─────────────────────────────────────────────────────────────────────────────
# 真實 config 煙霧：預設載入不報錯
# ─────────────────────────────────────────────────────────────────────────────

class TestRealConfigSmoke:
    def test_default_loads(self):
        tf = TermFilter()
        # 預設 config 應載入出非空 blacklist（生產詞庫）
        assert isinstance(tf.blacklist, dict)
        # 載入後 apply 不應拋例外
        out, _ = tf.apply_blacklist_with_log("測試一段文字")
        assert isinstance(out, str)
