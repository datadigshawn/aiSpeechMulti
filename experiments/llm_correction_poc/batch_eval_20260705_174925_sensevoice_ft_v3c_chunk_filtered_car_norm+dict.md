# 黃金語料集批次評測報告

- **時間**: 20260705_174925
- **引擎**: `sensevoice_ft_v3c_chunk_filtered`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 19/19 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **27.03%** |
| 平均 CER (final) | **26.52%** |
| 平均改善         | **+0.51%** |
| 平均 WER (final) | 47.83% |

## 🛡️ Regression guard（occurrence-weighted）

| 指標 | recall | hit/ref | 幻覺 |
|---|---|---|---|
| 關鍵詞 | **61.7%** | 37/60 | 1 |
| 站碼 | **60.6%** | 40/66 | 13 |
| 車廂號 | **21.1%** | 8/38 | 23 |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 5 | 28.90% | 27.89% | +1.01% |
| daily | 8 | 30.05% | 29.98% | +0.07% |
| door | 3 | 22.94% | 21.60% | +1.34% |
| emergency | 1 | 28.57% | 28.57% | +0.00% |
| track | 2 | 15.67% | 15.67% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 002 | daily | 42.11% | 42.11% | +0.00% | number_norm=1, dict=1 |
| 007 | daily | 30.00% | 35.00% | -5.00% | number_norm=1 |
| 018 | daily | 20.24% | 16.67% | +3.57% | number_norm=6 |
| 033 | control | 26.72% | 25.17% | +1.55% | car_norm=3, number_norm=16, dict=1, station_code=2 |
| 043 | daily | 26.47% | 26.47% | +0.00% | car_norm=1, number_norm=1 |
| 044 | control | 30.00% | 26.67% | +3.33% | car_norm=2, number_norm=6, dict=2, station_code=1 |
| 048 | daily | 44.00% | 42.00% | +2.00% | car_norm=1, dict=1, station_code=1 |
| 051 | daily | 13.89% | 13.89% | +0.00% | car_norm=1, dict=1 |
| G0001 | emergency | 28.57% | 28.57% | +0.00% | number_norm=1 |
| G0011 | door | 30.00% | 26.67% | +3.33% | car_norm=1 |
| G0029 | track | 15.62% | 15.62% | +0.00% | dict=2 |
| G0033 | daily | 35.56% | 35.56% | +0.00% | — |
| G0034 | control | 29.63% | 29.63% | +0.00% | — |
| G0042 | control | 36.52% | 36.33% | +0.19% | car_norm=3, number_norm=8, dict=2, station_code=1 |
| G0052 | daily | 28.12% | 28.12% | +0.00% | number_norm=1 |
| G0063 | control | 21.65% | 21.65% | +0.00% | number_norm=1, dict=1 |
| G0066 | door | 15.79% | 14.74% | +1.05% | dict=3 |
| G0068 | door | 23.02% | 23.38% | -0.36% | car_norm=1, number_norm=4, dict=3 |
| G0069 | track | 15.71% | 15.71% | +0.00% | dict=2 |