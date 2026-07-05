# 黃金語料集批次評測報告

- **時間**: 20260705_172959
- **引擎**: `sensevoice_ft_v3a_chunk_only`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 19/19 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **28.78%** |
| 平均 CER (final) | **28.09%** |
| 平均改善         | **+0.69%** |
| 平均 WER (final) | 52.30% |

## 🛡️ Regression guard（occurrence-weighted）

| 指標 | recall | hit/ref | 幻覺 |
|---|---|---|---|
| 關鍵詞 | **45.0%** | 27/60 | 0 |
| 站碼 | **60.6%** | 40/66 | 17 |
| 車廂號 | **7.9%** | 3/38 | 27 |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 5 | 29.92% | 29.03% | +0.89% |
| daily | 8 | 29.39% | 29.09% | +0.30% |
| door | 3 | 25.28% | 23.18% | +2.10% |
| emergency | 1 | 27.95% | 27.95% | +0.00% |
| track | 2 | 29.19% | 29.19% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 002 | daily | 42.11% | 42.11% | +0.00% | number_norm=1 |
| 007 | daily | 25.00% | 25.00% | +0.00% | — |
| 018 | daily | 21.43% | 19.05% | +2.38% | number_norm=5 |
| 033 | control | 28.28% | 26.38% | +1.90% | car_norm=4, number_norm=16, dict=2, station_code=2 |
| 043 | daily | 35.29% | 35.29% | +0.00% | car_norm=1, number_norm=1 |
| 044 | control | 30.48% | 28.10% | +2.38% | car_norm=1, number_norm=7, dict=2, station_code=1 |
| 048 | daily | 28.00% | 28.00% | +0.00% | dict=2 |
| 051 | daily | 22.22% | 22.22% | +0.00% | dict=1 |
| G0001 | emergency | 27.95% | 27.95% | +0.00% | number_norm=1 |
| G0011 | door | 36.67% | 30.00% | +6.67% | car_norm=1 |
| G0029 | track | 31.25% | 31.25% | +0.00% | dict=2 |
| G0033 | daily | 26.67% | 26.67% | +0.00% | car_norm=1 |
| G0034 | control | 33.33% | 33.33% | +0.00% | — |
| G0042 | control | 38.95% | 38.76% | +0.19% | car_norm=4, number_norm=8, dict=2, station_code=1 |
| G0052 | daily | 34.38% | 34.38% | +0.00% | number_norm=1 |
| G0063 | control | 18.56% | 18.56% | +0.00% | dict=1 |
| G0066 | door | 15.79% | 15.79% | +0.00% | dict=2 |
| G0068 | door | 23.38% | 23.74% | -0.36% | car_norm=1, number_norm=5, dict=3 |
| G0069 | track | 27.14% | 27.14% | +0.00% | dict=2 |