# 黃金語料集批次評測報告

- **時間**: 20260501_224108
- **引擎**: `sensevoice_ft_r32_full`
- **後處理**: ['car_norm']
- **樣本**: 63/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **29.50%** |
| 平均 CER (final) | **28.74%** |
| 平均改善         | **+0.76%** |
| 平均 WER (final) | 45.77% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 22 | 35.71% | 35.60% | +0.11% |
| daily | 29 | 23.04% | 21.84% | +1.20% |
| door | 4 | 38.50% | 37.82% | +0.68% |
| emergency | 1 | 27.40% | 26.71% | +0.68% |
| track | 6 | 28.89% | 27.66% | +1.23% |
| train | 1 | 50.00% | 50.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 33.33% | 33.33% | +0.00% | number_norm=2 |
| 002 | daily | 26.32% | 21.05% | +5.26% | number_norm=2 |
| 003 | track | 33.33% | 33.33% | +0.00% | car_norm=1, number_norm=2 |
| 004 | track | 34.78% | 34.78% | +0.00% | number_norm=4 |
| 005 | daily | 52.38% | 52.38% | +0.00% | — |
| 006 | door | 17.14% | 14.29% | +2.86% | number_norm=2 |
| 007 | train | 50.00% | 50.00% | +0.00% | — |
| 008 | track | 34.85% | 33.33% | +1.52% | car_norm=2, number_norm=2 |
| 009 | daily | 10.71% | 3.57% | +7.14% | car_norm=1, number_norm=2 |
| 010 | control | 13.49% | 13.49% | +0.00% | number_norm=2 |
| 011 | control | 12.07% | 12.07% | +0.00% | number_norm=1 |
| 012 | emergency | 27.40% | 26.71% | +0.68% | car_norm=1, number_norm=3 |
| 013 | track | 13.10% | 8.33% | +4.76% | number_norm=4 |
| 014 | track | 24.72% | 23.60% | +1.12% | car_norm=2, number_norm=3 |
| 015 | daily | 10.53% | 10.53% | +0.00% | car_norm=1, number_norm=1 |
| 016 | daily | 15.79% | 15.79% | +0.00% | number_norm=2 |
| 017 | daily | 21.62% | 20.27% | +1.35% | car_norm=1, number_norm=3 |
| 018 | daily | 9.52% | 7.14% | +2.38% | number_norm=5 |
| 019 | daily | 25.71% | 24.29% | +1.43% | car_norm=1, number_norm=3 |
| 020 | daily | 12.50% | 6.25% | +6.25% | number_norm=1 |
| 021 | control | 29.23% | 28.46% | +0.77% | car_norm=1, number_norm=4 |
| 022 | control | 27.56% | 26.67% | +0.89% | car_norm=2, number_norm=3 |
| 023 | control | 32.80% | 32.80% | +0.00% | number_norm=2 |
| 024 | daily | 27.50% | 30.00% | -2.50% | car_norm=1, number_norm=1 |
| 025 | daily | 15.62% | 12.50% | +3.12% | car_norm=1, number_norm=2 |
| 026 | daily | 11.90% | 9.52% | +2.38% | car_norm=1, number_norm=2 |
| 027 | control | 4.08% | 3.06% | +1.02% | car_norm=1, number_norm=2 |
| 028 | control | 32.31% | 32.31% | +0.00% | car_norm=2, number_norm=4 |
| 029 | control | 41.86% | 41.23% | +0.63% | car_norm=8, number_norm=9 |
| 030 | control | 51.02% | 51.02% | +0.00% | number_norm=2 |
| 031 | daily | 17.65% | 17.65% | +0.00% | number_norm=1 |
| 032 | control | 24.68% | 24.05% | +0.63% | car_norm=2, number_norm=4 |
| 033 | control | 42.24% | 41.55% | +0.69% | car_norm=1, number_norm=14 |
| 034 | door | 30.11% | 30.11% | +0.00% | number_norm=2 |
| 035 | control | 40.38% | 40.77% | -0.38% | car_norm=2, number_norm=5 |
| 036 | track | 32.56% | 32.56% | +0.00% | number_norm=1 |
| 037 | control | 48.08% | 49.62% | -1.53% | car_norm=7, number_norm=3 |
| 038 | door | 47.87% | 48.23% | -0.35% | car_norm=2 |
| 039 | control | 30.89% | 33.33% | -2.44% | car_norm=2, number_norm=2 |
| 040 | control | 46.58% | 46.58% | +0.00% | car_norm=3, number_norm=1 |
| 041 | control | 40.30% | 41.79% | -1.49% | car_norm=1, number_norm=2 |
| 042 | control | 50.00% | 50.00% | +0.00% | car_norm=2, number_norm=3 |
| 043 | daily | 27.94% | 29.41% | -1.47% | number_norm=2 |
| 044 | control | 37.14% | 34.76% | +2.38% | car_norm=1, number_norm=6 |
| 045 | door | 58.86% | 58.66% | +0.20% | car_norm=4, number_norm=3 |
| 046 | control | 32.35% | 32.35% | +0.00% | — |
| 047 | control | 63.52% | 63.10% | +0.42% | car_norm=3, number_norm=6 |
| 048 | daily | 18.00% | 18.00% | +0.00% | car_norm=1 |
| 049 | daily | 29.92% | 33.86% | -3.94% | car_norm=2, number_norm=2 |
| 050 | control | 46.64% | 46.64% | +0.00% | car_norm=2, number_norm=2 |
| 051 | daily | 2.78% | 0.00% | +2.78% | car_norm=1 |
| 052 | daily | 31.68% | 35.40% | -3.73% | number_norm=8 |
| 053 | daily | 17.89% | 17.89% | +0.00% | car_norm=1, number_norm=2 |
| 054 | control | 38.36% | 37.44% | +0.91% | car_norm=4, number_norm=5 |
| 055 | daily | 30.00% | 26.00% | +4.00% | car_norm=1, number_norm=2 |
| 056 | daily | 22.22% | 19.44% | +2.78% | car_norm=2, number_norm=1 |
| 057 | daily | 14.61% | 16.85% | -2.25% | car_norm=2, number_norm=2 |
| 058 | daily | 28.57% | 21.43% | +7.14% | car_norm=1, number_norm=2 |
| 059 | daily | 36.02% | 34.95% | +1.08% | car_norm=1, number_norm=5 |
| 060 | daily | 0.00% | 0.00% | +0.00% | — |
| 061 | daily | 20.63% | 19.05% | +1.59% | number_norm=2 |
| 062 | daily | 18.46% | 18.46% | +0.00% | number_norm=3 |
| 063 | daily | 78.46% | 78.46% | +0.00% | number_norm=2 |