#!/usr/bin/env python3
"""
多引擎 Ensemble PoC（Phase 4 PoC #2）
=====================================

對黃金語料集每段，同時讀 3 個主力引擎的辨識結果（gemini25pro / scribe / sensevoice），
用 LLM（gemini-2.5-flash）做「三選一/融合」仲裁，產出 ensemble 版本。

設計：LLM 仲裁勝過字級對齊投票
- gemini25pro 字數對齊 92% 但容易漏字
- scribe 字數對齊好但錯字多
- sensevoice 簡體輸出但成本零
- 三者各有所長 → LLM 看完三份 + 知識庫術語 → 挑/融合最佳版本

用法：
    # 對 63 段做 ensemble，輸出至 stt_outputs/ensemble_v1/
    python3 scripts/ensemble_eval.py

    # 自訂 LLM 模型
    python3 scripts/ensemble_eval.py --model gemini-2.5-pro
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.gemini_client import get_client, genai_types  # noqa: E402

MANIFEST_PATH = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"
STT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "stt_outputs"

ENGINES = ["gemini25pro", "scribe", "sensevoice"]


# ══════════════════════════════════════════════════════════════════════
# Prompt
# ══════════════════════════════════════════════════════════════════════
SYS_PROMPT = """你是一位「台灣台中捷運無線電通訊辨識結果仲裁員」。

任務：給你三個 STT 引擎對同一段音訊的辨識結果，你的工作是產出最佳的「整合版本」。

引擎背景：
- 引擎 A (Gemini 2.5 Pro): 通用大模型，CER 較低但偶有漏字
- 引擎 B (ElevenLabs Scribe): 字數對齊度高，但有時把術語聽成相似音字
- 引擎 C (SenseVoice 本地): 輸出簡體中文，常把英文縮寫聽錯（如把 OCC 聽成「資訊」）

仲裁原則（依優先序）：
1. 多數一致原則：3 個引擎中 2+ 一致的內容極可能正確，採用該段
2. 主力優先：相異段落以引擎 A 為基準，B/C 用來修正 A 的明顯錯字
3. 術語還原：若 B/C 中有清楚的術語（OCC、G05、月台、車組 17/18 等）而 A 漏字，補上
4. 簡繁統一：輸出**繁體中文**（台灣用詞），不留簡體字
5. 不過度修改：當不確定時保留 A 的版本

請直接輸出整合後的文字，不要加任何說明。"""

USER_TEMPLATE = """引擎 A (Gemini 2.5 Pro):
{a}

引擎 B (Scribe):
{b}

引擎 C (SenseVoice):
{c}

請輸出整合後的版本："""


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def load_manifest() -> list[dict]:
    rows = []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("has_gt") == "Y":
                rows.append(row)
    return rows


def load_stt(engine: str, sid: str) -> str | None:
    p = STT_DIR / engine / f"{sid}.txt"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def ensemble_one(client, model: str, a: str, b: str, c: str) -> str:
    """讓 LLM 對三引擎結果做仲裁，回傳整合後文字"""
    user_prompt = USER_TEMPLATE.format(a=a, b=b, c=c)
    resp = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=4096,
            system_instruction=SYS_PROMPT,
        ),
    )
    return (resp.text or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-flash",
                    help="仲裁用 LLM 模型（gemini-2.5-flash / pro）")
    ap.add_argument("--out-label", default="ensemble_v1",
                    help="輸出子目錄名（stt_outputs/{out-label}/）")
    ap.add_argument("--force", action="store_true", help="覆寫已存在輸出")
    args = ap.parse_args()

    out_dir = STT_DIR / args.out_label
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest()
    print(f"🔀 多引擎 Ensemble PoC")
    print(f"   引擎組合：{ENGINES}")
    print(f"   仲裁模型：{args.model}")
    print(f"   輸出目錄：{out_dir.relative_to(PROJECT_ROOT)}")
    print(f"   樣本數：{len(manifest)}")
    print()

    client = get_client()

    success = 0
    skipped = 0
    failed = 0
    total_t = 0.0

    for i, sample in enumerate(manifest, 1):
        sid = sample["id"]
        et = sample["event_type"]
        out_path = out_dir / f"{sid}.txt"

        if out_path.exists() and not args.force:
            print(f"[{i:3}/{len(manifest)}] {sid} ⏭️  cached")
            skipped += 1
            continue

        # 讀三引擎輸出
        a = load_stt("gemini25pro", sid)
        b = load_stt("scribe", sid)
        c = load_stt("sensevoice", sid)
        if a is None or b is None or c is None:
            print(f"[{i:3}/{len(manifest)}] {sid} ❌ STT 來源缺失 (A={a is not None} B={b is not None} C={c is not None})")
            failed += 1
            continue

        t0 = time.time()
        try:
            ensemble = ensemble_one(client, args.model, a.strip(), b.strip(), c.strip())
            elapsed = time.time() - t0
            total_t += elapsed
            out_path.write_text(ensemble, encoding="utf-8")
            success += 1
            print(f"[{i:3}/{len(manifest)}] {sid} ({et:10}) ✅ {len(ensemble):4d}字 / {elapsed:5.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            failed += 1
            print(f"[{i:3}/{len(manifest)}] {sid} ❌ {elapsed:.1f}s err: {str(e)[:120]}")

    print()
    print(f"📊 結果：success={success} / skipped={skipped} / failed={failed}")
    print(f"   總耗時：{total_t:.1f}s（平均 {total_t/max(success,1):.1f}s/段）")
    print(f"   輸出：{out_dir}")


if __name__ == "__main__":
    main()
