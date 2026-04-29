#!/usr/bin/env python3
"""
術語黑白名單過濾器 (TermFilter)
==================================
版本: 1.1.0 (2026-04-29) — 支援 engine-specific overlay

在後處理 pipeline 最外層運作：

    輸入文字 ──→ [1] apply_blacklist (絕對錯字強制替換)
                       │
                       ▼
              [2] protect_whitelist (關鍵術語 placeholder)
                       │
                       ▼
              [其他 pipeline: car_norm / dict / LLM]
                       │
                       ▼
              [3] restore_whitelist (還原 placeholder)
                       │
                       ▼
                   最終輸出

設計理念：
- **Blacklist**：絕對錯字 → 最早強制替換（優先於任何其他規則）
- **Whitelist**：關鍵術語 → 用 placeholder 凍結，避免後續 stage 誤改
- **Protected patterns**：regex 模式保護（如 G07/R01/25/26 車）

資料來源：vocabulary/term_filter.json

用法（模組）：
    from scripts.term_filter import TermFilter

    tf = TermFilter()

    # 方式 1: 完整保護流程
    text = tf.apply_blacklist(text)
    text, placeholder_map = tf.protect_whitelist(text)
    # ... 執行其他 pipeline ...
    text = tf.restore_whitelist(text, placeholder_map)

    # 方式 2: 單獨使用
    text, changes = tf.apply_blacklist_with_log(text)

用法（CLI）：
    python3 scripts/term_filter.py --text "歐西呼叫G07，越台門即將關閉"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "vocabulary" / "term_filter.json"
ENGINES_DIR = PROJECT_ROOT / "vocabulary" / "engines"

# Engine alias：把 dashboard / sub-model 名映射到 overlay 檔名
# overlay 路徑：vocabulary/engines/{value}.json
ENGINE_ALIASES = {
    # Gemini 子模型
    "gemini-2.5-pro":         "gemini25pro",
    "gemini-3.1-pro-preview": "gemini31pro",
    "gemini-2.5-flash":       "gemini",
    "gemini-2.5-flash-lite":  "gemini",
    "gemini-2.0-flash":       "gemini",
    # Google STT 子模型
    "chirp_3":                "chirp3",
    "chirp_2":                "chirp3",
    "chirp":                  "chirp3",
    "chirp_telephony":        "chirp3",
    "google_stt":             "chirp3",
    # Whisper 子模型
    "large-v3":               "whisper",
    "turbo":                  "whisper",
    "medium":                 "whisper",
    # SenseVoice 子模型
    "iic/SenseVoiceSmall":    "sensevoice",
    "sensevoice":             "sensevoice",
}


# ══════════════════════════════════════════════════════════════════════
# 共用：依 engine_hint 查 overlay 的 audio_preprocess 設定
# （讓 batch_stt_eval / dashboard 能根據引擎差異選擇是否預處理音檔）
# ══════════════════════════════════════════════════════════════════════
def get_engine_audio_preprocess(engine_hint: Optional[str]) -> dict:
    """
    回傳 {"enabled": bool, "filter": str | None, "overlay_file": str | None}。
    若該引擎沒有 overlay 或沒設 audio_preprocess，預設 enabled=False。
    """
    default = {"enabled": False, "filter": None, "overlay_file": None}
    if not engine_hint:
        return default
    # 先直接檔名
    p = ENGINES_DIR / f"{engine_hint}.json"
    if not p.exists():
        # 再 alias
        alias = ENGINE_ALIASES.get(engine_hint)
        if alias:
            p = ENGINES_DIR / f"{alias}.json"
    if not p.exists():
        return default
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default
    ap = cfg.get("audio_preprocess") or {}
    return {
        "enabled":      bool(ap.get("enabled", False)),
        "filter":       ap.get("filter"),
        "overlay_file": p.name,
    }


# Placeholder 格式（用罕見字元包住編號，避免被任何 pipeline 改到）
_PLACEHOLDER_PREFIX = "\u2060TFPH\u2060"   # WORD JOINER 包住 "TFPH" (Term Filter PlaceHolder)
_PLACEHOLDER_SUFFIX = "\u2060END\u2060"


@dataclass
class TermFilterChange:
    """修正紀錄"""
    stage: str          # "blacklist" | "whitelist_protect" | "whitelist_restore"
    original: str
    replaced: str
    count: int = 1


# ══════════════════════════════════════════════════════════════════════
# TermFilter 主類別
# ══════════════════════════════════════════════════════════════════════
class TermFilter:
    """術語黑白名單過濾器"""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        engine_hint: Optional[str] = None,
    ):
        """
        Args:
            config_path: 共用基底設定（預設 vocabulary/term_filter.json）
            engine_hint: 引擎名稱（如 "gemini25pro"、"scribe"、"gemini-2.5-pro"）。
                         若有對應的 vocabulary/engines/{key}.json overlay 則合併。
        """
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG
        self.engine_hint = engine_hint
        self.engine_overlay_path: Optional[Path] = None
        self.blacklist: dict[str, str] = {}
        self.whitelist: list[str] = []
        self.protected_patterns: list[re.Pattern] = []
        self.overlay_summary: dict = {
            "applied": False,
            "engine": None,
            "blacklist_added": 0,
            "blacklist_removed": 0,
            "whitelist_added": 0,
            "whitelist_removed": 0,
        }
        self._load_config()

    def _resolve_overlay_path(self) -> Optional[Path]:
        """依 engine_hint 找 overlay 檔，找不到回傳 None"""
        if not self.engine_hint:
            return None
        # 1) 直接匹配 vocabulary/engines/{engine_hint}.json
        direct = ENGINES_DIR / f"{self.engine_hint}.json"
        if direct.exists():
            return direct
        # 2) 透過 alias map 對應
        alias_key = ENGINE_ALIASES.get(self.engine_hint)
        if alias_key:
            via_alias = ENGINES_DIR / f"{alias_key}.json"
            if via_alias.exists():
                return via_alias
        return None

    def _load_config(self) -> None:
        """先載基底，再依 engine_hint 套 overlay"""
        # ── 基底 ─────────────────────────────────────────────
        if not self.config_path.exists():
            print(f"⚠️ term_filter 設定檔不存在: {self.config_path}")
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            self.blacklist = dict(data.get("blacklist", {}))
            self.whitelist = list(data.get("whitelist", []))
            patterns = data.get("protected_patterns", [])
            self.protected_patterns = [re.compile(p) for p in patterns]
        except Exception as e:
            print(f"⚠️ 載入 term_filter 基底設定失敗: {e}")
            return

        # ── Overlay（依 engine_hint）───────────────────────────
        self.engine_overlay_path = self._resolve_overlay_path()
        if not self.engine_overlay_path:
            return
        try:
            overlay = json.loads(self.engine_overlay_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠️ 載入 engine overlay 失敗 ({self.engine_overlay_path.name}): {e}")
            return

        bl_add = overlay.get("blacklist_add", {}) or {}
        bl_rm = overlay.get("blacklist_remove", []) or []
        wl_add = overlay.get("whitelist_add", []) or []
        wl_rm = overlay.get("whitelist_remove", []) or []
        pat_add = overlay.get("protected_patterns_add", []) or []

        for k, v in bl_add.items():
            self.blacklist[k] = v
        for k in bl_rm:
            self.blacklist.pop(k, None)
        for term in wl_add:
            if term not in self.whitelist:
                self.whitelist.append(term)
        for term in wl_rm:
            if term in self.whitelist:
                self.whitelist.remove(term)
        for p in pat_add:
            try:
                self.protected_patterns.append(re.compile(p))
            except re.error as e:
                print(f"⚠️ overlay protected_patterns 編譯失敗: {p} ({e})")

        self.overlay_summary = {
            "applied":           True,
            "engine":            self.engine_hint,
            "overlay_file":      self.engine_overlay_path.name,
            "blacklist_added":   len(bl_add),
            "blacklist_removed": len(bl_rm),
            "whitelist_added":   len(wl_add),
            "whitelist_removed": len(wl_rm),
            "patterns_added":    len(pat_add),
        }

    # ══════════════════════════════════════════════════════════════
    # Blacklist: 強制替換
    # ══════════════════════════════════════════════════════════════
    def apply_blacklist(self, text: str) -> str:
        """套用黑名單（簡易版，不記錄）"""
        result, _ = self.apply_blacklist_with_log(text)
        return result

    def apply_blacklist_with_log(self, text: str) -> tuple[str, list[TermFilterChange]]:
        """套用黑名單並回傳修正紀錄"""
        if not text or not self.blacklist:
            return text, []

        changes: list[TermFilterChange] = []
        result = text

        # 依鍵長度降序排列（先替長詞避免短詞誤觸）
        sorted_items = sorted(self.blacklist.items(), key=lambda x: -len(x[0]))
        for wrong, right in sorted_items:
            if not wrong or not right or wrong == right:
                continue
            if wrong in result:
                count = result.count(wrong)
                result = result.replace(wrong, right)
                changes.append(TermFilterChange(
                    stage="blacklist",
                    original=wrong,
                    replaced=right,
                    count=count,
                ))
        return result, changes

    # ══════════════════════════════════════════════════════════════
    # Whitelist: placeholder 保護
    # ══════════════════════════════════════════════════════════════
    def protect_whitelist(self, text: str) -> tuple[str, dict[str, str]]:
        """保護白名單術語與 protected_patterns

        回傳: (替換後文字, placeholder → 原文字的對應表)
        """
        if not text:
            return text, {}

        placeholder_map: dict[str, str] = {}
        result = text
        counter = 0

        def _make_placeholder(original: str) -> str:
            nonlocal counter
            ph = f"{_PLACEHOLDER_PREFIX}{counter:04d}{_PLACEHOLDER_SUFFIX}"
            placeholder_map[ph] = original
            counter += 1
            return ph

        # (1) 先套 protected_patterns（如 G07/R01/25/26 車）
        for pat in self.protected_patterns:
            def _pat_replacer(m):
                return _make_placeholder(m.group(0))
            result = pat.sub(_pat_replacer, result)

        # (2) 再套 whitelist 字串（依長度降序）
        sorted_wl = sorted(self.whitelist, key=lambda x: -len(x))
        for term in sorted_wl:
            if not term or term in placeholder_map.values():
                continue
            # 用 re.escape 避免 regex 特殊字元
            pattern = re.compile(re.escape(term))
            def _wl_replacer(m):
                return _make_placeholder(m.group(0))
            result = pattern.sub(_wl_replacer, result)

        return result, placeholder_map

    def restore_whitelist(self, text: str, placeholder_map: dict[str, str]) -> str:
        """還原白名單 placeholder"""
        if not text or not placeholder_map:
            return text
        result = text
        # 依 placeholder 長度降序還原（避免嵌套問題）
        for ph in sorted(placeholder_map.keys(), key=lambda x: -len(x)):
            result = result.replace(ph, placeholder_map[ph])
        return result

    # ══════════════════════════════════════════════════════════════
    # 全流程一次性處理
    # ══════════════════════════════════════════════════════════════
    def run_pre_pipeline(self, text: str) -> tuple[str, dict[str, str], list[TermFilterChange]]:
        """pipeline 前處理：blacklist + whitelist protect

        Returns:
            (處理後文字, placeholder_map, blacklist_changes)
        """
        text, bl_changes = self.apply_blacklist_with_log(text)
        text, ph_map = self.protect_whitelist(text)
        return text, ph_map, bl_changes

    def run_post_pipeline(self, text: str, placeholder_map: dict[str, str]) -> str:
        """pipeline 後處理：還原 whitelist"""
        return self.restore_whitelist(text, placeholder_map)


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--text", help="輸入文字")
    p.add_argument("--file", help="輸入檔案路徑")
    p.add_argument("--config", help="自訂設定檔路徑")
    p.add_argument("--engine", help="引擎名稱（會套用 vocabulary/engines/{engine}.json overlay）")
    p.add_argument("--show-config", action="store_true", help="顯示目前載入的設定")
    p.add_argument("--test", action="store_true", help="跑內建測試")
    args = p.parse_args()

    tf = TermFilter(
        config_path=Path(args.config) if args.config else None,
        engine_hint=args.engine,
    )

    if args.show_config:
        print(f"📋 基底: {tf.config_path}")
        if tf.overlay_summary.get("applied"):
            print(f"📦 Overlay: {tf.engine_overlay_path}  (engine={tf.engine_hint})")
            print(f"   blacklist +{tf.overlay_summary['blacklist_added']} / -{tf.overlay_summary['blacklist_removed']}")
            print(f"   whitelist +{tf.overlay_summary['whitelist_added']} / -{tf.overlay_summary['whitelist_removed']}")
        elif tf.engine_hint:
            print(f"📦 Overlay: 找不到（engine={tf.engine_hint}），僅使用基底")
        print(f"   Blacklist (合併後): {len(tf.blacklist)} 條")
        print(f"   Whitelist (合併後): {len(tf.whitelist)} 條")
        print(f"   Protected patterns: {len(tf.protected_patterns)} 條")
        print()
        print("--- Blacklist ---")
        for wrong, right in tf.blacklist.items():
            print(f"   {wrong!r:20} → {right!r}")
        print()
        print("--- Whitelist ---")
        print(f"   {tf.whitelist}")
        print()
        print("--- Protected Patterns ---")
        for p in tf.protected_patterns:
            print(f"   {p.pattern}")
        return

    if args.test:
        test_cases = [
            ("歐西呼叫G07，越台門即將關閉 over",
             "OCC呼叫G07，月台門即將關閉 over"),
            ("請 OCC 通告全線，EDRH 已啟用",
             "請 OCC 通告全線，EDRH 已啟用"),  # whitelist 保護，不變
            ("25/26 車門未開啟，清查作業中",
             "25/26 車門未開啟，清車作業中"),  # 清查 → 清車
            ("輔電作業開始，歐西通告",
             "復電作業開始，OCC通告"),
        ]
        passed = 0
        for i, (inp, expected) in enumerate(test_cases, 1):
            text, ph_map, bl_changes = tf.run_pre_pipeline(inp)
            result = tf.run_post_pipeline(text, ph_map)
            ok = result == expected
            mark = "✅" if ok else "❌"
            print(f"  {mark} Test {i}")
            print(f"     in:       {inp!r}")
            print(f"     expected: {expected!r}")
            print(f"     got:      {result!r}")
            if bl_changes:
                for c in bl_changes:
                    print(f"     blacklist: {c.original!r} → {c.replaced!r} ×{c.count}")
            if ok:
                passed += 1
        print()
        print(f"結果: {passed}/{len(test_cases)}")
        sys.exit(0 if passed == len(test_cases) else 1)

    # 基本 CLI: 輸入文字或檔案，輸出處理結果
    if args.file:
        path = Path(args.file)
        text = path.read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        print("❌ 請提供 --text、--file、--show-config 或 --test")
        sys.exit(1)

    print("─── 原文 ───")
    print(text)
    print()

    # Pre pipeline
    bl_text, bl_changes = tf.apply_blacklist_with_log(text)
    print("─── 套 blacklist 後 ───")
    print(bl_text)
    print()
    print(f"   blacklist 修正 {len(bl_changes)} 項：")
    for c in bl_changes:
        print(f"     {c.original!r} → {c.replaced!r} ×{c.count}")
    print()

    protected_text, ph_map = tf.protect_whitelist(bl_text)
    print("─── 保護 whitelist 後（placeholder）───")
    print(protected_text)
    print()
    print(f"   保護了 {len(ph_map)} 個 token")
    for ph, orig in list(ph_map.items())[:10]:
        print(f"     {ph!r} ← {orig!r}")

    # Restore
    restored = tf.restore_whitelist(protected_text, ph_map)
    print()
    print("─── 還原後 ───")
    print(restored)


if __name__ == "__main__":
    main()
