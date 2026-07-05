# 黃金語料集批次評測報告

- **時間**: 20260705_153924
- **引擎**: `sensevoice_ft_v2_157gt`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 18/21 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **26.45%** |
| 平均 CER (final) | **26.21%** |
| 平均改善         | **+0.24%** |
| 平均 WER (final) | 45.48% |

## 🛡️ Regression guard（occurrence-weighted）

| 指標 | recall | hit/ref | 幻覺 |
|---|---|---|---|
| 關鍵詞 | **47.1%** | 16/34 | 0 |
| 站碼 | **58.5%** | 38/65 | 13 |
| 車廂號 | **10.5%** | 4/38 | 16 |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 5 | 29.62% | 29.15% | +0.47% |
| daily | 8 | 27.94% | 27.60% | +0.33% |
| door | 3 | 22.58% | 22.82% | -0.24% |
| track | 2 | 18.40% | 18.40% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 002 | daily | 31.58% | 36.84% | -5.26% | number_norm=2 |
| 007 | daily | 25.00% | 25.00% | +0.00% | — |
| 018 | daily | 14.29% | 11.90% | +2.38% | number_norm=3, station_code=2 |
| 033 | control | 28.97% | 28.45% | +0.52% | car_norm=1, number_norm=11, dict=1, station_code=2 |
| 043 | daily | 30.88% | 30.88% | +0.00% | number_norm=1 |
| 044 | control | 34.76% | 31.90% | +2.86% | car_norm=1, number_norm=6, dict=3, station_code=2 |
| 048 | daily | 28.00% | 28.00% | +0.00% | dict=1 |
| 051 | daily | 16.67% | 11.11% | +5.56% | car_norm=1, number_norm=1, station_code=1 |
| A003 | emergency | — | — | — | ❌ STT cache not found |
| A004 | emergency | — | — | — | ❌ STT cache not found |
| A005 | emergency | — | — | — | ❌ STT cache not found |
| G0011 | door | 30.00% | 30.00% | +0.00% | car_norm=1, dict=1 |
| G0029 | track | 12.50% | 12.50% | +0.00% | dict=2 |
| G0033 | daily | 33.33% | 33.33% | +0.00% | car_norm=1 |
| G0034 | control | 18.52% | 18.52% | +0.00% | — |
| G0042 | control | 44.19% | 44.19% | +0.00% | number_norm=7, dict=1 |
| G0052 | daily | 43.75% | 43.75% | +0.00% | number_norm=1 |
| G0063 | control | 21.65% | 22.68% | -1.03% | number_norm=1 |
| G0066 | door | 15.79% | 15.79% | +0.00% | dict=2 |
| G0068 | door | 21.94% | 22.66% | -0.72% | car_norm=2, number_norm=6, dict=2 |
| G0069 | track | 24.29% | 24.29% | +0.00% | dict=2 |