# 黃金語料集批次評測報告

- **時間**: 20260430_114809
- **引擎**: `ensemble_v1`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 55/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **50.77%** |
| 平均 CER (final) | **50.00%** |
| 平均改善         | **+0.77%** |
| 平均 WER (final) | 62.84% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 19 | 44.31% | 43.10% | +1.21% |
| daily | 26 | 57.53% | 56.97% | +0.56% |
| door | 4 | 43.46% | 43.46% | +0.00% |
| emergency | 1 | 38.36% | 38.36% | +0.00% |
| track | 4 | 36.90% | 35.71% | +1.19% |
| train | 1 | 95.00% | 95.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 51.85% | 51.85% | +0.00% | — |
| 002 | daily | 78.95% | 78.95% | +0.00% | number_norm=1 |
| 003 | track | 45.83% | 45.83% | +0.00% | number_norm=1 |
| 004 | track | 40.87% | 40.87% | +0.00% | term_blacklist=1, number_norm=5 |
| 005 | daily | 69.05% | 69.05% | +0.00% | — |
| 006 | door | 42.86% | 42.86% | +0.00% | number_norm=2 |
| 007 | train | 95.00% | 95.00% | +0.00% | — |
| 008 | track | — | — | — | ❌ STT cache not found |
| 009 | daily | 46.43% | 46.43% | +0.00% | number_norm=1 |
| 010 | control | 26.98% | 25.40% | +1.59% | number_norm=7 |
| 011 | control | 25.00% | 25.00% | +0.00% | car_norm=3, number_norm=1 |
| 012 | emergency | 38.36% | 38.36% | +0.00% | number_norm=2 |
| 013 | track | 23.81% | 19.05% | +4.76% | number_norm=4 |
| 014 | track | 37.08% | 37.08% | +0.00% | number_norm=4 |
| 015 | daily | 65.79% | 65.79% | +0.00% | — |
| 016 | daily | 78.95% | 78.95% | +0.00% | — |
| 017 | daily | 62.16% | 59.46% | +2.70% | number_norm=2 |
| 018 | daily | 39.29% | 38.10% | +1.19% | number_norm=3, dict=1 |
| 019 | daily | 60.00% | 60.00% | +0.00% | number_norm=2 |
| 020 | daily | 81.25% | 81.25% | +0.00% | — |
| 021 | control | 36.92% | 36.15% | +0.77% | car_norm=1, number_norm=3 |
| 022 | control | 21.78% | 19.11% | +2.67% | number_norm=6, dict=2 |
| 023 | control | 36.00% | 36.00% | +0.00% | number_norm=1 |
| 024 | daily | — | — | — | ❌ STT cache not found |
| 025 | daily | 50.00% | 50.00% | +0.00% | car_norm=1, number_norm=1 |
| 026 | daily | 42.86% | 40.48% | +2.38% | car_norm=1, number_norm=2 |
| 027 | control | 9.18% | 8.16% | +1.02% | number_norm=1 |
| 028 | control | 56.92% | 49.23% | +7.69% | car_norm=2, number_norm=4 |
| 029 | control | 69.98% | 69.56% | +0.42% | car_norm=2, number_norm=1 |
| 030 | control | 42.04% | 42.04% | +0.00% | car_norm=1, number_norm=5 |
| 031 | daily | 58.82% | 58.82% | +0.00% | — |
| 032 | control | 37.97% | 36.08% | +1.90% | car_norm=5, number_norm=3 |
| 033 | control | 70.17% | 70.17% | +0.00% | number_norm=5 |
| 034 | door | 23.30% | 23.30% | +0.00% | number_norm=1 |
| 035 | control | 56.92% | 56.54% | +0.38% | dict=1 |
| 036 | track | — | — | — | ❌ STT cache not found |
| 037 | control | 63.17% | 62.92% | +0.26% | car_norm=1, number_norm=1 |
| 038 | door | 37.23% | 37.23% | +0.00% | number_norm=3 |
| 039 | control | 55.28% | 55.28% | +0.00% | — |
| 040 | control | 40.64% | 40.64% | +0.00% | number_norm=1 |
| 041 | control | — | — | — | ❌ STT cache not found |
| 042 | control | — | — | — | ❌ STT cache not found |
| 043 | daily | 58.82% | 58.82% | +0.00% | — |
| 044 | control | 28.10% | 25.71% | +2.38% | car_norm=2, number_norm=6, dict=4 |
| 045 | door | 70.47% | 70.47% | +0.00% | dict=1 |
| 046 | control | — | — | — | ❌ STT cache not found |
| 047 | control | 75.05% | 74.63% | +0.42% | number_norm=5 |
| 048 | daily | 54.00% | 54.00% | +0.00% | dict=1 |
| 049 | daily | 51.97% | 51.97% | +0.00% | number_norm=1, dict=4 |
| 050 | control | 50.00% | 47.48% | +2.52% | car_norm=4, number_norm=2, dict=1 |
| 051 | daily | 38.89% | 36.11% | +2.78% | car_norm=1 |
| 052 | daily | 53.42% | 52.80% | +0.62% | number_norm=1 |
| 053 | daily | 47.37% | 47.37% | +0.00% | number_norm=2, dict=1 |
| 054 | control | 39.73% | 38.81% | +0.91% | car_norm=2, number_norm=5 |
| 055 | daily | 52.00% | 52.00% | +0.00% | — |
| 056 | daily | 33.33% | 31.94% | +1.39% | car_norm=1, number_norm=1, dict=1 |
| 057 | daily | 30.34% | 30.34% | +0.00% | car_norm=2, number_norm=2, dict=1 |
| 058 | daily | 53.57% | 50.00% | +3.57% | number_norm=2 |
| 059 | daily | — | — | — | ❌ STT cache not found |
| 060 | daily | — | — | — | ❌ STT cache not found |
| 061 | daily | 44.44% | 44.44% | +0.00% | number_norm=1 |
| 062 | daily | 30.77% | 30.77% | +0.00% | number_norm=2, dict=2 |
| 063 | daily | 161.54% | 161.54% | +0.00% | number_norm=2 |