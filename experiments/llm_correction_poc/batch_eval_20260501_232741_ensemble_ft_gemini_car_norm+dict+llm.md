# 黃金語料集批次評測報告

- **時間**: 20260501_232741
- **引擎**: `ensemble_ft_gemini`
- **後處理**: ['car_norm', 'dict', 'llm']
- **樣本**: 55/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **30.89%** |
| 平均 CER (final) | **30.33%** |
| 平均改善         | **+0.56%** |
| 平均 WER (final) | 39.88% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 19 | 37.18% | 37.16% | +0.02% |
| daily | 26 | 26.83% | 25.94% | +0.88% |
| door | 4 | 40.87% | 40.06% | +0.81% |
| emergency | 1 | 5.48% | 7.53% | -2.05% |
| track | 4 | 25.30% | 23.76% | +1.54% |
| train | 1 | 25.00% | 25.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 48.15% | 48.15% | +0.00% | — |
| 002 | daily | 26.32% | 21.05% | +5.26% | number_norm=2 |
| 003 | track | 33.33% | 33.33% | +0.00% | car_norm=1, number_norm=1 |
| 004 | track | 31.30% | 32.17% | -0.87% | term_blacklist=1, number_norm=4, llm=1 |
| 005 | daily | 69.05% | 69.05% | +0.00% | — |
| 006 | door | 11.43% | 8.57% | +2.86% | number_norm=2 |
| 007 | train | 25.00% | 25.00% | +0.00% | — |
| 008 | track | — | — | — | ❌ STT cache not found |
| 009 | daily | 10.71% | 0.00% | +10.71% | car_norm=1, number_norm=2, llm=1 |
| 010 | control | 13.49% | 15.87% | -2.38% | number_norm=2, llm=1 |
| 011 | control | 5.17% | 5.17% | +0.00% | number_norm=1 |
| 012 | emergency | 5.48% | 7.53% | -2.05% | number_norm=2, llm=1 |
| 013 | track | 10.71% | 5.95% | +4.76% | number_norm=4 |
| 014 | track | 25.84% | 23.60% | +2.25% | car_norm=2, number_norm=4 |
| 015 | daily | 5.26% | 5.26% | +0.00% | car_norm=1, number_norm=1, dict=1 |
| 016 | daily | 13.16% | 13.16% | +0.00% | number_norm=2, dict=1 |
| 017 | daily | 25.68% | 24.32% | +1.35% | number_norm=3, dict=1 |
| 018 | daily | 5.95% | 7.14% | -1.19% | number_norm=5, llm=1 |
| 019 | daily | 32.86% | 31.43% | +1.43% | car_norm=1, number_norm=3 |
| 020 | daily | 12.50% | 6.25% | +6.25% | number_norm=1 |
| 021 | control | 20.00% | 17.69% | +2.31% | car_norm=1, number_norm=5 |
| 022 | control | 28.89% | 26.22% | +2.67% | car_norm=1, number_norm=6, dict=2, llm=1 |
| 023 | control | 21.60% | 21.60% | +0.00% | number_norm=2 |
| 024 | daily | — | — | — | ❌ STT cache not found |
| 025 | daily | 15.62% | 12.50% | +3.12% | car_norm=1, number_norm=2 |
| 026 | daily | 14.29% | 9.52% | +4.76% | car_norm=1, number_norm=2 |
| 027 | control | 3.06% | 2.04% | +1.02% | car_norm=1, number_norm=2 |
| 028 | control | 35.38% | 35.38% | +0.00% | car_norm=2, number_norm=4 |
| 029 | control | 68.92% | 68.71% | +0.21% | car_norm=1, number_norm=2 |
| 030 | control | 43.67% | 43.67% | +0.00% | car_norm=1, number_norm=4 |
| 031 | daily | 14.71% | 14.71% | +0.00% | number_norm=1 |
| 032 | control | 24.05% | 20.25% | +3.80% | car_norm=4, number_norm=5, llm=1 |
| 033 | control | 69.83% | 69.83% | +0.00% | number_norm=5 |
| 034 | door | 26.14% | 26.14% | +0.00% | number_norm=1 |
| 035 | control | 46.15% | 46.15% | +0.00% | car_norm=3, number_norm=6 |
| 036 | track | — | — | — | ❌ STT cache not found |
| 037 | control | 66.50% | 66.24% | +0.26% | car_norm=1, number_norm=2 |
| 038 | door | 52.48% | 52.48% | +0.00% | number_norm=2 |
| 039 | control | 30.89% | 33.33% | -2.44% | car_norm=2, number_norm=2 |
| 040 | control | 42.92% | 41.55% | +1.37% | number_norm=1, llm=5 |
| 041 | control | — | — | — | ❌ STT cache not found |
| 042 | control | — | — | — | ❌ STT cache not found |
| 043 | daily | 23.53% | 25.00% | -1.47% | number_norm=2 |
| 044 | control | 24.76% | 22.38% | +2.38% | car_norm=2, number_norm=6, dict=4 |
| 045 | door | 73.43% | 73.03% | +0.39% | dict=1, llm=1 |
| 046 | control | — | — | — | ❌ STT cache not found |
| 047 | control | 86.37% | 96.02% | -9.64% | number_norm=1 |
| 048 | daily | 20.00% | 20.00% | +0.00% | car_norm=1, dict=1 |
| 049 | daily | 29.92% | 29.92% | +0.00% | number_norm=1, dict=4 |
| 050 | control | 38.24% | 38.24% | +0.00% | car_norm=2, number_norm=4 |
| 051 | daily | 2.78% | 8.33% | -5.56% | car_norm=1, dict=1, llm=1 |
| 052 | daily | 29.81% | 32.92% | -3.11% | number_norm=8, llm=1 |
| 053 | daily | 17.89% | 21.05% | -3.16% | car_norm=1, number_norm=2, dict=2, llm=1 |
| 054 | control | 36.53% | 35.62% | +0.91% | car_norm=2, number_norm=5, dict=3 |
| 055 | daily | 34.00% | 36.00% | -2.00% | car_norm=1, number_norm=2, dict=1, llm=1 |
| 056 | daily | 20.83% | 18.06% | +2.78% | car_norm=2, number_norm=1, dict=3 |
| 057 | daily | 16.85% | 20.22% | -3.37% | car_norm=2, number_norm=2, dict=2, llm=1 |
| 058 | daily | 28.57% | 21.43% | +7.14% | car_norm=1, number_norm=2 |
| 059 | daily | — | — | — | ❌ STT cache not found |
| 060 | daily | — | — | — | ❌ STT cache not found |
| 061 | daily | 20.63% | 20.63% | +0.00% | number_norm=1 |
| 062 | daily | 15.38% | 15.38% | +0.00% | number_norm=2, dict=2 |
| 063 | daily | 143.08% | 143.08% | +0.00% | number_norm=3 |