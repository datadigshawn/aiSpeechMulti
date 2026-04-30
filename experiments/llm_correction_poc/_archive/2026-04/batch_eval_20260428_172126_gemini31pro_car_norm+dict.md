# 黃金語料集批次評測報告

- **時間**: 20260428_172126
- **引擎**: `gemini31pro`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 62/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **69.48%** |
| 平均 CER (final) | **68.52%** |
| 平均改善         | **+0.95%** |
| 平均 WER (final) | 74.14% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 22 | 106.80% | 105.35% | +1.45% |
| daily | 28 | 52.89% | 52.21% | +0.68% |
| door | 4 | 40.44% | 39.76% | +0.68% |
| emergency | 1 | 22.60% | 22.60% | +0.00% |
| track | 6 | 39.59% | 38.69% | +0.90% |
| train | 1 | 55.00% | 55.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 51.85% | 48.15% | +3.70% | number_norm=1, dict=1 |
| 002 | daily | 100.00% | 100.00% | +0.00% | car_norm=1, number_norm=1 |
| 003 | track | 29.17% | 29.17% | +0.00% | car_norm=1, number_norm=1 |
| 004 | track | 36.52% | 36.52% | +0.00% | number_norm=5 |
| 005 | daily | 61.90% | 61.90% | +0.00% | — |
| 006 | door | 37.14% | 37.14% | +0.00% | number_norm=1 |
| 007 | train | 55.00% | 55.00% | +0.00% | — |
| 008 | track | 46.97% | 43.94% | +3.03% | car_norm=2, number_norm=1 |
| 009 | daily | 53.57% | 53.57% | +0.00% | — |
| 010 | control | 19.05% | 16.67% | +2.38% | number_norm=5 |
| 011 | control | 19.83% | 18.97% | +0.86% | number_norm=1, dict=1 |
| 012 | emergency | 22.60% | 22.60% | +0.00% | number_norm=2 |
| 013 | track | 30.95% | 28.57% | +2.38% | number_norm=2, dict=1 |
| 014 | track | 40.45% | 40.45% | +0.00% | car_norm=3, number_norm=5, dict=1 |
| 015 | daily | 86.84% | 89.47% | -2.63% | car_norm=1 |
| 016 | daily | 73.68% | 73.68% | +0.00% | — |
| 017 | daily | 33.78% | 29.73% | +4.05% | number_norm=6, dict=1 |
| 018 | daily | 36.90% | 36.90% | +0.00% | number_norm=3 |
| 019 | daily | 47.14% | 47.14% | +0.00% | — |
| 020 | daily | 62.50% | 62.50% | +0.00% | car_norm=1 |
| 021 | control | 26.92% | 21.54% | +5.38% | car_norm=1, number_norm=6 |
| 022 | control | 21.78% | 20.44% | +1.33% | number_norm=3, dict=4 |
| 023 | control | 20.00% | 20.00% | +0.00% | number_norm=1 |
| 024 | daily | 65.00% | 65.00% | +0.00% | number_norm=1 |
| 025 | daily | 50.00% | 50.00% | +0.00% | car_norm=1, number_norm=1 |
| 026 | daily | 26.19% | 21.43% | +4.76% | car_norm=1, number_norm=3 |
| 027 | control | 15.31% | 14.29% | +1.02% | number_norm=1 |
| 028 | control | 52.31% | 52.31% | +0.00% | car_norm=2, number_norm=2 |
| 029 | control | 30.87% | 30.87% | +0.00% | car_norm=5, number_norm=4, dict=1 |
| 030 | control | 42.86% | 42.86% | +0.00% | — |
| 031 | daily | 38.24% | 38.24% | +0.00% | — |
| 032 | control | 26.58% | 24.68% | +1.90% | car_norm=3, number_norm=2 |
| 033 | control | 24.31% | 22.59% | +1.72% | car_norm=2, number_norm=8 |
| 034 | door | 35.80% | 34.66% | +1.14% | number_norm=3, dict=1 |
| 035 | control | 46.92% | 43.85% | +3.08% | car_norm=3, number_norm=7, dict=1 |
| 036 | track | 53.49% | 53.49% | +0.00% | number_norm=1 |
| 037 | control | 32.74% | 31.20% | +1.53% | car_norm=11 |
| 038 | door | 35.46% | 35.46% | +0.00% | number_norm=3 |
| 039 | control | 1629.27% | 1630.08% | -0.81% | dict=2 |
| 040 | control | 34.25% | 34.25% | +0.00% | number_norm=1 |
| 041 | control | 64.18% | 64.18% | +0.00% | car_norm=1, number_norm=1 |
| 042 | control | 34.67% | 31.67% | +3.00% | car_norm=4, number_norm=3 |
| 043 | daily | 42.65% | 41.18% | +1.47% | number_norm=1 |
| 044 | control | 22.38% | 19.05% | +3.33% | car_norm=2, number_norm=7, dict=4 |
| 045 | door | 53.35% | 51.77% | +1.57% | car_norm=9 |
| 046 | control | 50.00% | 50.00% | +0.00% | — |
| 047 | control | 42.77% | 40.46% | +2.31% | number_norm=23, dict=1 |
| 048 | daily | 24.00% | 22.00% | +2.00% | car_norm=1, dict=1 |
| 049 | daily | 49.61% | 50.39% | -0.79% | car_norm=3, number_norm=2, dict=2 |
| 050 | control | 42.86% | 41.60% | +1.26% | car_norm=3 |
| 051 | daily | 41.67% | 38.89% | +2.78% | car_norm=1 |
| 052 | daily | 49.69% | 48.45% | +1.24% | number_norm=2 |
| 053 | daily | 36.84% | 35.79% | +1.05% | car_norm=1, number_norm=2, dict=1 |
| 054 | control | 49.77% | 46.12% | +3.65% | car_norm=4, number_norm=7 |
| 055 | daily | 46.00% | 46.00% | +0.00% | number_norm=1 |
| 056 | daily | 43.06% | 41.67% | +1.39% | car_norm=2, number_norm=3, dict=1 |
| 057 | daily | 28.09% | 28.09% | +0.00% | car_norm=2, number_norm=2, dict=1 |
| 058 | daily | 46.43% | 46.43% | +0.00% | car_norm=1, number_norm=1 |
| 059 | daily | 31.72% | 31.72% | +0.00% | number_norm=2 |
| 060 | daily | — | — | — | ❌ STT cache not found |
| 061 | daily | 42.86% | 42.86% | +0.00% | number_norm=1 |
| 062 | daily | 26.15% | 26.15% | +0.00% | number_norm=2, dict=1 |
| 063 | daily | 184.62% | 184.62% | +0.00% | number_norm=1 |