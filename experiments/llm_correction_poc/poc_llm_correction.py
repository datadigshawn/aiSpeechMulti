#!/usr/bin/env python3
"""
LLM 後修正層 PoC 腳本
====================

從 aiSpeechMulti.db 抽取歷史辨識結果，使用 Gemini 進行後修正，
並輸出 diff 對照與簡易 CER 評估。

用法:
    python3 experiments/llm_correction_poc/poc_llm_correction.py \
        --limit 10 \
        --strictness conservative \
        --model gemini-2.5-flash

輸出:
    experiments/llm_correction_poc/results_<timestamp>.json
    experiments/llm_correction_poc/results_<timestamp>.md   (人類可讀)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

# ── 路徑設定 ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "aiSpeechMulti.db"
VOCAB_PATH = PROJECT_ROOT / "vocabulary" / "master_vocabulary.csv"
OUTPUT_DIR = Path(__file__).parent

# ── Gemini SDK（新版 google-genai）──────────────────────────────────────
try:
    from utils.gemini_client import get_client, genai_types
except ImportError:
    print("❌ 請先安裝: pip install google-genai")
    sys.exit(1)

# 模組層 client，由 run_poc() 初始化
_GEMINI_CLIENT = None


# ══════════════════════════════════════════════════════════════════════
# 資料結構
# ══════════════════════════════════════════════════════════════════════
@dataclass
class CorrectionResult:
    transcription_id: int
    original: str
    corrected: str
    changes: list[dict]
    char_diff: int
    cer_vs_original: float
    elapsed_sec: float
    model: str
    strictness: str
    error: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════
# 詞彙表載入
# ══════════════════════════════════════════════════════════════════════
def load_vocabulary(path: Path, max_terms: int = 60) -> list[str]:
    """從 master_vocabulary.csv 抽出高權重術語"""
    if not path.exists():
        print(f"⚠️  詞彙表不存在: {path}")
        return []
    terms = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = (row.get("term") or "").strip()
            if not term or term.startswith("#"):
                continue
            try:
                boost = float(row.get("boost_value") or 0)
            except ValueError:
                boost = 0
            terms.append((term, boost))
    terms.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in terms[:max_terms]]


# ══════════════════════════════════════════════════════════════════════
# 從 DB 抽樣
# ══════════════════════════════════════════════════════════════════════
def fetch_samples(db_path: Path, limit: int) -> list[dict]:
    """從 transcriptions 表抽出範例（含長度過濾，避免太短或過長）"""
    if not db_path.exists():
        print(f"❌ DB 不存在: {db_path}")
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 過濾長度 30-300 字之間的有意義段落
    cur.execute(
        """
        SELECT id, transcript
        FROM transcriptions
        WHERE length(transcript) BETWEEN 30 AND 300
          AND transcript IS NOT NULL
          AND status = 'success'
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ══════════════════════════════════════════════════════════════════════
# Prompt 設計
# ══════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT_TEMPLATE = """你是台中捷運（TMRT）行控中心無線電通訊文字校正專家。

任務：修正語音辨識結果中的明顯錯字，特別是同音字、術語誤辨、簡繁混雜。

【修正原則 - 嚴格遵守】
1. 保留口語特徵（包含「好」「收到」「over」等通訊用語）
2. 不要重寫句子，只修正字詞
3. 不要新增、刪除或翻譯任何內容
4. 不確定時保留原文
5. 將簡體字轉為繁體字（台灣用法）
6. 軍事數字讀法保留（洞=0、么=1、兩=2、拐=7、勾=9）

【修正強度: {strictness}】
- conservative: 只改 95% 確定的錯字（同音字、明顯術語誤辨）
- balanced: 改錯字 + 標點補全
- aggressive: 改錯字 + 標點 + 簡單語法修正

【參考詞彙表】
{vocab_block}

【常見誤辨範例】
- 越台門 → 月台門
- 歐西/哦西/現電力一場 → OCC
- 拘止繩 → 警戒繩
- 輔電/鋪電 → 復電
- 待行軌 → 待避軌
- 站前 → 站間 (依上下文)

【輸出格式】嚴格的 JSON（不要有任何 markdown、不要有 ```json）：
{{
  "corrected": "修正後的全文",
  "changes": [
    {{"from": "越台", "to": "月台", "reason": "同音字"}},
    ...
  ],
  "confidence": 0.95
}}
"""

USER_PROMPT_TEMPLATE = """請修正以下無線電辨識結果：

【原文】
{text}

請輸出 JSON。"""


def build_prompts(text: str, vocabulary: list[str], strictness: str) -> tuple[str, str]:
    vocab_block = "、".join(vocabulary) if vocabulary else "（無）"
    sys_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        strictness=strictness, vocab_block=vocab_block
    )
    user_prompt = USER_PROMPT_TEMPLATE.format(text=text)
    return sys_prompt, user_prompt


# ══════════════════════════════════════════════════════════════════════
# Gemini API 呼叫
# ══════════════════════════════════════════════════════════════════════
def get_api_key() -> str:
    # 優先讀環境變數，再讀 utils/api_keys.json
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    json_path = PROJECT_ROOT / "utils" / "api_keys.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            for k in ("gemini_api_key", "GEMINI_API_KEY", "google_api_key"):
                if data.get(k):
                    return data[k]
        except Exception:
            pass
    # 嘗試 .env
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("找不到 GEMINI_API_KEY，請設定環境變數或 utils/api_keys.json")


def call_gemini(
    model_name: str,
    sys_prompt: str,
    user_prompt: str,
) -> dict:
    resp = _GEMINI_CLIENT.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            system_instruction=sys_prompt,
        ),
    )
    text = (resp.text or "").strip()
    # 移除可能的 markdown fence
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    return json.loads(text)


# ══════════════════════════════════════════════════════════════════════
# 評估指標
# ══════════════════════════════════════════════════════════════════════
def char_cer(a: str, b: str) -> float:
    """簡易字元錯誤率（無 reference 時用 a 為基準）"""
    if not a:
        return 0.0
    sm = SequenceMatcher(None, a, b)
    similar = sum(blk.size for blk in sm.get_matching_blocks())
    return round(1 - similar / max(len(a), 1), 4)


def char_diff_count(a: str, b: str) -> int:
    sm = SequenceMatcher(None, a, b)
    diffs = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            diffs += max(i2 - i1, j2 - j1)
    return diffs


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def run_poc(args):
    print(f"🔧 LLM 後修正 PoC 啟動")
    print(f"   模型: {args.model}")
    print(f"   強度: {args.strictness}")
    print(f"   樣本: {args.limit}")
    print(f"   DB:   {DB_PATH}")
    print()

    # 1. 載入 API key + 建立 client
    global _GEMINI_CLIENT
    try:
        _GEMINI_CLIENT = get_client(get_api_key())
    except Exception as e:
        print(f"❌ {e}")
        return

    # 2. 載入詞彙表
    vocab = load_vocabulary(VOCAB_PATH, max_terms=args.vocab_size)
    print(f"📚 載入詞彙: {len(vocab)} 條（取 boost 最高的前 {args.vocab_size} 條）")

    # 3. 抽樣
    samples = fetch_samples(DB_PATH, args.limit)
    if not samples:
        print("❌ DB 中找不到合適樣本")
        return
    print(f"📊 抽樣完成: {len(samples)} 筆\n")

    # 4. 逐筆修正
    results: list[CorrectionResult] = []
    for i, sample in enumerate(samples, 1):
        tid = sample["id"]
        original = sample["transcript"]
        print(f"[{i}/{len(samples)}] id={tid} ({len(original)} 字) ... ", end="", flush=True)

        sys_p, user_p = build_prompts(original, vocab, args.strictness)
        t0 = time.time()
        try:
            data = call_gemini(args.model, sys_p, user_p)
            corrected = data.get("corrected", original)
            changes = data.get("changes", [])
            err = None
        except Exception as e:
            corrected = original
            changes = []
            err = str(e)[:200]
        elapsed = round(time.time() - t0, 2)

        result = CorrectionResult(
            transcription_id=tid,
            original=original,
            corrected=corrected,
            changes=changes,
            char_diff=char_diff_count(original, corrected),
            cer_vs_original=char_cer(original, corrected),
            elapsed_sec=elapsed,
            model=args.model,
            strictness=args.strictness,
            error=err,
        )
        results.append(result)

        if err:
            print(f"❌ {err[:60]}")
        else:
            print(f"✅ {len(changes)} 處修正 / {elapsed}s")

    # 5. 寫出結果
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUTPUT_DIR / f"results_{ts}.json"
    md_path = OUTPUT_DIR / f"results_{ts}.md"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path.write_text(
        json.dumps(
            {
                "meta": {
                    "model": args.model,
                    "strictness": args.strictness,
                    "vocab_size": len(vocab),
                    "sample_count": len(results),
                    "timestamp": ts,
                },
                "results": [asdict(r) for r in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Markdown 報告
    md_lines = [
        f"# LLM 後修正 PoC 結果\n",
        f"- **時間**: {ts}",
        f"- **模型**: `{args.model}`",
        f"- **強度**: `{args.strictness}`",
        f"- **詞彙**: {len(vocab)} 條",
        f"- **樣本**: {len(results)} 筆\n",
        "## 統計摘要\n",
    ]
    success = [r for r in results if r.error is None]
    total_changes = sum(len(r.changes) for r in success)
    total_diff = sum(r.char_diff for r in success)
    avg_time = sum(r.elapsed_sec for r in success) / max(len(success), 1)
    md_lines += [
        f"- 成功率: {len(success)}/{len(results)}",
        f"- 總修正次數: {total_changes}",
        f"- 總字元變動: {total_diff}",
        f"- 平均耗時: {avg_time:.2f}s / 句\n",
        "## 逐筆對照\n",
    ]
    for i, r in enumerate(results, 1):
        md_lines += [
            f"### #{i} (id={r.transcription_id})",
            f"- **耗時**: {r.elapsed_sec}s | **修正**: {len(r.changes)} 處 | **字元變動**: {r.char_diff} | **CER vs 原**: {r.cer_vs_original}",
        ]
        if r.error:
            md_lines.append(f"- ❌ **錯誤**: {r.error}")
        md_lines += [
            f"",
            f"**原文**:",
            f"> {r.original}",
            f"",
            f"**修正後**:",
            f"> {r.corrected}",
            f"",
        ]
        if r.changes:
            md_lines.append(f"**修正項目**:")
            for c in r.changes:
                md_lines.append(
                    f"- `{c.get('from','')}` → `{c.get('to','')}` ({c.get('reason','')})"
                )
            md_lines.append("")
        md_lines.append("---\n")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    # 6. Console 摘要
    print()
    print("═" * 60)
    print(f"✅ 完成 — 成功 {len(success)}/{len(results)}")
    print(f"   總修正次數: {total_changes}")
    print(f"   總字元變動: {total_diff}")
    print(f"   平均耗時:   {avg_time:.2f}s/句")
    print(f"📄 JSON: {json_path}")
    print(f"📄 報告: {md_path}")


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser(description="LLM 後修正層 PoC")
    p.add_argument("--limit", type=int, default=10, help="抽樣筆數（預設 10）")
    p.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Gemini 模型名稱（預設 gemini-2.5-flash）",
    )
    p.add_argument(
        "--strictness",
        default="conservative",
        choices=["conservative", "balanced", "aggressive"],
        help="修正強度",
    )
    p.add_argument("--vocab-size", type=int, default=60, help="載入詞彙條數")
    args = p.parse_args()
    run_poc(args)


if __name__ == "__main__":
    main()
