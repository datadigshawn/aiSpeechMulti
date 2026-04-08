#!/usr/bin/env python3
"""
強化版 initial_prompt / hotwords 建構器 (PromptBuilder)
========================================================
版本: 1.0.0 (2026-04-08)

把「單純術語列表」升級為「術語 + 範例句 + 上下文」的強化版 prompt，
支援依事件類型動態組合，供 Whisper / SenseVoice 等模型使用。

## 設計理念

**舊版 prompt**（只列術語）：
    這是一段台灣捷運無線電通訊。對話中包含以下專業術語：OCC、EDRH、G07...

**新版 prompt**（含範例句）：
    這是一段台灣台中捷運的車門與月台門相關事件。
    對話中常見的專業術語包括：EDRH、MTC、MCP、NCP、月台門、車門、25/26 車、05/06 車、停準、未停準。
    範例：G17 高鐵站呼叫 OCC，二月台列車 25/26 車門未開啟，請派人至 10 車門處以 EDRH 登上列車。

**預期改善**：
- 比 keyword-only prompt 再降 2~5% CER
- STT 模型能學到術語的自然上下文（人稱、動詞、時序）

## 支援的事件類型

- **default**: 通用預設（綜合術語）
- **daily**: 日常車務通訊
- **door**: 車門 / 月台門事件
- **track**: 軌道作業 / 電力
- **emergency**: 緊急事件
- **control**: 列車控制

## 用法（模組）

```python
from scripts.prompt_builder import build_whisper_prompt, build_sensevoice_hotwords

# Whisper
whisper_prompt = build_whisper_prompt(event_type="door")
# → "這是一段台灣台中捷運的車門與月台門相關事件。對話中常見..."

# SenseVoice
sv_hotwords = build_sensevoice_hotwords(event_type="emergency")
# → "火災 出軌 OCC 緊急 EDRH 撤離 受傷 立即 呼叫 over"

# 動態決定事件類型（後續可由分類器預測）
prompt = build_whisper_prompt(event_type="track")
```

## CLI

```
python3 scripts/prompt_builder.py --list                  # 列出所有事件類型
python3 scripts/prompt_builder.py --event-type door       # 顯示 door 的 prompt
python3 scripts/prompt_builder.py --format whisper         # 輸出 Whisper 格式
python3 scripts/prompt_builder.py --format sensevoice      # 輸出 SenseVoice 格式
python3 scripts/prompt_builder.py --test                   # 內建測試
```
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "vocabulary" / "initial_prompts.json"


@dataclass
class PromptSection:
    context: str
    keywords: list[str]
    example: str


# ══════════════════════════════════════════════════════════════════════
# 載入器（含快取）
# ══════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def _load_config() -> dict:
    """載入設定檔（僅載入一次）"""
    if not DEFAULT_CONFIG.exists():
        return {}
    try:
        return json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ 載入 {DEFAULT_CONFIG.name} 失敗: {e}", file=sys.stderr)
        return {}


def _get_section(event_type: str = "default") -> PromptSection:
    """取得指定事件類型的 prompt 片段，找不到則退回 default"""
    cfg = _load_config()

    # 1. 先找 event_types.{event_type}
    section_data = cfg.get("event_types", {}).get(event_type)
    if not section_data:
        # 2. 退回 default
        section_data = cfg.get("default", {})

    return PromptSection(
        context=section_data.get("context", "台灣捷運無線電通訊"),
        keywords=section_data.get("keywords", []),
        example=section_data.get("example", ""),
    )


def list_event_types() -> list[str]:
    """列出所有可用的事件類型"""
    cfg = _load_config()
    types = ["default"]
    types.extend(cfg.get("event_types", {}).keys())
    return types


# ══════════════════════════════════════════════════════════════════════
# Whisper 用：自然語言 prompt
# ══════════════════════════════════════════════════════════════════════
def build_whisper_prompt(
    event_type: str = "default",
    max_keywords: int = 10,
    include_example: bool = True,
) -> str:
    """產生 Whisper 的 initial_prompt（自然語言格式）

    Args:
        event_type: 事件類型（default/daily/door/track/emergency/control）
        max_keywords: 最多包含幾個關鍵詞
        include_example: 是否包含範例句（建議 True，效果較好）

    Returns:
        自然語言的 prompt 字串
    """
    section = _get_section(event_type)

    if not section.keywords:
        return "這是一段台灣捷運無線電通訊。"

    keywords_str = "、".join(section.keywords[:max_keywords])
    parts = [
        f"這是一段{section.context}。",
        f"對話中常見的專業術語包括：{keywords_str}。",
    ]
    if include_example and section.example:
        parts.append(f"範例：{section.example}")

    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════
# SenseVoice 用：空格分隔 hotwords
# ══════════════════════════════════════════════════════════════════════
def build_sensevoice_hotwords(
    event_type: str = "default",
    max_keywords: int = 20,
) -> str:
    """產生 SenseVoice 的 hotwords（空格分隔）

    Args:
        event_type: 事件類型
        max_keywords: 最多包含幾個熱詞

    Returns:
        空格分隔的熱詞字串
    """
    section = _get_section(event_type)
    return " ".join(section.keywords[:max_keywords])


def build_hotwords_list(event_type: str = "default") -> list[str]:
    """回傳純粹的熱詞清單（給需要 list 的場景）"""
    section = _get_section(event_type)
    return list(section.keywords)


# ══════════════════════════════════════════════════════════════════════
# 內建測試
# ══════════════════════════════════════════════════════════════════════
def run_tests() -> int:
    print("🧪 執行 PromptBuilder 測試")
    print("=" * 60)

    passed = 0
    total = 0

    # 測試 1: 可列出事件類型
    total += 1
    types = list_event_types()
    ok1 = "default" in types and len(types) >= 5
    mark = "✅" if ok1 else "❌"
    print(f"{mark} 可列出事件類型: {types}")
    if ok1:
        passed += 1

    # 測試 2: default 有基本內容
    total += 1
    default_prompt = build_whisper_prompt("default")
    ok2 = "OCC" in default_prompt and "範例" in default_prompt
    mark = "✅" if ok2 else "❌"
    print(f"{mark} default prompt 包含 OCC 與範例")
    if ok2:
        passed += 1

    # 測試 3: 事件類型不同 → prompt 不同
    total += 1
    door_prompt = build_whisper_prompt("door")
    track_prompt = build_whisper_prompt("track")
    emergency_prompt = build_whisper_prompt("emergency")
    ok3 = (door_prompt != track_prompt != emergency_prompt)
    mark = "✅" if ok3 else "❌"
    print(f"{mark} 不同事件類型產生不同 prompt")
    if ok3:
        passed += 1

    # 測試 4: 不存在的事件類型 → 退回 default
    total += 1
    unknown = build_whisper_prompt("nonexistent")
    ok4 = unknown == default_prompt
    mark = "✅" if ok4 else "❌"
    print(f"{mark} 未知事件類型退回 default")
    if ok4:
        passed += 1

    # 測試 5: include_example=False 不含範例
    total += 1
    no_example = build_whisper_prompt("door", include_example=False)
    ok5 = "範例" not in no_example
    mark = "✅" if ok5 else "❌"
    print(f"{mark} include_example=False 時不含範例")
    if ok5:
        passed += 1

    # 測試 6: SenseVoice hotwords 是空格分隔
    total += 1
    hw = build_sensevoice_hotwords("door")
    ok6 = " " in hw and "EDRH" in hw and "，" not in hw
    mark = "✅" if ok6 else "❌"
    print(f"{mark} SenseVoice hotwords 為空格分隔")
    if ok6:
        passed += 1

    # 測試 7: max_keywords 生效
    total += 1
    short_hw = build_sensevoice_hotwords("door", max_keywords=3)
    ok7 = len(short_hw.split(" ")) == 3
    mark = "✅" if ok7 else "❌"
    print(f"{mark} max_keywords 限制生效")
    if ok7:
        passed += 1

    print()
    print("=" * 60)
    print(f"結果: {passed}/{total} 通過")
    return 0 if passed == total else 1


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true", help="列出所有事件類型")
    p.add_argument("--event-type", default="default",
                   help="事件類型（預設 default）")
    p.add_argument("--format", default="whisper",
                   choices=["whisper", "sensevoice", "list"],
                   help="輸出格式")
    p.add_argument("--no-example", action="store_true",
                   help="Whisper 格式不含範例句")
    p.add_argument("--max-keywords", type=int, default=10)
    p.add_argument("--test", action="store_true", help="跑內建測試")
    args = p.parse_args()

    if args.test:
        sys.exit(run_tests())

    if args.list:
        print("可用事件類型：")
        for t in list_event_types():
            section = _get_section(t)
            print(f"  - {t:12} {section.context}（{len(section.keywords)} 個關鍵詞）")
        return

    print(f"📋 事件類型: {args.event_type}")
    print(f"📋 輸出格式: {args.format}")
    print()

    if args.format == "whisper":
        prompt = build_whisper_prompt(
            event_type=args.event_type,
            max_keywords=args.max_keywords,
            include_example=not args.no_example,
        )
        print("─── Whisper initial_prompt ───")
        print(prompt)
        print()
        print(f"長度: {len(prompt)} 字")
    elif args.format == "sensevoice":
        hw = build_sensevoice_hotwords(
            event_type=args.event_type,
            max_keywords=args.max_keywords,
        )
        print("─── SenseVoice hotwords ───")
        print(hw)
        print()
        print(f"熱詞數: {len(hw.split())}")
    elif args.format == "list":
        keywords = build_hotwords_list(args.event_type)
        print("─── Keywords list ───")
        for kw in keywords:
            print(f"  - {kw}")


if __name__ == "__main__":
    main()
