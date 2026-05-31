# fine-tune 評估報告 — sensevoice_ft_r32

- 時間：20260501_212651
- checkpoint：experiments/finetune_runs/sensevoice_lora_r32_e60/best.pt
- 對照基準：sensevoice,gemini25pro

## CER 對照

| model | post_process | raw CER | final CER |
|---|---|---|---|
| sensevoice_ft_r32 | raw | 30.78% | 29.38% |
| sensevoice_ft_r32 | car_norm,dict | 30.78% | 28.68% |
| sensevoice | raw | 65.84% | 65.03% |
| sensevoice | car_norm,dict | 65.84% | 64.97% |
| gemini25pro | raw | 49.34% | 48.55% |
| gemini25pro | car_norm,dict | 49.34% | 48.35% |