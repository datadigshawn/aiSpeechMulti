# 黃金語料集批次評測報告

- **時間**: 20260705_172107
- **引擎**: `sensevoice_ft_v3_chunk_aug`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 19/19 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **48.59%** |
| 平均 CER (final) | **48.18%** |
| 平均改善         | **+0.41%** |
| 平均 WER (final) | 70.80% |

## 🛡️ Regression guard（occurrence-weighted）

| 指標 | recall | hit/ref | 幻覺 |
|---|---|---|---|
| 關鍵詞 | **20.0%** | 12/60 | 0 |
| 站碼 | **42.4%** | 28/66 | 22 |
| 車廂號 | **0.0%** | 0/38 | 8 |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 5 | 45.86% | 45.21% | +0.65% |
| daily | 8 | 49.50% | 48.76% | +0.75% |
| door | 3 | 49.97% | 50.44% | -0.47% |
| emergency | 1 | 45.96% | 45.96% | +0.00% |
| track | 2 | 51.05% | 51.05% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 002 | daily | 63.16% | 63.16% | +0.00% | number_norm=1 |
| 007 | daily | 50.00% | 50.00% | +0.00% | — |
| 018 | daily | 46.43% | 45.24% | +1.19% | car_norm=1, number_norm=4 |
| 033 | control | 40.86% | 40.00% | +0.86% | car_norm=4, number_norm=13, dict=1 |
| 043 | daily | 47.06% | 47.06% | +0.00% | number_norm=2, dict=1 |
| 044 | control | 43.33% | 40.95% | +2.38% | car_norm=1, number_norm=7, dict=1, station_code=1 |
| 048 | daily | 40.00% | 38.00% | +2.00% | dict=1, station_code=1 |
| 051 | daily | 38.89% | 36.11% | +2.78% | number_norm=1, dict=1, station_code=1 |
| G0001 | emergency | 45.96% | 45.96% | +0.00% | — |
| G0011 | door | 66.67% | 66.67% | +0.00% | car_norm=1 |
| G0029 | track | 57.81% | 57.81% | +0.00% | dict=2 |
| G0033 | daily | 51.11% | 51.11% | +0.00% | — |
| G0034 | control | 55.56% | 55.56% | +0.00% | — |
| G0042 | control | 54.49% | 54.49% | +0.00% | car_norm=1, number_norm=6, dict=1 |
| G0052 | daily | 59.38% | 59.38% | +0.00% | — |
| G0063 | control | 35.05% | 35.05% | +0.00% | — |
| G0066 | door | 36.84% | 37.89% | -1.05% | number_norm=1, dict=1 |
| G0068 | door | 46.40% | 46.76% | -0.36% | car_norm=1, number_norm=5, dict=1 |
| G0069 | track | 44.29% | 44.29% | +0.00% | number_norm=1, dict=2 |