# 黃金語料集批次評測報告

- **時間**: 20260429_093934
- **引擎**: `gemini25pro`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 55/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **49.34%** |
| 平均 CER (final) | **48.35%** |
| 平均改善         | **+0.99%** |
| 平均 WER (final) | 62.78% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 19 | 38.08% | 35.47% | +2.60% |
| daily | 26 | 59.64% | 59.50% | +0.14% |
| door | 4 | 35.28% | 35.28% | +0.00% |
| emergency | 1 | 38.36% | 38.36% | +0.00% |
| track | 4 | 41.31% | 40.93% | +0.38% |
| train | 1 | 95.00% | 95.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 62.96% | 62.96% | +0.00% | — |
| 002 | daily | 89.47% | 89.47% | +0.00% | — |
| 003 | track | 41.67% | 41.67% | +0.00% | number_norm=1 |
| 004 | track | 45.22% | 46.09% | -0.87% | term_blacklist=1, number_norm=6 |
| 005 | daily | 69.05% | 73.81% | -4.76% | term_blacklist=1 |
| 006 | door | 42.86% | 42.86% | +0.00% | number_norm=2 |
| 007 | train | 95.00% | 95.00% | +0.00% | — |
| 008 | track | — | — | — | ❌ STT cache not found |
| 009 | daily | 42.86% | 42.86% | +0.00% | number_norm=1 |
| 010 | control | 31.75% | 30.16% | +1.59% | number_norm=7 |
| 011 | control | 25.00% | 25.00% | +0.00% | car_norm=3, number_norm=1 |
| 012 | emergency | 38.36% | 38.36% | +0.00% | number_norm=2 |
| 013 | track | 34.52% | 32.14% | +2.38% | term_blacklist=1 |
| 014 | track | 43.82% | 43.82% | +0.00% | number_norm=4 |
| 015 | daily | 76.32% | 76.32% | +0.00% | — |
| 016 | daily | 78.95% | 78.95% | +0.00% | — |
| 017 | daily | 56.76% | 56.76% | +0.00% | number_norm=2 |
| 018 | daily | 42.86% | 42.86% | +0.00% | number_norm=3 |
| 019 | daily | 60.00% | 60.00% | +0.00% | number_norm=2 |
| 020 | daily | 81.25% | 81.25% | +0.00% | — |
| 021 | control | 44.62% | 36.92% | +7.69% | term_blacklist=1, car_norm=1, number_norm=2 |
| 022 | control | 21.78% | 19.11% | +2.67% | number_norm=6, dict=2 |
| 023 | control | 37.60% | 34.40% | +3.20% | term_blacklist=1, number_norm=1 |
| 024 | daily | — | — | — | ❌ STT cache not found |
| 025 | daily | 53.12% | 53.12% | +0.00% | number_norm=1 |
| 026 | daily | 50.00% | 50.00% | +0.00% | car_norm=1, number_norm=1 |
| 027 | control | 8.16% | 7.14% | +1.02% | number_norm=1 |
| 028 | control | 64.62% | 58.46% | +6.15% | car_norm=2, number_norm=2 |
| 029 | control | 27.91% | 27.27% | +0.63% | car_norm=3, number_norm=4 |
| 030 | control | 42.04% | 42.04% | +0.00% | car_norm=1, number_norm=5 |
| 031 | daily | 55.88% | 55.88% | +0.00% | — |
| 032 | control | 39.87% | 37.97% | +1.90% | car_norm=5, number_norm=3 |
| 033 | control | 24.31% | 23.45% | +0.86% | car_norm=1, number_norm=15 |
| 034 | door | 25.00% | 25.00% | +0.00% | number_norm=1 |
| 035 | control | 56.92% | 56.54% | +0.38% | dict=1 |
| 036 | track | — | — | — | ❌ STT cache not found |
| 037 | control | 33.50% | 33.25% | +0.26% | car_norm=1, number_norm=1 |
| 038 | door | 37.23% | 37.23% | +0.00% | number_norm=3 |
| 039 | control | 56.10% | 56.10% | +0.00% | term_blacklist=1 |
| 040 | control | 44.75% | 44.75% | +0.00% | number_norm=1 |
| 041 | control | — | — | — | ❌ STT cache not found |
| 042 | control | — | — | — | ❌ STT cache not found |
| 043 | daily | 63.24% | 63.24% | +0.00% | — |
| 044 | control | 30.95% | 29.52% | +1.43% | car_norm=2, number_norm=4, dict=3 |
| 045 | door | 36.02% | 36.02% | +0.00% | dict=1 |
| 046 | control | — | — | — | ❌ STT cache not found |
| 047 | control | 44.44% | 37.11% | +7.34% | term_blacklist=1, car_norm=2, number_norm=17, dict=1 |
| 048 | daily | 54.00% | 54.00% | +0.00% | dict=1 |
| 049 | daily | 52.76% | 52.76% | +0.00% | number_norm=1, dict=4 |
| 050 | control | 51.68% | 38.24% | +13.45% | term_blacklist=2, car_norm=2, number_norm=2 |
| 051 | daily | 38.89% | 36.11% | +2.78% | car_norm=1 |
| 052 | daily | 54.66% | 54.04% | +0.62% | number_norm=1 |
| 053 | daily | 47.37% | 47.37% | +0.00% | number_norm=2, dict=1 |
| 054 | control | 37.44% | 36.53% | +0.91% | car_norm=2, number_norm=5 |
| 055 | daily | 54.00% | 54.00% | +0.00% | number_norm=1 |
| 056 | daily | 34.72% | 33.33% | +1.39% | car_norm=1, number_norm=1, dict=1 |
| 057 | daily | 30.34% | 30.34% | +0.00% | car_norm=2, number_norm=2, dict=1 |
| 058 | daily | 53.57% | 50.00% | +3.57% | number_norm=2 |
| 059 | daily | — | — | — | ❌ STT cache not found |
| 060 | daily | — | — | — | ❌ STT cache not found |
| 061 | daily | 46.03% | 46.03% | +0.00% | number_norm=1 |
| 062 | daily | 33.85% | 33.85% | +0.00% | number_norm=2, dict=2 |
| 063 | daily | 167.69% | 167.69% | +0.00% | number_norm=2 |