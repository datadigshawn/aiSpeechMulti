#!/usr/bin/env python3
"""
Whisper vs Google STT 批次比對測試
====================================
目的：驗證 Whisper large-v3 與 Google STT chirp_3 的「錯誤互補性」

使用方式：
    # 完整比對（兩個引擎都跑）
    python scripts/whisper_vs_google_batch.py

    # 只跑 Whisper（不耗 Google API 費用）
    python scripts/whisper_vs_google_batch.py --skip-google

    # 只跑 Google STT
    python scripts/whisper_vs_google_batch.py --skip-whisper

    # 指定資料夾與模型
    python scripts/whisper_vs_google_batch.py --dataset experiments/61003 --model turbo

輸出：
    experiments/61001/
    ├── asr_output/
    │   ├── whisper/    ← 每個 wav 對應的 Whisper 辨識結果 .txt
    │   └── google/     ← 每個 wav 對應的 Google STT 辨識結果 .txt
    └── evaluation/
        ├── comparison.csv   ← 逐檔 CER/WER 對比
        └── summary.txt      ← 整體統計 + 互補分析
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 設定 Google 認證（必須在 import google client 之前）
_key_path = PROJECT_ROOT / "utils" / "google-speech-key.json"
if _key_path.exists() and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_key_path)

# ── 載入 .env（PROJECT_ID 等） ─────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# ── 專案模組 ──────────────────────────────────────────────────────────────────
from scripts.cer_engine import calculate_cer, calculate_wer, normalize_text

# ── 常數 ──────────────────────────────────────────────────────────────────────
DEFAULT_DATASET   = "experiments/61001"
DEFAULT_MODEL     = "large-v3"
CORRECT_CER_THRESHOLD = 0.30   # CER < 30% 視為「正確」

PROJECT_ID  = os.getenv("GOOGLE_CLOUD_PROJECT", "dazzling-seat-315406")
STT_LOCATION = os.getenv("STT_LOCATION", "asia-northeast1")
STT_MODEL    = "chirp_3"


# ============================================================================
# Ground Truth 解析
# ============================================================================

def parse_huizhen(huizhen_path: Path) -> dict:
    """
    解析「彙整」文字檔，回傳 {wav_stem: ground_truth_text} 字典。

    格式範例：
        【15:44:38】UltraLog06020260321154438.wav
        好,就叫99組站長...

        【15:44:56】UltraLog06020260321154456.wav
        謝謝謝謝謝
    """
    text = huizhen_path.read_text(encoding="utf-8-sig")
    pattern = re.compile(r"【\d{1,2}:\d{2}:\d{2}】(\S+\.wav)\n(.*?)(?=\n【|\Z)", re.DOTALL)

    result = {}
    for m in pattern.finditer(text):
        wav_name = m.group(1).strip()
        content  = m.group(2).strip()
        stem     = Path(wav_name).stem
        result[stem] = content

    return result


def find_huizhen(dataset_dir: Path) -> Path:
    """找到資料夾內的彙整 .txt 檔。"""
    candidates = list(dataset_dir.glob("*彙整*.txt"))
    if not candidates:
        raise FileNotFoundError(f"找不到彙整檔案於 {dataset_dir}")
    # 取最新的
    return sorted(candidates)[-1]


# ============================================================================
# Whisper 辨識（lazy import，避免未安裝時整個腳本失敗）
# ============================================================================

def run_whisper(audio_path: Path, model_size: str) -> str:
    """執行 Whisper 辨識，回傳辨識文字。"""
    try:
        from scripts.models.model_whisper import transcribe_with_whisper
    except ImportError as e:
        raise RuntimeError(
            f"無法載入 Whisper：{e}\n"
            "請先安裝：pip install openai-whisper"
        )
    return transcribe_with_whisper(
        str(audio_path),
        model_size=model_size,
        use_vocabulary=True,
        language="zh",
    )


# ============================================================================
# Google STT 辨識
# ============================================================================

def load_google_phrases() -> list:
    """載入詞彙表供 Google STT 使用。"""
    phrases_path = PROJECT_ROOT / "vocabulary" / "google_phrases.json"
    if not phrases_path.exists():
        return []
    try:
        data = json.loads(phrases_path.read_text(encoding="utf-8"))
        return data.get("phrases", [])
    except Exception:
        return []


_google_model = None

def get_google_model():
    """單例模式，避免重複初始化。"""
    global _google_model
    if _google_model is None:
        from scripts.models.model_google_stt import GoogleSTTModel
        _google_model = GoogleSTTModel(
            project_id=PROJECT_ID,
            location=STT_LOCATION,
            model=STT_MODEL,
        )
    return _google_model


def run_google(audio_path: Path, phrases: list) -> str:
    """執行 Google STT 辨識，回傳辨識文字。"""
    model = get_google_model()
    result = model.transcribe_file(str(audio_path), phrases=phrases)
    if result.get("error"):
        raise RuntimeError(result["error"])
    return result.get("transcript", "")


# ============================================================================
# 互補類型判斷
# ============================================================================

def complementary_type(w_cer: float, g_cer: float, threshold: float) -> str:
    w_ok = w_cer < threshold
    g_ok = g_cer < threshold
    if w_ok and g_ok:
        return "both_correct"
    if w_ok and not g_ok:
        return "whisper_wins"
    if not w_ok and g_ok:
        return "google_wins"
    return "both_wrong"


# ============================================================================
# 主流程
# ============================================================================

def run_batch(
    dataset_dir: Path,
    model_size: str,
    skip_whisper: bool,
    skip_google: bool,
    resume: bool,
):
    print("\n" + "=" * 65)
    print(f"  Whisper vs Google STT 批次比對")
    print(f"  資料集  : {dataset_dir}")
    print(f"  Whisper : {'略過' if skip_whisper else model_size}")
    print(f"  Google  : {'略過' if skip_google else f'{STT_MODEL} @ {STT_LOCATION}'}")
    print(f"  Resume  : {'是' if resume else '否'}")
    print("=" * 65 + "\n")

    # ── 建立輸出資料夾 ──────────────────────────────────────────────────────
    out_whisper = dataset_dir / "asr_output" / "whisper"
    out_google  = dataset_dir / "asr_output" / "google"
    out_eval    = dataset_dir / "evaluation"
    for d in [out_whisper, out_google, out_eval]:
        d.mkdir(parents=True, exist_ok=True)

    # ── 解析 Ground Truth ───────────────────────────────────────────────────
    huizhen_path = find_huizhen(dataset_dir)
    print(f"📋 Ground Truth：{huizhen_path.name}")
    gt_dict = parse_huizhen(huizhen_path)
    print(f"   解析完成：{len(gt_dict)} 筆\n")

    # ── 取得 wav 清單 ────────────────────────────────────────────────────────
    wav_files = sorted(dataset_dir.glob("*.wav"))
    if not wav_files:
        print("❌ 找不到 .wav 檔案")
        return
    print(f"🎵 音檔數量：{len(wav_files)} 個\n")

    # ── 載入詞彙表（Google STT 用） ─────────────────────────────────────────
    phrases = [] if skip_google else load_google_phrases()
    if not skip_google:
        print(f"📚 詞彙表：{len(phrases)} 個詞彙\n")

    # ── 逐檔處理 ────────────────────────────────────────────────────────────
    rows = []
    start_all = time.time()

    for idx, wav_path in enumerate(wav_files, 1):
        stem = wav_path.stem
        gt   = gt_dict.get(stem, "").strip()

        print(f"[{idx:02d}/{len(wav_files)}] {wav_path.name}")
        if not gt:
            print("   ⚠️  無 Ground Truth，跳過")
            continue

        row = {
            "filename"    : wav_path.name,
            "gt"          : gt,
            "gt_chars"    : len(normalize_text(gt)),
            "whisper_text": "",
            "google_text" : "",
            "whisper_cer" : None,
            "google_cer"  : None,
            "whisper_wer" : None,
            "google_wer"  : None,
            "whisper_acc" : None,
            "google_acc"  : None,
            "complementary": "n/a",
            "whisper_error": "",
            "google_error" : "",
        }

        # ── Whisper ──────────────────────────────────────────────────────────
        if not skip_whisper:
            w_out = out_whisper / f"{stem}.txt"
            if resume and w_out.exists():
                row["whisper_text"] = w_out.read_text(encoding="utf-8").strip()
                print(f"   Whisper  ⏭️  (已存在)")
            else:
                t0 = time.time()
                try:
                    text = run_whisper(wav_path, model_size)
                    row["whisper_text"] = text
                    w_out.write_text(text, encoding="utf-8")
                    elapsed = time.time() - t0
                    print(f"   Whisper  ✅  ({elapsed:.1f}s)  {text[:50]}{'…' if len(text)>50 else ''}")
                except Exception as e:
                    row["whisper_error"] = str(e)
                    print(f"   Whisper  ❌  {e}")

        # ── Google STT ───────────────────────────────────────────────────────
        if not skip_google:
            g_out = out_google / f"{stem}.txt"
            if resume and g_out.exists():
                row["google_text"] = g_out.read_text(encoding="utf-8").strip()
                print(f"   Google   ⏭️  (已存在)")
            else:
                t0 = time.time()
                try:
                    text = run_google(wav_path, phrases)
                    row["google_text"] = text
                    g_out.write_text(text, encoding="utf-8")
                    elapsed = time.time() - t0
                    print(f"   Google   ✅  ({elapsed:.1f}s)  {text[:50]}{'…' if len(text)>50 else ''}")
                except Exception as e:
                    row["google_error"] = str(e)
                    print(f"   Google   ❌  {e}")

        # ── CER / WER ────────────────────────────────────────────────────────
        if row["whisper_text"]:
            r = calculate_cer(gt, row["whisper_text"])
            row["whisper_cer"] = round(r["cer"], 4)
            row["whisper_acc"] = round(r["accuracy"], 4)
            r2 = calculate_wer(gt, row["whisper_text"])
            row["whisper_wer"] = round(r2["wer"], 4)

        if row["google_text"]:
            r = calculate_cer(gt, row["google_text"])
            row["google_cer"] = round(r["cer"], 4)
            row["google_acc"] = round(r["accuracy"], 4)
            r2 = calculate_wer(gt, row["google_text"])
            row["google_wer"] = round(r2["wer"], 4)

        # ── 互補分類 ─────────────────────────────────────────────────────────
        if row["whisper_cer"] is not None and row["google_cer"] is not None:
            row["complementary"] = complementary_type(
                row["whisper_cer"], row["google_cer"], CORRECT_CER_THRESHOLD
            )
            label_map = {
                "both_correct" : "✅✅",
                "whisper_wins" : "🟡W",
                "google_wins"  : "🟢G",
                "both_wrong"   : "❌❌",
            }
            w_cer_pct = f"{row['whisper_cer']*100:.1f}%"
            g_cer_pct = f"{row['google_cer']*100:.1f}%"
            print(f"   CER  W={w_cer_pct}  G={g_cer_pct}  {label_map[row['complementary']]}")

        rows.append(row)
        print()

    total_elapsed = time.time() - start_all

    # ── 輸出 CSV ─────────────────────────────────────────────────────────────
    csv_path = out_eval / "comparison.csv"
    fieldnames = [
        "filename", "gt_chars",
        "whisper_cer", "google_cer",
        "whisper_wer", "google_wer",
        "whisper_acc", "google_acc",
        "complementary",
        "whisper_text", "google_text", "gt",
        "whisper_error", "google_error",
    ]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"📊 CSV 已儲存：{csv_path.relative_to(PROJECT_ROOT)}")

    # ── 輸出 Summary ─────────────────────────────────────────────────────────
    summary = _build_summary(rows, skip_whisper, skip_google, total_elapsed)
    summary_path = out_eval / "summary.txt"
    summary_path.write_text(summary, encoding="utf-8")
    print(summary)
    print(f"📝 Summary 已儲存：{summary_path.relative_to(PROJECT_ROOT)}")


def _build_summary(rows: list, skip_whisper: bool, skip_google: bool, elapsed: float) -> str:
    valid = [r for r in rows if r["complementary"] != "n/a"]
    n = len(valid)
    if n == 0:
        return "無有效比對資料。"

    def mean(vals):
        v = [x for x in vals if x is not None]
        return sum(v) / len(v) if v else float("nan")

    w_cers = [r["whisper_cer"] for r in valid]
    g_cers = [r["google_cer"]  for r in valid]
    w_wers = [r["whisper_wer"] for r in valid]
    g_wers = [r["google_wer"]  for r in valid]

    counts = {"both_correct": 0, "whisper_wins": 0, "google_wins": 0, "both_wrong": 0}
    for r in valid:
        counts[r["complementary"]] += 1

    complementary_cases = counts["whisper_wins"] + counts["google_wins"]
    complementary_pct   = complementary_cases / n * 100 if n else 0

    lines = [
        "=" * 65,
        f"  批次比對摘要  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 65,
        f"  有效比對筆數  : {n}",
        f"  總耗時        : {elapsed/60:.1f} 分鐘",
        "",
    ]

    if not skip_whisper:
        lines += [
            f"  ── Whisper large-v3 ──",
            f"  平均 CER  : {mean(w_cers)*100:.2f}%",
            f"  平均 WER  : {mean(w_wers)*100:.2f}%",
            f"  平均準確率: {(1-mean(w_cers))*100:.2f}%",
            "",
        ]
    if not skip_google:
        lines += [
            f"  ── Google STT chirp_3 ──",
            f"  平均 CER  : {mean(g_cers)*100:.2f}%",
            f"  平均 WER  : {mean(g_wers)*100:.2f}%",
            f"  平均準確率: {(1-mean(g_cers))*100:.2f}%",
            "",
        ]

    if not skip_whisper and not skip_google:
        lines += [
            f"  ── 互補分析（CER < {CORRECT_CER_THRESHOLD*100:.0f}% 視為正確）──",
            f"  兩者皆對  : {counts['both_correct']:3d} 筆 ({counts['both_correct']/n*100:.1f}%)",
            f"  僅 Whisper : {counts['whisper_wins']:3d} 筆 ({counts['whisper_wins']/n*100:.1f}%)",
            f"  僅 Google  : {counts['google_wins']:3d} 筆 ({counts['google_wins']/n*100:.1f}%)",
            f"  兩者皆錯  : {counts['both_wrong']:3d} 筆 ({counts['both_wrong']/n*100:.1f}%)",
            "",
            f"  互補潛力  : {complementary_cases} 筆 ({complementary_pct:.1f}%)",
            f"  ← 代表若 ensemble 可多救回的樣本",
        ]

        # 互補效益估算
        if counts["both_correct"] + complementary_cases > 0:
            ensemble_correct = counts["both_correct"] + complementary_cases
            ensemble_acc = ensemble_correct / n * 100
            w_acc = counts["both_correct"] + counts["whisper_wins"]
            g_acc = counts["both_correct"] + counts["google_wins"]
            lines += [
                "",
                f"  ── 效益估算（理想 ensemble 上限）──",
                f"  Whisper 單獨正確率 : {w_acc/n*100:.1f}%",
                f"  Google  單獨正確率 : {g_acc/n*100:.1f}%",
                f"  理想 Ensemble 上限 : {ensemble_acc:.1f}%",
            ]

    lines.append("=" * 65)
    return "\n".join(lines)


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Whisper vs Google STT 批次比對")
    parser.add_argument("--dataset",      default=DEFAULT_DATASET,
                        help=f"實驗資料夾（預設：{DEFAULT_DATASET}）")
    parser.add_argument("--model",        default=DEFAULT_MODEL,
                        help="Whisper 模型（turbo/medium/large-v3，預設：large-v3）")
    parser.add_argument("--skip-whisper", action="store_true",
                        help="略過 Whisper（只跑 Google STT）")
    parser.add_argument("--skip-google",  action="store_true",
                        help="略過 Google STT（只跑 Whisper）")
    parser.add_argument("--no-resume",    action="store_true",
                        help="強制重新辨識（不跳過已有結果）")
    args = parser.parse_args()

    dataset_dir = PROJECT_ROOT / args.dataset
    if not dataset_dir.exists():
        print(f"❌ 資料夾不存在：{dataset_dir}")
        sys.exit(1)

    run_batch(
        dataset_dir  = dataset_dir,
        model_size   = args.model,
        skip_whisper = args.skip_whisper,
        skip_google  = args.skip_google,
        resume       = not args.no_resume,
    )
