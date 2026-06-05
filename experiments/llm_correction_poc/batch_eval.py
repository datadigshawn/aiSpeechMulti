#!/usr/bin/env python3
"""
黃金語料集批次評測腳本
======================

讀取 manifest.csv，對每段音檔/GT 對跑指定引擎的辨識並計算 CER，
產出統計報表（依事件類型分組 + 跨樣本平均）。

特性：
- 支援多引擎並列比較
- 支援後處理 pipeline 開關（car_norm / dict / LLM）
- 依事件類型分組統計
- 輸出 JSON + Markdown 報告
- 支援「STT 重跑」與「STT 結果快取」兩種模式

用法：
    # 用既有 STT 結果（從 stt_inputs/ 讀），不重跑 STT
    python3 experiments/llm_correction_poc/batch_eval.py \\
        --manifest experiments/golden_dataset/manifest.csv \\
        --stt-cache-dir experiments/golden_dataset/stt_outputs/chirp3 \\
        --engine-label chirp3

    # 啟用後處理 pipeline
    python3 experiments/llm_correction_poc/batch_eval.py \\
        --manifest experiments/golden_dataset/manifest.csv \\
        --stt-cache-dir experiments/golden_dataset/stt_outputs/chirp3 \\
        --engine-label chirp3 \\
        --post-process car_norm,dict

    # 啟用 LLM 後修正
    python3 experiments/llm_correction_poc/batch_eval.py \\
        --manifest experiments/golden_dataset/manifest.csv \\
        --stt-cache-dir experiments/golden_dataset/stt_outputs/chirp3 \\
        --engine-label chirp3 \\
        --post-process car_norm,dict,llm

注意：
- 此腳本不重跑 STT（避免 API 成本與不確定性）
- 請先用 dashboard 或其他工具產出 STT 結果，存到 stt_cache_dir
- 檔名規則：{golden_id}.txt （例如 001.txt 對應 manifest 中 id=001 的樣本）
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = Path(__file__).parent

try:
    import jiwer
except ImportError:
    print("❌ 請先安裝: pip install jiwer")
    sys.exit(1)

try:
    from opencc import OpenCC
    _CC = OpenCC("s2twp")
except Exception:
    _CC = None

from scripts.post_process import post_process


# ══════════════════════════════════════════════════════════════════════
# 文本正規化（CER 用）
# ══════════════════════════════════════════════════════════════════════
def normalize_for_cer(text: str) -> str:
    """移除影響 CER 計算的雜訊，但保留實質字元"""
    if not text:
        return ""
    # 移除 GT 講者標記 [B:] [H:] [G:] [T:] [?:]
    text = re.sub(r"^[A-Z?]:\s*", "", text, flags=re.MULTILINE)
    # 移除 GT 標註 [?] [noise] [unclear]
    text = re.sub(r"\[[^\]]*\]", "", text)
    # 移除 STT 講者標記 【講者X | 時間】
    text = re.sub(r"【[^】]*】", "", text)
    # 移除標點符號與空白
    text = re.sub(r"[\s,，。.、:：;；!?！？\-—()（）\"'\u201c\u201d]+", "", text)
    # 簡繁統一
    if _CC:
        try:
            text = _CC.convert(text)
        except Exception:
            pass
    return text


def compute_cer(reference: str, hypothesis: str) -> float:
    ref = normalize_for_cer(reference)
    hyp = normalize_for_cer(hypothesis)
    if not ref:
        return 0.0
    return jiwer.cer(ref, hyp)


def compute_wer_per_word(reference: str, hypothesis: str) -> float:
    """計算 WER（用 jieba 分詞，若無則退化為字元級）"""
    ref = normalize_for_cer(reference)
    hyp = normalize_for_cer(hypothesis)
    if not ref:
        return 0.0
    try:
        import jieba
        ref_words = list(jieba.cut(ref))
        hyp_words = list(jieba.cut(hyp))
        return jiwer.wer(" ".join(ref_words), " ".join(hyp_words))
    except ImportError:
        return jiwer.cer(ref, hyp)  # fallback


# ══════════════════════════════════════════════════════════════════════
# 資料結構
# ══════════════════════════════════════════════════════════════════════
@dataclass
class SampleResult:
    id: str
    event_type: str
    audio_file: str
    gt_chars: int
    stt_chars: int
    final_chars: int
    cer_raw: float          # 原始 STT vs GT
    cer_final: float        # 後處理後 vs GT
    cer_improvement: float  # cer_raw - cer_final
    wer_final: float
    pp_changes: dict        # 各階段修正項目數
    elapsed_sec: float
    error: Optional[str] = None


@dataclass
class BatchReport:
    timestamp: str
    engine_label: str
    post_process_stages: list[str]
    sample_count: int
    success_count: int
    avg_cer_raw: float
    avg_cer_final: float
    avg_improvement: float
    avg_wer_final: float
    by_event_type: dict        # event_type → {count, avg_cer, ...}
    samples: list[dict] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
# Manifest 載入
# ══════════════════════════════════════════════════════════════════════
def load_manifest(path: Path) -> list[dict]:
    if not path.exists():
        print(f"❌ Manifest 不存在: {path}")
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("has_gt") == "Y":
                rows.append(row)
    return rows


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def run_batch(args):
    print(f"🔬 黃金語料集批次評測")
    print(f"   manifest:    {args.manifest}")
    print(f"   STT cache:   {args.stt_cache_dir}")
    print(f"   engine:      {args.engine_label}")
    pp_stages = [s.strip() for s in args.post_process.split(",") if s.strip()]
    print(f"   post-process: {pp_stages or '（無）'}")
    print()

    manifest = load_manifest(Path(args.manifest))
    if not manifest:
        print("❌ Manifest 為空或不存在")
        return
    print(f"📋 共 {len(manifest)} 筆已標註 GT 的樣本")
    print()

    cache_dir = Path(args.stt_cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = PROJECT_ROOT / cache_dir
    if not cache_dir.exists():
        print(f"❌ STT cache 目錄不存在: {cache_dir}")
        print(f"   請先用 dashboard 或其他工具產出 STT 結果並放到此目錄")
        print(f"   檔名規則：{{id}}.txt（例如 001.txt 對應 manifest id=001）")
        return

    enable_car  = "car_norm" in pp_stages
    enable_dict = "dict" in pp_stages
    enable_llm  = "llm" in pp_stages

    results: list[SampleResult] = []
    for i, sample in enumerate(manifest, 1):
        sid = sample["id"]
        event_type = sample["event_type"]
        gt_path = PROJECT_ROOT / sample["gt_file"]
        stt_path = cache_dir / f"{sid}.txt"

        print(f"[{i:3}/{len(manifest)}] {sid} ({event_type:10}) ", end="", flush=True)

        if not gt_path.exists():
            print(f"❌ GT not found")
            continue
        if not stt_path.exists():
            print(f"⏭️  STT cache 不存在: {stt_path.name}")
            results.append(SampleResult(
                id=sid, event_type=event_type,
                audio_file=sample["audio_file"],
                gt_chars=0, stt_chars=0, final_chars=0,
                cer_raw=0, cer_final=0, cer_improvement=0, wer_final=0,
                pp_changes={}, elapsed_sec=0,
                error="STT cache not found",
            ))
            continue

        gt = gt_path.read_text(encoding="utf-8")
        stt_raw = stt_path.read_text(encoding="utf-8")

        # 套用後處理
        try:
            final, report = post_process(
                stt_raw,
                enable_car_norm=enable_car,
                enable_dict=enable_dict,
                enable_llm=enable_llm,
                enable_number_norm=not args.no_number_norm,
                llm_model=args.llm_model,
                llm_strictness=args.llm_strictness,
                engine_hint=args.engine_label,
                auto_skip_llm_for_high_quality=False,  # 評測時強制執行
            )
        except Exception as e:
            print(f"❌ post_process error: {e}")
            results.append(SampleResult(
                id=sid, event_type=event_type,
                audio_file=sample["audio_file"],
                gt_chars=len(normalize_for_cer(gt)),
                stt_chars=len(normalize_for_cer(stt_raw)),
                final_chars=0,
                cer_raw=0, cer_final=0, cer_improvement=0, wer_final=0,
                pp_changes={}, elapsed_sec=0,
                error=str(e)[:200],
            ))
            continue

        cer_raw   = compute_cer(gt, stt_raw)
        cer_final = compute_cer(gt, final)
        wer_final = compute_wer_per_word(gt, final)

        pp_changes = {
            s["name"]: s["change_count"]
            for s in report["stages"] if s.get("change_count", 0) > 0
        }

        result = SampleResult(
            id=sid,
            event_type=event_type,
            audio_file=sample["audio_file"],
            gt_chars=len(normalize_for_cer(gt)),
            stt_chars=len(normalize_for_cer(stt_raw)),
            final_chars=len(normalize_for_cer(final)),
            cer_raw=round(cer_raw, 4),
            cer_final=round(cer_final, 4),
            cer_improvement=round(cer_raw - cer_final, 4),
            wer_final=round(wer_final, 4),
            pp_changes=pp_changes,
            elapsed_sec=report["elapsed_sec"],
        )
        results.append(result)
        delta = cer_raw - cer_final
        marker = "↓" if delta > 0 else ("↑" if delta < 0 else "—")
        print(f"CER {cer_raw*100:5.2f}% → {cer_final*100:5.2f}% ({delta*100:+5.2f}% {marker})")

    # ── 統計 ──────────────────────────────────────────────────────
    success = [r for r in results if not r.error]
    if not success:
        print("\n❌ 無成功樣本可統計")
        return

    avg_cer_raw   = sum(r.cer_raw for r in success) / len(success)
    avg_cer_final = sum(r.cer_final for r in success) / len(success)
    avg_improve   = sum(r.cer_improvement for r in success) / len(success)
    avg_wer       = sum(r.wer_final for r in success) / len(success)

    # 依事件類型分組
    by_type: dict[str, dict] = {}
    for r in success:
        et = r.event_type
        if et not in by_type:
            by_type[et] = {"count": 0, "cer_raw": 0, "cer_final": 0, "improve": 0}
        by_type[et]["count"] += 1
        by_type[et]["cer_raw"] += r.cer_raw
        by_type[et]["cer_final"] += r.cer_final
        by_type[et]["improve"] += r.cer_improvement
    for et, d in by_type.items():
        n = d["count"]
        d["avg_cer_raw"]   = round(d["cer_raw"] / n, 4)
        d["avg_cer_final"] = round(d["cer_final"] / n, 4)
        d["avg_improve"]   = round(d["improve"] / n, 4)

    # ── Console 報告 ──────────────────────────────────────────────
    print()
    print("═" * 70)
    print(f"📊 批次評測結果（{args.engine_label}）")
    print("═" * 70)
    print(f"   成功:        {len(success)}/{len(results)}")
    print(f"   平均 CER raw:    {avg_cer_raw*100:6.2f}%")
    print(f"   平均 CER final:  {avg_cer_final*100:6.2f}%")
    print(f"   平均改善:        {avg_improve*100:+6.2f}%")
    print(f"   平均 WER final:  {avg_wer*100:6.2f}%")
    print()
    print(f"   ── 依事件類型分組 ──")
    for et in sorted(by_type.keys()):
        d = by_type[et]
        print(f"   {et:12} (n={d['count']:2})  CER {d['avg_cer_raw']*100:5.2f}% → {d['avg_cer_final']*100:5.2f}%  ({d['avg_improve']*100:+.2f}%)")

    # ── 寫出 JSON + Markdown ──────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    label_safe = re.sub(r"[^\w-]", "_", args.engine_label)
    pp_safe = "+".join(pp_stages) if pp_stages else "raw"
    json_path = OUTPUT_DIR / f"batch_eval_{ts}_{label_safe}_{pp_safe}.json"
    md_path = OUTPUT_DIR / f"batch_eval_{ts}_{label_safe}_{pp_safe}.md"

    report_obj = BatchReport(
        timestamp=ts,
        engine_label=args.engine_label,
        post_process_stages=pp_stages,
        sample_count=len(results),
        success_count=len(success),
        avg_cer_raw=round(avg_cer_raw, 4),
        avg_cer_final=round(avg_cer_final, 4),
        avg_improvement=round(avg_improve, 4),
        avg_wer_final=round(avg_wer, 4),
        by_event_type=by_type,
        samples=[asdict(r) for r in results],
    )

    json_path.write_text(json.dumps(asdict(report_obj), ensure_ascii=False, indent=2),
                         encoding="utf-8")

    md = [
        f"# 黃金語料集批次評測報告",
        f"",
        f"- **時間**: {ts}",
        f"- **引擎**: `{args.engine_label}`",
        f"- **後處理**: {pp_stages or '（無）'}",
        f"- **樣本**: {len(success)}/{len(results)} 成功",
        f"",
        f"## 📊 平均指標",
        f"",
        f"| 指標 | 數值 |",
        f"|---|---|",
        f"| 平均 CER (raw)   | **{avg_cer_raw*100:.2f}%** |",
        f"| 平均 CER (final) | **{avg_cer_final*100:.2f}%** |",
        f"| 平均改善         | **{avg_improve*100:+.2f}%** |",
        f"| 平均 WER (final) | {avg_wer*100:.2f}% |",
        f"",
        f"## 📂 依事件類型分組",
        f"",
        f"| 事件類型 | 段數 | CER raw | CER final | 改善 |",
        f"|---|---|---|---|---|",
    ]
    for et in sorted(by_type.keys()):
        d = by_type[et]
        md.append(
            f"| {et} | {d['count']} | "
            f"{d['avg_cer_raw']*100:.2f}% | "
            f"{d['avg_cer_final']*100:.2f}% | "
            f"{d['avg_improve']*100:+.2f}% |"
        )

    md += [f"", f"## 📋 各樣本詳細", f"",
           f"| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |",
           f"|---|---|---|---|---|---|"]
    for r in results:
        if r.error:
            md.append(f"| {r.id} | {r.event_type} | — | — | — | ❌ {r.error[:50]} |")
        else:
            stages_str = ", ".join(f"{k}={v}" for k, v in r.pp_changes.items()) or "—"
            md.append(
                f"| {r.id} | {r.event_type} | "
                f"{r.cer_raw*100:.2f}% | {r.cer_final*100:.2f}% | "
                f"{r.cer_improvement*100:+.2f}% | {stages_str} |"
            )

    md_path.write_text("\n".join(md), encoding="utf-8")

    # 自動 append 到 cer_history.csv + cer_event_type_history.csv（趨勢看板用）
    try:
        from scripts.build_cer_index import (
            CERRow, CEREventTypeRow,
            append_row, append_event_type_rows, _ts_to_iso,
        )
        pp_label = "+".join(pp_stages) if pp_stages else "raw"
        append_row(CERRow(
            timestamp=       ts,
            timestamp_iso=   _ts_to_iso(ts),
            engine_label=    args.engine_label,
            post_process=    pp_label,
            sample_count=    len(results),
            success_count=   len(success),
            avg_cer_raw=     round(avg_cer_raw, 4),
            avg_cer_final=   round(avg_cer_final, 4),
            avg_improvement= round(avg_improve, 4),
            avg_wer_final=   round(avg_wer, 4),
            source_json=     json_path.name,
        ))
        # 事件類型分組（每事件一筆）
        et_rows = []
        for et, m in by_type.items():
            et_rows.append(CEREventTypeRow(
                timestamp=       ts,
                timestamp_iso=   _ts_to_iso(ts),
                engine_label=    args.engine_label,
                post_process=    pp_label,
                event_type=      et,
                count=           int(m.get("count", 0)),
                avg_cer_raw=     round(float(m.get("avg_cer_raw", 0)), 4),
                avg_cer_final=   round(float(m.get("avg_cer_final", 0)), 4),
                avg_improvement= round(float(m.get("avg_improve", 0)), 4),
                source_json=     json_path.name,
            ))
        append_event_type_rows(et_rows)
    except Exception as _ce:
        print(f"⚠️ append cer_history.csv 失敗: {_ce}")

    print()
    print(f"📄 JSON: {json_path}")
    print(f"📄 報告: {md_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True, help="manifest.csv 路徑")
    p.add_argument("--stt-cache-dir", required=True,
                   help="STT 結果快取目錄（檔名：{id}.txt）")
    p.add_argument("--engine-label", required=True,
                   help="引擎標籤（用於報告，例如 chirp3 / gemini31pro）")
    p.add_argument("--post-process", default="",
                   help="逗號分隔的後處理階段：car_norm,dict,llm")
    p.add_argument("--llm-model", default="gemini-2.5-flash")
    p.add_argument("--llm-strictness", default="conservative",
                   choices=["strict", "conservative", "balanced"])
    p.add_argument("--no-number-norm", action="store_true",
                   help="關閉 number_norm（A1 量測用；預設仍開以維持既有行為）")
    args = p.parse_args()
    run_batch(args)


if __name__ == "__main__":
    main()
