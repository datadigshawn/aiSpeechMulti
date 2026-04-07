#!/usr/bin/env python3
"""
Ground Truth 評測腳本
======================

對單一音檔（已有 STT 結果 + 正確文稿）執行 LLM 後修正並計算真實 CER。

流程:
    Ground Truth 文稿  ──┐
                        ├──→ jiwer CER 計算
    STT 原始辨識結果   ──┤
         │              │
         ↓              │
    LLM 後修正  ────────┘
                        └──→ jiwer CER 計算（修正後）

比對「修正前 vs 修正後」的 CER 改善幅度。

用法:
    python3 experiments/llm_correction_poc/eval_groundtruth.py \\
        --gt experiments/Test_TMRT2正確文稿/UltraLog06320251222192724.txt \\
        --transcription-id 2 \\
        --strictness conservative
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "aiSpeechMulti.db"
OUTPUT_DIR = Path(__file__).parent

try:
    import jiwer
except ImportError:
    print("❌ 請先安裝: pip install jiwer")
    sys.exit(1)

try:
    import google.generativeai as genai
except ImportError:
    print("❌ 請先安裝: pip install google-generativeai")
    sys.exit(1)

# 匯入強化版 prompt
from prompt_v2 import build_prompts_v2


# ══════════════════════════════════════════════════════════════════════
# 文本正規化（為了公平比對 CER）
# ══════════════════════════════════════════════════════════════════════
def normalize_for_cer(text: str) -> str:
    """移除影響 CER 計算的雜訊，但保留實質字元"""
    if not text:
        return ""
    # 1. 移除講者標記 【講者X ｜ 時間:時間】
    text = re.sub(r"【[^】]*】", "", text)
    # 2. 移除常見前綴 G:、B:、H:、A: 等講者代號
    text = re.sub(r"^[A-Z]:\s*", "", text, flags=re.MULTILINE)
    # 3. 移除標點與空白
    text = re.sub(r"[\s,，。.、:：;；!?！？\-—()（）\"'\"" "]+", "", text)
    # 4. 簡繁統一（用 opencc 將兩邊都轉繁體再比對）
    try:
        from opencc import OpenCC

        cc = OpenCC("s2twp")
        text = cc.convert(text)
    except Exception:
        pass
    return text


def load_ground_truth(path: Path) -> str:
    """載入 ground truth 並合併為單一字串"""
    raw = path.read_text(encoding="utf-8")
    return raw


def fetch_transcription(tid: int) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, transcript FROM transcriptions WHERE id = ?", (tid,)
    ).fetchone()
    conn.close()
    if not row:
        raise ValueError(f"找不到 transcription id={tid}")
    return dict(row)


def load_stt_source(args) -> tuple[str, str]:
    """根據參數從 DB 或檔案載入 STT 結果。回傳 (text, source_label)"""
    if args.stt_file:
        path = Path(args.stt_file)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            raise FileNotFoundError(f"STT 檔案不存在: {path}")
        return path.read_text(encoding="utf-8"), path.name
    elif args.transcription_id:
        rec = fetch_transcription(args.transcription_id)
        return rec["transcript"], f"db:id={args.transcription_id}"
    else:
        raise ValueError("必須指定 --stt-file 或 --transcription-id")


# ══════════════════════════════════════════════════════════════════════
# Gemini 呼叫
# ══════════════════════════════════════════════════════════════════════
def get_api_key() -> str:
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
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("找不到 GEMINI_API_KEY")


def call_gemini_correct(model_name: str, text: str, strictness: str) -> dict:
    sys_p, user_p = build_prompts_v2(text, strictness)
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=sys_p,
        generation_config={
            "temperature": 0.0,
            "response_mime_type": "application/json",
        },
    )
    resp = model.generate_content(user_p)
    raw = resp.text.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    return json.loads(raw)


# ══════════════════════════════════════════════════════════════════════
# CER 計算
# ══════════════════════════════════════════════════════════════════════
def compute_cer(reference: str, hypothesis: str) -> dict:
    """計算 CER 並回傳詳細指標"""
    ref_norm = normalize_for_cer(reference)
    hyp_norm = normalize_for_cer(hypothesis)
    if not ref_norm:
        return {"cer": 0.0, "ref_len": 0, "hyp_len": len(hyp_norm)}
    cer = jiwer.cer(ref_norm, hyp_norm)
    return {
        "cer": round(cer, 4),
        "ref_len": len(ref_norm),
        "hyp_len": len(hyp_norm),
        "ref_normalized": ref_norm[:200],
        "hyp_normalized": hyp_norm[:200],
    }


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def run_eval(args):
    print("🔬 Ground Truth 評測啟動")
    print(f"   GT 檔案:    {args.gt}")
    print(f"   STT 來源:   {args.stt_file or f'db:id={args.transcription_id}'}")
    print(f"   修正模型:   {args.model}")
    print(f"   修正強度:   {args.strictness}")
    print()

    # 1. API key
    try:
        genai.configure(api_key=get_api_key())
    except Exception as e:
        print(f"❌ {e}")
        return

    # 2. 載入資料
    gt_path = Path(args.gt)
    if not gt_path.is_absolute():
        gt_path = PROJECT_ROOT / gt_path
    if not gt_path.exists():
        print(f"❌ Ground truth 檔案不存在: {gt_path}")
        return
    ground_truth = load_ground_truth(gt_path)
    print(f"📄 Ground truth: {len(ground_truth)} 字")

    try:
        original_stt, stt_source = load_stt_source(args)
    except (ValueError, FileNotFoundError) as e:
        print(f"❌ {e}")
        return
    print(f"📄 STT 原文:     {len(original_stt)} 字 (來源: {stt_source})")

    # 3. 計算修正前 CER
    print("\n[1/3] 計算修正前 CER...")
    cer_before = compute_cer(ground_truth, original_stt)
    print(f"      CER (修正前) = {cer_before['cer']:.4f} ({cer_before['cer']*100:.2f}%)")
    print(f"      正規化後長度 — GT: {cer_before['ref_len']} / STT: {cer_before['hyp_len']}")

    # 4. LLM 修正
    print("\n[2/3] 執行 LLM 後修正...")
    t0 = time.time()
    try:
        result = call_gemini_correct(args.model, original_stt, args.strictness)
        corrected = result.get("corrected", original_stt)
        changes = result.get("changes", [])
        uncertain = result.get("uncertain_kept", [])
        confidence = result.get("confidence", None)
    except Exception as e:
        print(f"❌ LLM 呼叫失敗: {e}")
        return
    elapsed = round(time.time() - t0, 2)
    print(f"      耗時: {elapsed}s | 修正: {len(changes)} 處 | 信心: {confidence}")

    # 5. 計算修正後 CER
    print("\n[3/3] 計算修正後 CER...")
    cer_after = compute_cer(ground_truth, corrected)
    print(f"      CER (修正後) = {cer_after['cer']:.4f} ({cer_after['cer']*100:.2f}%)")

    # 6. 改善幅度
    delta = cer_before["cer"] - cer_after["cer"]
    delta_pct = (delta / cer_before["cer"] * 100) if cer_before["cer"] > 0 else 0

    print()
    print("═" * 60)
    print(f"📊 評測結果")
    print("═" * 60)
    print(f"   CER 修正前:  {cer_before['cer']*100:6.2f}%")
    print(f"   CER 修正後:  {cer_after['cer']*100:6.2f}%")
    print(f"   絕對改善:    {delta*100:+6.2f}%")
    print(f"   相對改善:    {delta_pct:+6.2f}%")
    print(f"   修正項目:    {len(changes)} 處")
    print(f"   保留疑問:    {len(uncertain)} 處")
    print(f"   API 耗時:    {elapsed}s")

    # 7. 寫出報告
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"_{args.label}" if args.label else ""
    json_path = OUTPUT_DIR / f"eval_gt_{ts}{suffix}.json"
    md_path = OUTPUT_DIR / f"eval_gt_{ts}{suffix}.md"

    payload = {
        "meta": {
            "timestamp": ts,
            "gt_file": str(gt_path),
            "transcription_id": args.transcription_id,
            "model": args.model,
            "strictness": args.strictness,
            "elapsed_sec": elapsed,
        },
        "metrics": {
            "cer_before": cer_before["cer"],
            "cer_after": cer_after["cer"],
            "absolute_improvement": round(delta, 4),
            "relative_improvement_pct": round(delta_pct, 2),
            "ref_len": cer_before["ref_len"],
            "hyp_len_before": cer_before["hyp_len"],
            "hyp_len_after": cer_after["hyp_len"],
        },
        "ground_truth": ground_truth,
        "stt_original": original_stt,
        "llm_corrected": corrected,
        "changes": changes,
        "uncertain_kept": uncertain,
        "confidence": confidence,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        f"# Ground Truth 評測結果",
        f"",
        f"- **時間**: {ts}",
        f"- **GT 檔案**: `{gt_path.name}`",
        f"- **STT id**: {args.transcription_id}",
        f"- **模型**: `{args.model}`",
        f"- **強度**: `{args.strictness}`",
        f"",
        f"## 📊 CER 對比",
        f"",
        f"| 指標 | 修正前 | 修正後 | 改善 |",
        f"|---|---|---|---|",
        f"| CER | **{cer_before['cer']*100:.2f}%** | **{cer_after['cer']*100:.2f}%** | **{delta*100:+.2f}% ({delta_pct:+.1f}%)** |",
        f"| 文字長度 | {cer_before['hyp_len']} | {cer_after['hyp_len']} | — |",
        f"",
        f"- Ground truth 正規化長度: {cer_before['ref_len']}",
        f"- LLM 信心度: {confidence}",
        f"- API 耗時: {elapsed}s",
        f"- 修正項目數: {len(changes)}",
        f"- 保留疑問詞: {len(uncertain)}",
        f"",
        f"## 📄 Ground Truth",
        f"",
        f"```",
        ground_truth.strip(),
        f"```",
        f"",
        f"## 📄 STT 原始辨識",
        f"",
        f"```",
        original_stt.strip(),
        f"```",
        f"",
        f"## ✨ LLM 修正後",
        f"",
        f"```",
        corrected.strip(),
        f"```",
        f"",
        f"## 🔧 修正項目（共 {len(changes)} 處）",
        f"",
    ]
    if changes:
        md.append("| # | 原 | → | 修正 | 類別 |")
        md.append("|---|---|---|---|---|")
        for i, c in enumerate(changes, 1):
            md.append(
                f"| {i} | `{c.get('from','')}` | → | `{c.get('to','')}` | {c.get('type','')} |"
            )
    else:
        md.append("（無）")

    if uncertain:
        md += [f"", f"## ⚠️ 保留但可能有問題的詞", ""]
        for u in uncertain:
            md.append(f"- {u}")

    md_path.write_text("\n".join(md), encoding="utf-8")

    print()
    print(f"📄 JSON: {json_path}")
    print(f"📄 報告: {md_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gt", required=True, help="Ground truth 文稿路徑")
    p.add_argument(
        "--transcription-id",
        type=int,
        default=None,
        help="DB 中對應的 transcriptions.id（與 --stt-file 擇一）",
    )
    p.add_argument(
        "--stt-file",
        default=None,
        help="STT 結果的純文字檔案路徑（與 --transcription-id 擇一）",
    )
    p.add_argument(
        "--label",
        default=None,
        help="此次評測的標籤（用於報告檔名，例如 chirp3 / gemini-3.1-pro）",
    )
    p.add_argument("--model", default="gemini-2.5-flash")
    p.add_argument(
        "--strictness",
        default="conservative",
        choices=["strict", "conservative", "balanced"],
    )
    args = p.parse_args()
    run_eval(args)


if __name__ == "__main__":
    main()
