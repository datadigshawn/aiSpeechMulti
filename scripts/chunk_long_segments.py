#!/usr/bin/env python3
"""
切窗管線：把訓練集裡的長音檔切成 ≤max-sec 的 (audio, text) 對
=============================================================
目的：攻 C3 最大錯誤桶——長段 under-generation（漏字 ~49%）。讓訓練分布對齊
推論時的 VAD 切窗分布（S1a），使模型在「實際會遇到的長度」上學習。

原理（VAD 自舉對齊，不需 forced-alignment 模型）：
  1. VAD（fsmn-vad）把長音檔切成自然小段（聲學切點，與辨識品質無關）。
  2. 對每個小段跑 fine-tuned SenseVoice（短段辨識才準）→ hyp。
  3. 把各小段 hyp 串接後對齊回 GT（difflib，文字對文字）→ 找 GT 切點分配文字。
  4. 合併小段到 ≤max-sec 的訓練塊；塊邊界落在最大靜音處（最可靠）。

設計：只處理 train.jsonl（funasr 格式）的長段，test/val 不動（test 推論端由 S1a
切窗，不可洩漏）。短段原樣通過。

用法：
    python scripts/chunk_long_segments.py \\
        --in experiments/finetune_dataset/train.jsonl \\
        --checkpoint experiments/finetune_runs/sensevoice_lora_r32_e60_v2_157gt/best.pt \\
        --out-jsonl experiments/finetune_dataset/train_chunked.jsonl \\
        --out-audio experiments/finetune_dataset/chunks_audio \\
        --max-sec 45
    # 先看報告不寫檔：加 --report-only
"""
import argparse
import json
import os
import re
import sys
import tempfile
import difflib
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VAD_DIR = os.path.expanduser(
    "~/.cache/modelscope/hub/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
)
SV_HF = "FunAudioLLM/SenseVoiceSmall"

# 對齊用正規化（去標點/空白，留中文+英數，小寫）——與 cer 對齊空間一致
_TAG_RE = re.compile(r"<\|[^|]*\|>")


def norm(t: str) -> str:
    t = re.sub(r"^\s*[A-Za-z?]:\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"[^一-鿿\w]", "", t)
    return t.lower()


def strip_tags(s: str) -> str:
    return _TAG_RE.sub("", s)


def load_models(checkpoint: Path, device: str):
    """載入 VAD + fine-tuned SenseVoice（對齊器）。"""
    import torch
    from funasr import AutoModel

    vad = AutoModel(model=VAD_DIR, disable_update=True, device=device)
    sv = AutoModel(model=SV_HF, hub="hf", disable_update=True, device=device)
    if checkpoint and checkpoint.exists():
        sd = torch.load(checkpoint, map_location=device, weights_only=False)
        if isinstance(sd, dict) and "lora_state_dict" in sd:
            from peft import (LoraConfig, get_peft_model,
                              set_peft_model_state_dict, TaskType)
            cfg = LoraConfig(
                r=32, lora_alpha=64,
                target_modules=["q_proj", "k_proj", "v_proj", "out_proj",
                                "linear_q", "linear_k", "linear_v", "linear_out"],
                lora_dropout=0.05, bias="none",
                task_type=TaskType.FEATURE_EXTRACTION,
            )
            wrapped = get_peft_model(sv.model, cfg)
            set_peft_model_state_dict(wrapped, sd["lora_state_dict"])
            sv.model = wrapped
            print(f"   ✅ 對齊器載入 LoRA: {checkpoint.name}")
        else:
            sv.model.load_state_dict(sd, strict=False)
            print(f"   ✅ 對齊器載入 full state_dict")
    else:
        print("   ⚠️ 無 checkpoint，用 base SenseVoice 對齊（繁體領域品質差，不建議）")
    return vad, sv


def _asr_clip(sv, wav, sr, s_ms, e_ms):
    import soundfile as sf
    clip = wav[int(s_ms / 1000 * sr):int(e_ms / 1000 * sr)]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        sf.write(tf.name, clip, sr)
        tmp = tf.name
    try:
        out = sv.generate(input=tmp, cache={}, language="zh", use_itn=True)
        return strip_tags(out[0]["text"])
    finally:
        os.unlink(tmp)


def _map_boundaries(hyp_norm, gt_norm, cum_positions):
    """把 hyp_norm 的累積邊界位置 → gt_norm 位置（單調遞增，保證合法分割）。"""
    sm = difflib.SequenceMatcher(None, hyp_norm, gt_norm, autojunk=False)
    h2g = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            h2g[a + k] = b + k

    def nearest(p):
        if p in h2g:
            return h2g[p]
        for d in range(1, len(hyp_norm) + 1):
            if p - d in h2g:
                return h2g[p - d] + d
            if p + d in h2g:
                return max(0, h2g[p + d] - d)
        return min(p, len(gt_norm))

    bounds = []
    prev = 0
    for p in cum_positions:
        b = max(prev, nearest(p))
        prev = b
        bounds.append(b)
    return bounds


def chunk_one(vad, sv, audio_path, gt_raw, max_sec):
    """回傳 (chunks, stats)；chunks = [(start_ms,end_ms,gt_span,chunk_cer),...]。"""
    import soundfile as sf
    import jiwer

    wav, sr = sf.read(audio_path)
    segs = vad.generate(input=str(audio_path))[0]["value"]  # natural small segments
    if not segs:
        return [], {"ok": False, "reason": "no_vad_segments"}

    hyp_norms = [norm(_asr_clip(sv, wav, sr, s, e)) for s, e in segs]
    gt_norm = norm(gt_raw)
    cum, acc = [], 0
    for hn in hyp_norms:
        acc += len(hn)
        cum.append(acc)
    bounds = _map_boundaries("".join(hyp_norms), gt_norm, cum)
    cuts = [0] + bounds
    cuts[-1] = len(gt_norm)
    seg_gt = [gt_norm[cuts[i]:cuts[i + 1]] for i in range(len(segs))]
    reconstruct_ok = "".join(seg_gt) == gt_norm

    # 合併小段到 ≤max_sec 訓練塊（同時帶 hyp 供塊層級 QC）
    chunks = []
    cs, ce, cg, ch = segs[0][0], segs[0][1], seg_gt[0], hyp_norms[0]
    for (s, e), g, h in zip(segs[1:], seg_gt[1:], hyp_norms[1:]):
        if e - cs <= max_sec * 1000:
            ce, cg, ch = e, cg + g, ch + h
        else:
            chunks.append((cs, ce, cg, ch))
            cs, ce, cg, ch = s, e, g, h
    chunks.append((cs, ce, cg, ch))

    out = []
    cers = []
    for s, e, g, h in chunks:
        cc = jiwer.cer(g, h) if g else 1.0
        cers.append(cc)
        out.append((s, e, g, cc))
    stats = {
        "ok": reconstruct_ok,
        "n_vad": len(segs),
        "n_chunks": len(chunks),
        "max_chunk_cer": max(cers) if cers else 1.0,
    }
    return out, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_jsonl", required=True, help="輸入 train.jsonl（funasr 格式）")
    ap.add_argument("--checkpoint", default="", help="對齊器 LoRA checkpoint（強烈建議用 v2）")
    ap.add_argument("--out-jsonl", default="", help="輸出切窗後 jsonl")
    ap.add_argument("--out-audio", default="", help="切塊音檔輸出目錄")
    ap.add_argument("--max-sec", type=int, default=45, help="訓練塊長度上限（秒）")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--cer-flag", type=float, default=0.7,
                    help="塊 CER 超過此值標記為可疑（人工複查）")
    ap.add_argument("--report-only", action="store_true", help="只報告，不寫檔/不切音檔")
    args = ap.parse_args()

    in_path = Path(args.in_jsonl)
    if not in_path.is_absolute():
        in_path = PROJECT_ROOT / in_path
    records = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    long_recs = [r for r in records if (r.get("source_len", 0) / 1000.0) > args.max_sec]
    print(f"📋 輸入 {len(records)} 段，其中 {len(long_recs)} 段 > {args.max_sec}s 需切窗\n")

    if not args.report_only:
        if not args.out_jsonl or not args.out_audio:
            print("❌ 非 report-only 模式需 --out-jsonl 與 --out-audio")
            sys.exit(1)
        out_audio = Path(args.out_audio)
        if not out_audio.is_absolute():
            out_audio = PROJECT_ROOT / out_audio
        out_audio.mkdir(parents=True, exist_ok=True)

    print("📦 載入模型…")
    vad, sv = load_models(Path(args.checkpoint) if args.checkpoint else None, args.device)
    import soundfile as sf

    new_records = []
    flagged = []
    n_short_pass = n_chunks_made = n_bad_reconstruct = 0
    for r in records:
        dur = r.get("source_len", 0) / 1000.0
        if dur <= args.max_sec:
            new_records.append(r)
            n_short_pass += 1
            continue
        src = r["source"]
        src_path = src if os.path.isabs(src) else str(PROJECT_ROOT / src)
        chunks, stats = chunk_one(vad, sv, src_path, r["target"], args.max_sec)
        if not stats["ok"]:
            n_bad_reconstruct += 1
        wav, sr = sf.read(src_path)
        for i, (s, e, gt_span, cc) in enumerate(chunks):
            key = f"{r['key']}_c{i:02d}"
            flag = cc > args.cer_flag
            if flag:
                flagged.append((key, round(cc, 2)))
            if not args.report_only:
                clip = wav[int(s / 1000 * sr):int(e / 1000 * sr)]
                wav_path = out_audio / f"{key}.wav"
                sf.write(str(wav_path), clip, sr)
                rel = os.path.relpath(wav_path, PROJECT_ROOT)
                new_records.append({
                    "key": key,
                    "source": rel,
                    "source_len": int(e - s),
                    "target": gt_span,
                    "target_len": len(gt_span),
                    "event_type": r.get("event_type", ""),
                    "parent": r["key"],
                })
            n_chunks_made += 1
        print(f"  {r['key']:<10} {dur:5.0f}s → {stats['n_chunks']} 塊  "
              f"reconstruct={'OK' if stats['ok'] else 'FAIL'}  max_chunk_cer={stats['max_chunk_cer']*100:.0f}%")

    print(f"\n📊 結果：短段直通 {n_short_pass}，長段切出 {n_chunks_made} 塊；"
          f"reconstruct 失敗 {n_bad_reconstruct} 段")
    if flagged:
        print(f"⚠️ {len(flagged)} 塊 CER > {args.cer_flag*100:.0f}%（建議人工複查）：{flagged[:10]}")
    else:
        print("✅ 無高 CER 可疑塊")

    if not args.report_only:
        out_jsonl = Path(args.out_jsonl)
        if not out_jsonl.is_absolute():
            out_jsonl = PROJECT_ROOT / out_jsonl
        with open(out_jsonl, "w", encoding="utf-8") as f:
            for r in new_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"✅ 輸出 {len(new_records)} 段至 {out_jsonl}（音檔 {n_chunks_made} 塊於 {args.out_audio}）")


if __name__ == "__main__":
    main()
