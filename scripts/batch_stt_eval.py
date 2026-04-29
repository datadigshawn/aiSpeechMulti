#!/usr/bin/env python3
"""
黃金語料集批次 STT 跑分腳本
==========================

對 manifest.csv 中所有樣本，跑指定引擎的 STT 並把結果寫入
experiments/golden_dataset/stt_outputs/{engine_label}/{id}.txt

支援引擎：chirp3 / gemini / scribe / sensevoice
- 已存在的輸出預設 skip（resumable），加 --force 強制重跑
- 各引擎累計耗時與字數統計

用法：
    # 跑單一引擎
    python3 scripts/batch_stt_eval.py --engine chirp3

    # 跑多個引擎（依序）
    python3 scripts/batch_stt_eval.py --engines chirp3,gemini,scribe,sensevoice

    # 強制重跑（覆寫快取）
    python3 scripts/batch_stt_eval.py --engine gemini --force
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 載入 .env
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

# .env 中的 GOOGLE_APPLICATION_CREDENTIALS 指向另一個 repo（aiSpeech），
# 在此覆寫為本專案路徑
_GOOGLE_KEY_PATH = PROJECT_ROOT / "utils" / "google-speech-key.json"
if _GOOGLE_KEY_PATH.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_GOOGLE_KEY_PATH)

# .env 中的 GEMINI_API_KEY 是個無效路徑值，
# 改從 utils/api_keys.json 讀真實 key
def _load_gemini_key() -> str | None:
    import json
    p = PROJECT_ROOT / "utils" / "api_keys.json"
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            return cfg.get("GEMINI_API_KEY")
        except Exception:
            return None
    return None

MANIFEST_PATH = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"
STT_OUTPUTS_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "stt_outputs"


# ══════════════════════════════════════════════════════════════════════
# 引擎工廠
# ══════════════════════════════════════════════════════════════════════
def make_engine(label: str):
    if label == "chirp3":
        from scripts.models.model_google_stt import GoogleSTTModel
        return GoogleSTTModel(
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT", "dazzling-seat-315406"),
            location="asia-northeast1",
            model="chirp_3",
            language_code="cmn-Hant-TW",
            auto_convert_audio=True,
            use_config_manager=True,
        )
    if label == "gemini":
        from scripts.models.model_gemini import GeminiModel
        return GeminiModel(api_key=_load_gemini_key(), model="gemini-2.5-flash", temperature=0.0)
    if label == "gemini25pro":
        from scripts.models.model_gemini import GeminiModel
        return GeminiModel(api_key=_load_gemini_key(), model="gemini-2.5-pro", temperature=0.0)
    if label == "gemini31pro":
        from scripts.models.model_gemini import GeminiModel
        return GeminiModel(api_key=_load_gemini_key(), model="gemini-3.1-pro-preview", temperature=0.0)
    if label == "scribe":
        from scripts.models.model_scribe import ScribeSTTModel
        return ScribeSTTModel(language_code="zh", diarize=False, timeout=120.0)
    if label == "sensevoice":
        from scripts.models.model_sensevoice import SenseVoiceModel
        return SenseVoiceModel(
            model_name="iic/SenseVoiceSmall",
            language="zh",
            device="cpu",
            use_vad=True,
        )
    raise ValueError(f"Unknown engine label: {label}")


# ══════════════════════════════════════════════════════════════════════
# Manifest
# ══════════════════════════════════════════════════════════════════════
def load_manifest() -> list[dict]:
    rows = []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("has_gt") == "Y":
                rows.append(row)
    return rows


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def run_engine(label: str, force: bool = False) -> dict:
    print(f"\n{'═' * 70}")
    print(f"🎯 引擎：{label}")
    print(f"{'═' * 70}")

    out_dir = STT_OUTPUTS_DIR / label
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest()
    print(f"📋 共 {len(manifest)} 筆樣本")

    # 模型初始化（一次）
    t_init_start = time.time()
    try:
        engine = make_engine(label)
    except Exception as e:
        print(f"❌ 引擎初始化失敗: {e}")
        return {"label": label, "error": str(e)}
    init_sec = time.time() - t_init_start
    print(f"✅ 引擎已就緒（init {init_sec:.1f}s）\n")

    total_chars = 0
    total_audio_sec = 0.0
    total_stt_sec = 0.0
    success = 0
    skipped = 0
    failed = 0

    for i, sample in enumerate(manifest, 1):
        sid = sample["id"]
        event_type = sample["event_type"]
        audio_path = PROJECT_ROOT / sample["audio_file"]
        out_path = out_dir / f"{sid}.txt"
        duration = float(sample.get("duration_sec") or 0)

        prefix = f"[{i:3}/{len(manifest)}] {sid} ({event_type:10})"

        if out_path.exists() and not force:
            print(f"{prefix} ⏭️  cache hit ({out_path.stat().st_size}B)")
            skipped += 1
            continue
        if not audio_path.exists():
            print(f"{prefix} ❌ audio not found")
            failed += 1
            continue

        t0 = time.time()
        try:
            result = engine.transcribe_file(str(audio_path))
            transcript = (result.get("transcript") or "").strip()
            elapsed = time.time() - t0

            out_path.write_text(transcript, encoding="utf-8")
            total_chars += len(transcript)
            total_stt_sec += elapsed
            total_audio_sec += duration
            success += 1

            rtf = elapsed / duration if duration > 0 else 0
            print(f"{prefix} ✅ {len(transcript):4d}字 / {elapsed:5.1f}s (RTF {rtf:.2f})")
        except Exception as e:
            elapsed = time.time() - t0
            err_msg = str(e)[:200]
            print(f"{prefix} ❌ {elapsed:.1f}s err: {err_msg}")
            failed += 1

    summary = {
        "label": label,
        "samples": len(manifest),
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "total_chars": total_chars,
        "total_audio_sec": round(total_audio_sec, 1),
        "total_stt_sec": round(total_stt_sec, 1),
        "rtf_avg": round(total_stt_sec / total_audio_sec, 3) if total_audio_sec > 0 else 0,
    }
    print(f"\n📊 {label} 結果：success={success} skipped={skipped} failed={failed}")
    print(f"   總字數 {total_chars} / 音檔 {summary['total_audio_sec']}s / 推論 {summary['total_stt_sec']}s / RTF {summary['rtf_avg']}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", help="單一引擎")
    ap.add_argument("--engines", help="多個引擎（逗號分隔）")
    ap.add_argument("--force", action="store_true", help="強制重跑（覆寫快取）")
    args = ap.parse_args()

    if args.engines:
        engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    elif args.engine:
        engines = [args.engine]
    else:
        engines = ["chirp3", "gemini", "scribe", "sensevoice"]

    print(f"🚀 將跑 {len(engines)} 個引擎: {engines}")
    print(f"   manifest: {MANIFEST_PATH}")
    print(f"   outputs:  {STT_OUTPUTS_DIR}/<engine>/<id>.txt")

    summaries = []
    for label in engines:
        try:
            summaries.append(run_engine(label, force=args.force))
        except KeyboardInterrupt:
            print(f"\n⏹️  使用者中斷")
            break
        except Exception as e:
            print(f"\n❌ {label} 整體失敗: {e}")
            summaries.append({"label": label, "error": str(e)})

    print(f"\n\n{'═' * 70}")
    print("📈 全部引擎統計")
    print(f"{'═' * 70}")
    print(f"{'engine':<12} {'success':>8} {'skipped':>8} {'failed':>7} {'chars':>7} {'audio_s':>8} {'stt_s':>8} {'RTF':>6}")
    for s in summaries:
        if "error" in s:
            print(f"{s['label']:<12} ERROR: {s['error'][:60]}")
        else:
            print(f"{s['label']:<12} {s['success']:>8} {s['skipped']:>8} {s['failed']:>7} {s['total_chars']:>7} {s['total_audio_sec']:>8.1f} {s['total_stt_sec']:>8.1f} {s['rtf_avg']:>6}")


if __name__ == "__main__":
    main()
