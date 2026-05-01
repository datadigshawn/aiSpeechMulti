# 黃金語料集批次評測報告

- **時間**: 20260501_225945
- **引擎**: `sensevoice_ft_r32_full`
- **後處理**: ['car_norm', 'dict', 'llm']
- **樣本**: 63/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **29.50%** |
| 平均 CER (final) | **28.12%** |
| 平均改善         | **+1.38%** |
| 平均 WER (final) | 43.19% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 22 | 35.71% | 35.44% | +0.27% |
| daily | 29 | 23.04% | 22.14% | +0.90% |
| door | 4 | 38.50% | 34.43% | +4.06% |
| emergency | 1 | 27.40% | 27.40% | +0.00% |
| track | 6 | 28.89% | 26.65% | +2.23% |
| train | 1 | 50.00% | 25.00% | +25.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 33.33% | 33.33% | +0.00% | number_norm=2, llm=1 |
| 002 | daily | 26.32% | 21.05% | +5.26% | number_norm=2 |
| 003 | track | 33.33% | 33.33% | +0.00% | car_norm=1, number_norm=2, llm=1 |
| 004 | track | 34.78% | 33.04% | +1.74% | number_norm=4, llm=6 |
| 005 | daily | 52.38% | 52.38% | +0.00% | llm=1 |
| 006 | door | 17.14% | 8.57% | +8.57% | number_norm=2, llm=3 |
| 007 | train | 50.00% | 25.00% | +25.00% | llm=2 |
| 008 | track | 34.85% | 25.76% | +9.09% | car_norm=2, number_norm=2, dict=2, llm=3 |
| 009 | daily | 10.71% | 0.00% | +10.71% | car_norm=1, number_norm=2, llm=1 |
| 010 | control | 13.49% | 14.29% | -0.79% | number_norm=2, llm=4 |
| 011 | control | 12.07% | 12.93% | -0.86% | number_norm=1, dict=1, llm=5 |
| 012 | emergency | 27.40% | 27.40% | +0.00% | car_norm=1, number_norm=3, llm=11 |
| 013 | track | 13.10% | 7.14% | +5.95% | number_norm=4, llm=3 |
| 014 | track | 24.72% | 28.09% | -3.37% | car_norm=2, number_norm=3, llm=2 |
| 015 | daily | 10.53% | 7.89% | +2.63% | car_norm=1, number_norm=1, llm=3 |
| 016 | daily | 15.79% | 13.16% | +2.63% | number_norm=2, dict=1, llm=1 |
| 017 | daily | 21.62% | 20.27% | +1.35% | car_norm=1, number_norm=3, dict=1, llm=2 |
| 018 | daily | 9.52% | 9.52% | +0.00% | number_norm=5, llm=4 |
| 019 | daily | 25.71% | 28.57% | -2.86% | car_norm=1, number_norm=3, llm=3 |
| 020 | daily | 12.50% | 6.25% | +6.25% | number_norm=1 |
| 021 | control | 29.23% | 27.69% | +1.54% | car_norm=1, number_norm=4, llm=5 |
| 022 | control | 27.56% | 25.33% | +2.22% | car_norm=2, number_norm=3, dict=3, llm=16 |
| 023 | control | 32.80% | 33.60% | -0.80% | number_norm=2, llm=4 |
| 024 | daily | 27.50% | 30.00% | -2.50% | car_norm=1, number_norm=1, llm=2 |
| 025 | daily | 15.62% | 12.50% | +3.12% | car_norm=1, number_norm=2 |
| 026 | daily | 11.90% | 16.67% | -4.76% | car_norm=1, number_norm=2, llm=2 |
| 027 | control | 4.08% | 3.06% | +1.02% | car_norm=1, number_norm=2 |
| 028 | control | 32.31% | 32.31% | +0.00% | car_norm=2, number_norm=4 |
| 029 | control | 41.86% | 41.65% | +0.21% | car_norm=8, number_norm=9, llm=11 |
| 030 | control | 51.02% | 51.43% | -0.41% | number_norm=2, llm=5 |
| 031 | daily | 17.65% | 14.71% | +2.94% | number_norm=1, dict=1, llm=4 |
| 032 | control | 24.68% | 22.15% | +2.53% | car_norm=2, number_norm=4, llm=3 |
| 033 | control | 42.24% | 40.34% | +1.90% | car_norm=1, number_norm=14, llm=6 |
| 034 | door | 30.11% | 26.14% | +3.98% | number_norm=2, llm=10 |
| 035 | control | 40.38% | 40.77% | -0.38% | car_norm=2, number_norm=5, llm=4 |
| 036 | track | 32.56% | 32.56% | +0.00% | number_norm=1, dict=1, llm=3 |
| 037 | control | 48.08% | 48.59% | -0.51% | car_norm=7, number_norm=3, llm=8 |
| 038 | door | 47.87% | 45.74% | +2.13% | car_norm=2, dict=1, llm=6 |
| 039 | control | 30.89% | 31.71% | -0.81% | car_norm=2, number_norm=2, llm=6 |
| 040 | control | 46.58% | 46.12% | +0.46% | car_norm=3, number_norm=1, llm=4 |
| 041 | control | 40.30% | 41.79% | -1.49% | car_norm=1, number_norm=2, dict=1, llm=2 |
| 042 | control | 50.00% | 50.00% | +0.00% | car_norm=2, number_norm=3, dict=3, llm=5 |
| 043 | daily | 27.94% | 25.00% | +2.94% | number_norm=2, llm=2 |
| 044 | control | 37.14% | 35.24% | +1.90% | car_norm=1, number_norm=6, dict=3, llm=7 |
| 045 | door | 58.86% | 57.28% | +1.57% | car_norm=4, number_norm=3, dict=2, llm=5 |
| 046 | control | 32.35% | 32.35% | +0.00% | — |
| 047 | control | 63.52% | 64.99% | -1.47% | car_norm=3, number_norm=6, dict=1, llm=14 |
| 048 | daily | 18.00% | 18.00% | +0.00% | car_norm=1, dict=2, llm=1 |
| 049 | daily | 29.92% | 36.22% | -6.30% | car_norm=2, number_norm=2, dict=3, llm=4 |
| 050 | control | 46.64% | 44.96% | +1.68% | car_norm=2, number_norm=2, llm=6 |
| 051 | daily | 2.78% | 8.33% | -5.56% | car_norm=1, dict=1, llm=1 |
| 052 | daily | 31.68% | 32.30% | -0.62% | number_norm=8, llm=5 |
| 053 | daily | 17.89% | 18.95% | -1.05% | car_norm=1, number_norm=2, dict=3, llm=5 |
| 054 | control | 38.36% | 38.36% | +0.00% | car_norm=4, number_norm=5, dict=3, llm=3 |
| 055 | daily | 30.00% | 32.00% | -2.00% | car_norm=1, number_norm=2, dict=1, llm=4 |
| 056 | daily | 22.22% | 19.44% | +2.78% | car_norm=2, number_norm=1, dict=3, llm=2 |
| 057 | daily | 14.61% | 15.73% | -1.12% | car_norm=2, number_norm=2, dict=2, llm=3 |
| 058 | daily | 28.57% | 21.43% | +7.14% | car_norm=1, number_norm=2 |
| 059 | daily | 36.02% | 35.48% | +0.54% | car_norm=1, number_norm=5, dict=1, llm=6 |
| 060 | daily | 0.00% | 0.00% | +0.00% | — |
| 061 | daily | 20.63% | 19.05% | +1.59% | number_norm=2, llm=3 |
| 062 | daily | 18.46% | 15.38% | +3.08% | number_norm=3, dict=2, llm=3 |
| 063 | daily | 78.46% | 78.46% | +0.00% | number_norm=2, llm=2 |