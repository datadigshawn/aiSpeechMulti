# 黃金語料集批次評測報告

- **時間**: 20260430_144833
- **引擎**: `scribe`
- **後處理**: ['car_norm', 'dict', 'llm']
- **樣本**: 63/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **66.15%** |
| 平均 CER (final) | **62.43%** |
| 平均改善         | **+3.72%** |
| 平均 WER (final) | 76.80% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 22 | 58.23% | 54.71% | +3.51% |
| daily | 29 | 73.21% | 69.61% | +3.60% |
| door | 4 | 57.63% | 49.67% | +7.96% |
| emergency | 1 | 50.00% | 47.95% | +2.05% |
| track | 6 | 63.79% | 60.62% | +3.18% |
| train | 1 | 100.00% | 100.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 48.15% | 48.15% | +0.00% | llm=2 |
| 002 | daily | 100.00% | 94.74% | +5.26% | number_norm=1, llm=1 |
| 003 | track | 75.00% | 70.83% | +4.17% | number_norm=1, dict=1, llm=5 |
| 004 | track | 51.30% | 46.09% | +5.22% | dict=1, llm=27 |
| 005 | daily | 104.76% | 100.00% | +4.76% | llm=4 |
| 006 | door | 68.57% | 60.00% | +8.57% | dict=1, llm=4 |
| 007 | train | 100.00% | 100.00% | +0.00% | — |
| 008 | track | 75.76% | 74.24% | +1.52% | number_norm=1, llm=8 |
| 009 | daily | 78.57% | 67.86% | +10.71% | number_norm=1, dict=1, llm=7 |
| 010 | control | 42.06% | 32.54% | +9.52% | number_norm=2, dict=1, contextual=1, llm=12 |
| 011 | control | 40.52% | 34.48% | +6.03% | dict=2, llm=2 |
| 012 | emergency | 50.00% | 47.95% | +2.05% | number_norm=1, llm=19 |
| 013 | track | 34.52% | 30.95% | +3.57% | llm=9 |
| 014 | track | 76.40% | 74.16% | +2.25% | number_norm=2, llm=5 |
| 015 | daily | 100.00% | 100.00% | +0.00% | llm=5 |
| 016 | daily | 94.74% | 94.74% | +0.00% | llm=3 |
| 017 | daily | 67.57% | 64.86% | +2.70% | number_norm=2, llm=11 |
| 018 | daily | 48.81% | 38.10% | +10.71% | number_norm=3, dict=1, contextual=1, llm=7 |
| 019 | daily | 67.14% | 67.14% | +0.00% | llm=12 |
| 020 | daily | 100.00% | 100.00% | +0.00% | llm=3 |
| 021 | control | 57.69% | 56.15% | +1.54% | number_norm=3, llm=11 |
| 022 | control | 37.78% | 34.22% | +3.56% | dict=2, llm=22 |
| 023 | control | 44.80% | 44.80% | +0.00% | number_norm=1, llm=20 |
| 024 | daily | 62.50% | 60.00% | +2.50% | number_norm=1, llm=8 |
| 025 | daily | 75.00% | 65.62% | +9.38% | number_norm=1, dict=1, llm=2 |
| 026 | daily | 66.67% | 64.29% | +2.38% | dict=1, llm=6 |
| 027 | control | 27.55% | 24.49% | +3.06% | number_norm=1, dict=1, llm=6 |
| 028 | control | 76.92% | 76.92% | +0.00% | llm=10 |
| 029 | control | 53.07% | 52.22% | +0.85% | number_norm=1, dict=2, llm=57 |
| 030 | control | 72.65% | 71.02% | +1.63% | number_norm=7, llm=32 |
| 031 | daily | 67.65% | 67.65% | +0.00% | llm=10 |
| 032 | control | 59.49% | 53.80% | +5.70% | number_norm=2, dict=1, llm=13 |
| 033 | control | 46.90% | 42.07% | +4.83% | number_norm=8, dict=1, llm=29 |
| 034 | door | 44.89% | 32.95% | +11.93% | term_blacklist=1, number_norm=1, llm=16 |
| 035 | control | 74.23% | 70.00% | +4.23% | number_norm=6, dict=1, llm=30 |
| 036 | track | 69.77% | 67.44% | +2.33% | number_norm=1, dict=1, llm=8 |
| 037 | control | 60.61% | 56.78% | +3.84% | dict=4, llm=43 |
| 038 | door | 70.21% | 67.73% | +2.48% | dict=2, llm=28 |
| 039 | control | 71.54% | 71.54% | +0.00% | llm=13 |
| 040 | control | 51.14% | 48.40% | +2.74% | number_norm=1, dict=1, llm=8 |
| 041 | control | 88.06% | 85.07% | +2.99% | dict=1, llm=9 |
| 042 | control | 66.67% | 54.33% | +12.33% | llm=53 |
| 043 | daily | 75.00% | 73.53% | +1.47% | number_norm=1, llm=18 |
| 044 | control | 48.57% | 42.86% | +5.71% | number_norm=2, dict=5, llm=26 |
| 045 | door | 46.85% | 37.99% | +8.86% | term_blacklist=1, dict=2, llm=18 |
| 046 | control | 85.29% | 85.29% | +0.00% | llm=2 |
| 047 | control | 60.17% | 56.81% | +3.35% | number_norm=11, dict=2, llm=43 |
| 048 | daily | 62.00% | 60.00% | +2.00% | llm=8 |
| 049 | daily | 68.50% | 63.78% | +4.72% | number_norm=1, dict=4, llm=12 |
| 050 | control | 50.42% | 49.16% | +1.26% | dict=1, llm=20 |
| 051 | daily | 63.89% | 63.89% | +0.00% | llm=6 |
| 052 | daily | 72.05% | 67.08% | +4.97% | number_norm=2, dict=1, llm=15 |
| 053 | daily | 62.11% | 60.00% | +2.11% | dict=2, llm=10 |
| 054 | control | 64.84% | 60.73% | +4.11% | number_norm=4, dict=3, llm=24 |
| 055 | daily | 64.00% | 62.00% | +2.00% | number_norm=1, llm=7 |
| 056 | daily | 58.33% | 48.61% | +9.72% | number_norm=1, dict=3, llm=13 |
| 057 | daily | 66.29% | 62.92% | +3.37% | dict=1, llm=10 |
| 058 | daily | 75.00% | 67.86% | +7.14% | number_norm=1, dict=1, llm=3 |
| 059 | daily | 62.90% | 53.76% | +9.14% | car_norm=2, number_norm=3, dict=1, llm=3 |
| 060 | daily | 0.00% | 0.00% | +0.00% | — |
| 061 | daily | 71.43% | 71.43% | +0.00% | — |
| 062 | daily | 43.08% | 35.38% | +7.69% | number_norm=4, dict=1, llm=2 |
| 063 | daily | 196.92% | 195.38% | +1.54% | number_norm=2, dict=1 |