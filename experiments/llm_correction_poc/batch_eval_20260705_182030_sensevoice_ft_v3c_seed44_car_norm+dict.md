# 黃金語料集批次評測報告

- **時間**: 20260705_182030
- **引擎**: `sensevoice_ft_v3c_seed44`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 19/19 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **29.56%** |
| 平均 CER (final) | **29.26%** |
| 平均改善         | **+0.30%** |
| 平均 WER (final) | 50.04% |

## 🛡️ Regression guard（occurrence-weighted）

| 指標 | recall | hit/ref | 幻覺 |
|---|---|---|---|
| 關鍵詞 | **50.0%** | 30/60 | 0 |
| 站碼 | **50.0%** | 33/66 | 19 |
| 車廂號 | **10.5%** | 4/38 | 27 |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 5 | 31.96% | 31.19% | +0.77% |
| daily | 8 | 32.30% | 32.56% | -0.26% |
| door | 3 | 25.00% | 23.66% | +1.34% |
| emergency | 1 | 25.47% | 25.47% | +0.00% |
| track | 2 | 21.52% | 21.52% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 002 | daily | 47.37% | 47.37% | +0.00% | number_norm=1, dict=1 |
| 007 | daily | 30.00% | 35.00% | -5.00% | number_norm=1 |
| 018 | daily | 23.81% | 21.43% | +2.38% | number_norm=5 |
| 033 | control | 30.34% | 29.83% | +0.52% | car_norm=5, number_norm=13, dict=1 |
| 043 | daily | 36.76% | 38.24% | -1.47% | number_norm=2 |
| 044 | control | 38.10% | 34.76% | +3.33% | car_norm=2, number_norm=7, dict=1, station_code=2 |
| 048 | daily | 32.00% | 30.00% | +2.00% | car_norm=1, dict=1, station_code=1 |
| 051 | daily | 19.44% | 19.44% | +0.00% | car_norm=1, dict=1 |
| G0001 | emergency | 25.47% | 25.47% | +0.00% | — |
| G0011 | door | 33.33% | 30.00% | +3.33% | car_norm=1 |
| G0029 | track | 18.75% | 18.75% | +0.00% | dict=2 |
| G0033 | daily | 37.78% | 37.78% | +0.00% | car_norm=1 |
| G0034 | control | 29.63% | 29.63% | +0.00% | — |
| G0042 | control | 38.01% | 38.01% | +0.00% | car_norm=2, number_norm=6, dict=2, station_code=1 |
| G0052 | daily | 31.25% | 31.25% | +0.00% | — |
| G0063 | control | 23.71% | 23.71% | +0.00% | number_norm=1 |
| G0066 | door | 16.84% | 15.79% | +1.05% | dict=3 |
| G0068 | door | 24.82% | 25.18% | -0.36% | car_norm=2, number_norm=5, dict=1 |
| G0069 | track | 24.29% | 24.29% | +0.00% | dict=2 |