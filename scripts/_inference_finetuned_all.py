#!/usr/bin/env python3
"""對 manifest 全 63 段用 fine-tuned LoRA checkpoint 跑推論"""
import sys, csv, re, torch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funasr import AutoModel
from peft import LoraConfig, get_peft_model, TaskType, set_peft_model_state_dict

CKPT = Path("experiments/finetune_runs/sensevoice_lora_r32_e60/best.pt")
OUT_DIR = Path("experiments/golden_dataset/stt_outputs/sensevoice_ft_r32_full")
MANIFEST = Path("experiments/golden_dataset/manifest.csv")

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Loading SenseVoiceSmall + LoRA checkpoint (device={device})...")
model = AutoModel(model="FunAudioLLM/SenseVoiceSmall", hub="hf", device=device, disable_update=True)
state = torch.load(CKPT, map_location=device, weights_only=False)
lora_config = LoraConfig(
    r=32, lora_alpha=64,
    target_modules=["q_proj", "k_proj", "v_proj", "out_proj",
                    "linear_q", "linear_k", "linear_v", "linear_out"],
    lora_dropout=0.05, bias="none",
    task_type=TaskType.FEATURE_EXTRACTION,
)
wrapped = get_peft_model(model.model, lora_config)
set_peft_model_state_dict(wrapped, state["lora_state_dict"])
model.model = wrapped
print("Model ready")

samples = []
with open(MANIFEST, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r.get("has_gt") == "Y":
            samples.append((r["id"], r["audio_file"]))

OUT_DIR.mkdir(parents=True, exist_ok=True)
ok = 0
fail = 0
for i, (sid, audio) in enumerate(samples, 1):
    try:
        res = model.generate(input=audio, cache={}, language="zh", use_itn=True)
        txt = res[0].get("text", "") if res else ""
        txt = re.sub(r"<\|[^|]+\|>", "", txt).strip()
        (OUT_DIR / f"{sid}.txt").write_text(txt, encoding="utf-8")
        ok += 1
        if i % 10 == 0:
            print(f"  [{i}/{len(samples)}] {sid}: {len(txt)} chars")
    except Exception as e:
        fail += 1
        print(f"  {sid} FAIL: {str(e)[:80]}")

print(f"\nDone: {ok}/{len(samples)} success, {fail} fail")
print(f"Output: {OUT_DIR}")
