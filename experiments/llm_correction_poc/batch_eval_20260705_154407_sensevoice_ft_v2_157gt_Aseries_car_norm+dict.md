# 黃金語料集批次評測報告

- **時間**: 20260705_154407
- **引擎**: `sensevoice_ft_v2_157gt_Aseries`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 13/13 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **45.25%** |
| 平均 CER (final) | **45.39%** |
| 平均改善         | **-0.14%** |
| 平均 WER (final) | 58.34% |

## 🛡️ Regression guard（occurrence-weighted）

| 指標 | recall | hit/ref | 幻覺 |
|---|---|---|---|
| 關鍵詞 | **50.0%** | 2/4 | 0 |
| 站碼 | **100.0%** | 2/2 | 5 |
| 車廂號 | **n/a** | 0/0 | 0 |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| emergency | 13 | 45.25% | 45.39% | -0.14% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| A001 | emergency | 39.68% | 39.68% | +0.00% | number_norm=2 |
| A002 | emergency | 23.56% | 23.56% | +0.00% | number_norm=1, dict=1 |
| A003 | emergency | 54.48% | 54.48% | +0.00% | — |
| A004 | emergency | 54.76% | 54.76% | +0.00% | number_norm=1 |
| A005 | emergency | 83.33% | 85.00% | -1.67% | number_norm=1, dict=1 |
| A007 | emergency | 44.97% | 44.97% | +0.00% | — |
| A008 | emergency | 47.75% | 47.75% | +0.00% | — |
| A009 | emergency | 42.59% | 42.59% | +0.00% | — |
| A010 | emergency | 48.62% | 48.62% | +0.00% | dict=1 |
| A011 | emergency | 33.33% | 33.33% | +0.00% | — |
| A012 | emergency | 47.82% | 47.94% | -0.12% | car_norm=1, number_norm=1, dict=1 |
| A013 | emergency | 35.09% | 35.09% | +0.00% | — |
| A014 | emergency | 32.27% | 32.27% | +0.00% | — |