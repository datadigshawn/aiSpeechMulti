# fine-tune 評估報告 — sensevoice_ft_v2_157gt

- 時間：20260531_174244
- checkpoint：experiments/finetune_runs/sensevoice_lora_r32_e60_v2_157gt/best.pt
- 對照基準：sensevoice,gemini25pro

## CER 對照

| model | post_process | raw CER | final CER |
|---|---|---|---|
| sensevoice_ft_v2_157gt | raw | 26.20% | 26.44% |
| sensevoice_ft_v2_157gt | car_norm,dict | 26.20% | 26.32% |
| sensevoice | raw | 65.84% | 65.03% |
| sensevoice | car_norm,dict | 65.84% | 64.97% |
| gemini25pro | raw | 49.34% | 48.55% |
| gemini25pro | car_norm,dict | 49.34% | 48.35% |