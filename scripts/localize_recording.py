#!/usr/bin/env python3
"""
批次句級時間定位：錄音檔 → 每句（SenseVoice 文字 + 絕對牆鐘時間）
==================================================================
主力 SenseVoice 辨識 + 顯式 fsmn-vad 取句界，零 Paraformer（句級不需要）。
用途：事件時間軸、查「某時某分線上說了什麼」。

流程：
    音檔 → fsmn-vad 句界[start,end] → 每句 SenseVoice 文字
    絕對時間 = 檔名 session start（YYYYMMDD_HHMMSS）+ 句 offset；檔名無日期 → 用檔案 mtime

⚠️ 不用 SenseVoice 自帶 segment 時間（實測壞：回 1 段 start=end=0）。

用法：
    python scripts/localize_recording.py rec.wav
    python scripts/localize_recording.py a.wav b.wav --out-dir experiments/localized
    python scripts/localize_recording.py rec.wav --checkpoint <ft/best.pt> --device cpu
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

VAD_DIR = os.path.expanduser(
    "~/.cache/modelscope/hub/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
)
_TAG_RE = re.compile(r"<\|[^|]*\|>")


def _strip(s: str) -> str:
    return _TAG_RE.sub("", s or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", nargs="+", help="錄音檔（.wav/.mp3…）")
    ap.add_argument("--out-dir", default="experiments/localized",
                    help="輸出目錄（每檔一份 .json + .txt）")
    ap.add_argument("--checkpoint", default="",
                    help="SenseVoice LoRA checkpoint（預設用 SenseVoiceFTModel 內建主力 v2）")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--no-write", action="store_true", help="只印不寫檔")
    args = ap.parse_args()

    from funasr import AutoModel
    from scripts.models.model_sensevoice_ft import SenseVoiceFTModel
    from utils.sentence_localizer import session_start_from_filename, localize_sentences
    import soundfile as sf

    print("📦 載入 fsmn-vad + SenseVoice-ft（主力）…")
    vad = AutoModel(model=VAD_DIR, disable_update=True)
    sv = SenseVoiceFTModel(ckpt_path=args.checkpoint) if args.checkpoint else SenseVoiceFTModel()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    if not args.no_write:
        out_dir.mkdir(parents=True, exist_ok=True)

    for a in args.audio:
        ap_path = a if os.path.isabs(a) else str(PROJECT_ROOT / a)
        if not os.path.exists(ap_path):
            print(f"⚠️ 找不到 {a}，略過")
            continue
        wav, sr = sf.read(ap_path)
        if wav.ndim == 2:
            wav = wav.mean(axis=1)
        # session 起始時間：檔名優先，否則檔案 mtime
        ss = session_start_from_filename(ap_path)
        ss_source = "filename"
        if ss is None:
            ss = datetime.fromtimestamp(os.path.getmtime(ap_path))
            ss_source = "mtime"

        segs_ms = vad.generate(input=ap_path)[0]["value"]
        segments = []
        for s, e in segs_ms:
            clip = wav[int(s / 1000 * sr):int(e / 1000 * sr)]
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                sf.write(tf.name, clip, sr)
                tmp = tf.name
            try:
                txt = _strip(sv.transcribe_file(tmp)["transcript"])
            finally:
                os.unlink(tmp)
            segments.append({"start": s / 1000.0, "end": e / 1000.0, "text": txt})

        sentences = localize_sentences(segments, session_start=ss)
        name = Path(ap_path).stem
        print(f"\n=== {name}  ({len(sentences)} 句, session start={ss.isoformat()} [{ss_source}]) ===")
        for x in sentences:
            t = x["abs_time"][11:19] if x["abs_time"] else "--:--:--"
            print(f"  [{t}] {x['start_ms']/1000:6.1f}-{x['end_ms']/1000:6.1f}s  {x['text']}")

        if not args.no_write:
            rec = {
                "audio": os.path.relpath(ap_path, PROJECT_ROOT),
                "session_start": ss.isoformat(),
                "session_start_source": ss_source,
                "engine": "sensevoice_ft + fsmn-vad",
                "sentences": sentences,
            }
            (out_dir / f"{name}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            txt_lines = [
                f"[{(x['abs_time'][11:19] if x['abs_time'] else '--:--:--')}] {x['text']}"
                for x in sentences
            ]
            (out_dir / f"{name}.txt").write_text("\n".join(txt_lines), encoding="utf-8")

    if not args.no_write:
        print(f"\n✅ 輸出於 {out_dir}（每檔 .json 結構化 + .txt 可讀）")


if __name__ == "__main__":
    main()
