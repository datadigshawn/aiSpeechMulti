#!/usr/bin/env python3
"""
上下文敏感修正器 (ContextualCorrector)
========================================
版本: 1.1.0 (2026-04-29) — 支援 engine-specific overlay

把 correction_dict（純字串替換）升級為三元組規則：

    (prefix, wrong, suffix) → right

比起 dict 的字串替換，三元組規則能：
1. **避免 false positive**：例如 `越台` 只在後接 `門` 或前有 `上/下/至` 時才修正
2. **同字不同修正**：例如 `輔電` 在 `三軌` 上下文改為 `復電`，在其他上下文保留
3. **保留上下文語意**：`拘止繩` 必須前後配對才改成 `警戒繩`

## 規則格式（vocabulary/contextual_corrections.json）

```json
{
  "rules": [
    {
      "prefix": "進入",       // 前綴（空字串表示無限制）
      "wrong":  "越台",       // 要修正的錯字
      "suffix": "門",         // 後綴（空字串表示無限制）
      "right":  "月台",       // 修正後
      "gap":    0,            // prefix 與 wrong、wrong 與 suffix 的最大間隔
      "note":   "月台門"      // 說明
    }
  ]
}
```

## 匹配邏輯

1. 若 `prefix` 非空：`wrong` 前必須有 `prefix`（允許 `gap` 字元間隔）
2. 若 `suffix` 非空：`wrong` 後必須有 `suffix`（允許 `gap` 字元間隔）
3. 兩者皆空時，退化為純字串替換（但仍比 dict 嚴格：只匹配一次）
4. 替換時**只改 `wrong` 本身**，prefix 與 suffix 保留不動

## 用法

### 模組
```python
from scripts.contextual_corrector import ContextualCorrector

cc = ContextualCorrector()
text, changes = cc.apply("進入越台門即將關閉")
# text = "進入月台門即將關閉"
```

### CLI
```
python3 scripts/contextual_corrector.py --test
python3 scripts/contextual_corrector.py --text "三軌輔電作業"
python3 scripts/contextual_corrector.py --show-config
```
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

logger = get_logger("contextual_corrector")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "vocabulary" / "contextual_corrections.json"

# 共用 engine alias map 與 overlay 目錄（與 TermFilter 一致）
try:
    from scripts.term_filter import ENGINE_ALIASES, ENGINES_DIR
except ImportError:
    ENGINE_ALIASES = {}
    ENGINES_DIR = PROJECT_ROOT / "vocabulary" / "engines"


@dataclass
class ContextualRule:
    prefix: str
    wrong: str
    suffix: str
    right: str
    gap: int = 0
    note: str = ""

    def to_regex(self) -> re.Pattern:
        """將三元組規則編譯為 regex

        - prefix 非空 → 用 lookbehind: `(?<=prefix.{0,gap})`
        - suffix 非空 → 用 lookahead: `(?=.{0,gap}suffix)`
        - wrong 本身用 group capture
        """
        pattern = ""
        if self.prefix:
            # Python regex 的 lookbehind 需要固定長度，所以用 group capture 再替換
            if self.gap > 0:
                pattern += f"(?<={re.escape(self.prefix)})" + f".{{0,{self.gap}}}"
            else:
                pattern += f"(?<={re.escape(self.prefix)})"

        pattern += f"({re.escape(self.wrong)})"

        if self.suffix:
            if self.gap > 0:
                pattern += f".{{0,{self.gap}}}" + f"(?={re.escape(self.suffix)})"
            else:
                pattern += f"(?={re.escape(self.suffix)})"

        return re.compile(pattern)


# ══════════════════════════════════════════════════════════════════════
# 主類別
# ══════════════════════════════════════════════════════════════════════
class ContextualCorrector:
    """上下文敏感修正器（支援 engine-specific overlay）"""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        engine_hint: Optional[str] = None,
    ):
        """
        Args:
            config_path: 共用基底（預設 vocabulary/contextual_corrections.json）
            engine_hint: 引擎名稱。若 vocabulary/engines/{engine}.json 含
                         contextual_rules_add / contextual_rules_remove 欄位則合併。
        """
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG
        self.engine_hint = engine_hint
        self.engine_overlay_path: Optional[Path] = None
        self.rules: list[ContextualRule] = []
        self.overlay_summary: dict = {
            "applied":           False,
            "engine":            None,
            "rules_added":       0,
            "rules_removed":     0,
        }
        self._load_rules()

    def _resolve_overlay_path(self) -> Optional[Path]:
        """依 engine_hint 找 overlay 檔（與 TermFilter 共用同一目錄）"""
        if not self.engine_hint:
            return None
        direct = ENGINES_DIR / f"{self.engine_hint}.json"
        if direct.exists():
            return direct
        alias_key = ENGINE_ALIASES.get(self.engine_hint)
        if alias_key:
            via_alias = ENGINES_DIR / f"{alias_key}.json"
            if via_alias.exists():
                return via_alias
        return None

    def _make_rule(self, r: dict) -> Optional[ContextualRule]:
        if not r.get("wrong"):
            return None
        return ContextualRule(
            prefix=r.get("prefix", "") or "",
            wrong=r["wrong"],
            suffix=r.get("suffix", "") or "",
            right=r.get("right", "") or "",
            gap=int(r.get("gap", 0)),
            note=r.get("note", "") or "",
        )

    def _load_rules(self) -> None:
        # ── 基底 ─────────────────────────────────────────────
        if not self.config_path.exists():
            logger.warning(f"規則檔不存在: {self.config_path}")
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            for r in data.get("rules", []):
                rule = self._make_rule(r)
                if rule:
                    self.rules.append(rule)
        except Exception as e:
            logger.warning(f"載入基底規則失敗: {e}")
            return

        # ── Overlay（依 engine_hint）───────────────────────────
        self.engine_overlay_path = self._resolve_overlay_path()
        if not self.engine_overlay_path:
            return
        try:
            overlay = json.loads(self.engine_overlay_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"載入 contextual overlay 失敗 ({self.engine_overlay_path.name}): {e}")
            return

        rules_add = overlay.get("contextual_rules_add", []) or []
        rules_rm = overlay.get("contextual_rules_remove", []) or []

        # 移除（依 wrong 字串匹配；可選 prefix/suffix 進一步過濾）
        if rules_rm:
            def _matches_remove(existing: ContextualRule, spec: dict) -> bool:
                if existing.wrong != spec.get("wrong"):
                    return False
                if "prefix" in spec and existing.prefix != spec["prefix"]:
                    return False
                if "suffix" in spec and existing.suffix != spec["suffix"]:
                    return False
                return True
            self.rules = [
                r for r in self.rules
                if not any(_matches_remove(r, spec) for spec in rules_rm)
            ]

        # 新增
        added = 0
        for r in rules_add:
            rule = self._make_rule(r)
            if rule:
                self.rules.append(rule)
                added += 1

        self.overlay_summary = {
            "applied":       True,
            "engine":        self.engine_hint,
            "overlay_file":  self.engine_overlay_path.name,
            "rules_added":   added,
            "rules_removed": len(rules_rm),
        }

    def apply(self, text: str) -> tuple[str, list[dict]]:
        """套用所有規則

        Returns:
            (修正後文字, 修正紀錄清單)
        """
        if not text or not self.rules:
            return text, []

        changes: list[dict] = []
        result = text

        for rule in self.rules:
            # 若 right == wrong，代表這是「上下文確認」型規則，不修改
            if rule.right == rule.wrong:
                continue

            # 使用 regex 匹配並替換
            try:
                pattern = rule.to_regex()
                matches = list(pattern.finditer(result))
                if not matches:
                    continue

                # 從右到左替換，避免索引偏移
                for m in reversed(matches):
                    start, end = m.start(1), m.end(1)  # group 1 = wrong 本身
                    before = result[:start]
                    after = result[end:]
                    result = before + rule.right + after

                changes.append({
                    "from": rule.wrong,
                    "to": rule.right,
                    "count": len(matches),
                    "rule": f"contextual:{rule.note}" if rule.note else "contextual",
                    "prefix": rule.prefix,
                    "suffix": rule.suffix,
                })
            except re.error as e:
                logger.warning(f"規則編譯失敗 ({rule.wrong}): {e}")
                continue

        return result, changes


# ══════════════════════════════════════════════════════════════════════
# 內建測試
# ══════════════════════════════════════════════════════════════════════
TEST_CASES = [
    # (輸入, 預期輸出, 說明)
    # 後綴規則
    ("進入越台門即將關閉", "進入月台門即將關閉", "(, 越台, 門) → 月台"),
    ("越台門關閉", "月台門關閉", "越台 + 門 → 月台 (無前綴)"),

    # 前綴規則
    ("請上越台車", "請上月台車", "上 + 越台 → 月台"),
    ("下越台待命", "下月台待命", "下 + 越台 → 月台"),
    ("至越台協助", "至月台協助", "至 + 越台 → 月台"),

    # 不匹配：沒有符合的前後綴
    ("越台是什麼", "越台是什麼", "單獨越台不動（無前後綴符合）"),

    # 三軌 + 輔電
    ("三軌輔電作業", "三軌復電作業", "三軌 + 輔電 → 復電"),
    ("三軌鋪電", "三軌復電", "三軌 + 鋪電 → 復電"),

    # 不匹配：輔電在其他上下文不改
    ("備用輔電系統", "備用輔電系統", "非三軌上下文不改輔電"),

    # 車頭誤辨
    ("車鬥受損", "車頭受損", "車 + 鬥 → 頭"),
    ("車斗故障", "車頭故障", "車 + 斗 → 頭"),

    # 警戒繩
    ("拉起拘止繩", "拉起警戒繩", "拘止 + 繩 → 警戒"),

    # 待避軌
    ("列車停在待行軌", "列車停在待避軌", "待行軌 → 待避軌"),

    # OCC 回復
    ("OCC回服站長", "OCC回復站長", "OCC + 回服 → 回復"),

    # 複合
    ("車鬥撞擊，三軌輔電中斷，請至越台門協助",
     "車頭撞擊，三軌復電中斷，請至月台門協助",
     "三條規則同時觸發"),

    # 無變動
    ("OCC 通告全線", "OCC 通告全線", "無匹配"),
]


def run_tests() -> int:
    cc = ContextualCorrector()
    if not cc.rules:
        print("❌ 無規則可測試")
        return 1

    print(f"🧪 執行 {len(TEST_CASES)} 個測試（已載入 {len(cc.rules)} 條規則）")
    print("=" * 70)
    passed = 0
    for i, (inp, expected, desc) in enumerate(TEST_CASES, 1):
        result, changes = cc.apply(inp)
        ok = result == expected
        mark = "✅" if ok else "❌"
        print(f"{mark} #{i:2} [{desc}]")
        print(f"     in:       {inp!r}")
        if not ok:
            print(f"     expected: {expected!r}")
            print(f"     actual:   {result!r}")
            if changes:
                for c in changes:
                    print(f"     change:   {c['from']!r} → {c['to']!r}")
        else:
            passed += 1
    print()
    print("=" * 70)
    print(f"結果: {passed}/{len(TEST_CASES)} 通過")
    return 0 if passed == len(TEST_CASES) else 1


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", help="引擎名稱（會套 vocabulary/engines/{engine}.json 中的 contextual_rules_add/remove）")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--test", action="store_true", help="跑內建測試")
    grp.add_argument("--show-config", action="store_true", help="顯示載入的規則")
    grp.add_argument("--text", help="修正單句")
    grp.add_argument("--file", help="修正檔案")
    args = p.parse_args()

    cc = ContextualCorrector(engine_hint=args.engine)

    if args.test:
        sys.exit(run_tests())

    if args.show_config:
        print(f"📋 基底: {cc.config_path}")
        if cc.overlay_summary.get("applied"):
            print(f"📦 Overlay: {cc.engine_overlay_path}  (engine={cc.engine_hint})")
            print(f"   contextual rules +{cc.overlay_summary['rules_added']} / -{cc.overlay_summary['rules_removed']}")
        elif cc.engine_hint:
            print(f"📦 Overlay: 找不到（engine={cc.engine_hint}），僅使用基底")
        print(f"   規則數（合併後）: {len(cc.rules)}")
        print()
        for i, r in enumerate(cc.rules, 1):
            print(f"{i:2}. ({r.prefix!r:10}, {r.wrong!r:10}, {r.suffix!r:10}) → {r.right!r}")
            if r.note:
                print(f"    💬 {r.note}")
        return

    text = args.text if args.text else Path(args.file).read_text(encoding="utf-8")
    result, changes = cc.apply(text)
    print("─── 原文 ───")
    print(text)
    print()
    print("─── 修正後 ───")
    print(result)
    print()
    print(f"─── 修正紀錄（{len(changes)} 處）───")
    for c in changes:
        print(f"  {c['from']!r} → {c['to']!r}  ×{c['count']}  [{c.get('rule','')}]")


if __name__ == "__main__":
    main()
