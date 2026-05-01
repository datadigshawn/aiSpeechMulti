# 黃金語料集批次評測報告

- **時間**: 20260501_232032
- **引擎**: `ensemble_ft_gemini`
- **後處理**: （無）
- **樣本**: 55/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **30.89%** |
| 平均 CER (final) | **29.98%** |
| 平均改善         | **+0.91%** |
| 平均 WER (final) | 41.74% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 19 | 37.18% | 36.38% | +0.80% |
| daily | 26 | 26.83% | 25.82% | +1.00% |
| door | 4 | 40.87% | 40.16% | +0.72% |
| emergency | 1 | 5.48% | 5.48% | +0.00% |
| track | 4 | 25.30% | 23.82% | +1.47% |
| train | 1 | 25.00% | 25.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 48.15% | 48.15% | +0.00% | — |
| 002 | daily | 26.32% | 21.05% | +5.26% | number_norm=2 |
| 003 | track | 33.33% | 33.33% | +0.00% | number_norm=1 |
| 004 | track | 31.30% | 31.30% | +0.00% | term_blacklist=1, number_norm=4 |
| 005 | daily | 69.05% | 69.05% | +0.00% | — |
| 006 | door | 11.43% | 8.57% | +2.86% | number_norm=2 |
| 007 | train | 25.00% | 25.00% | +0.00% | — |
| 008 | track | — | — | — | ❌ STT cache not found |
| 009 | daily | 10.71% | 7.14% | +3.57% | number_norm=2 |
| 010 | control | 13.49% | 13.49% | +0.00% | number_norm=2 |
| 011 | control | 5.17% | 5.17% | +0.00% | number_norm=1 |
| 012 | emergency | 5.48% | 5.48% | +0.00% | number_norm=2 |
| 013 | track | 10.71% | 5.95% | +4.76% | number_norm=4 |
| 014 | track | 25.84% | 24.72% | +1.12% | number_norm=4 |
| 015 | daily | 5.26% | 5.26% | +0.00% | number_norm=1 |
| 016 | daily | 13.16% | 13.16% | +0.00% | number_norm=2 |
| 017 | daily | 25.68% | 24.32% | +1.35% | number_norm=3 |
| 018 | daily | 5.95% | 3.57% | +2.38% | number_norm=5 |
| 019 | daily | 32.86% | 31.43% | +1.43% | number_norm=3 |
| 020 | daily | 12.50% | 6.25% | +6.25% | number_norm=1 |
| 021 | control | 20.00% | 17.69% | +2.31% | number_norm=5 |
| 022 | control | 28.89% | 26.22% | +2.67% | number_norm=6 |
| 023 | control | 21.60% | 21.60% | +0.00% | number_norm=2 |
| 024 | daily | — | — | — | ❌ STT cache not found |
| 025 | daily | 15.62% | 12.50% | +3.12% | number_norm=2 |
| 026 | daily | 14.29% | 11.90% | +2.38% | number_norm=2 |
| 027 | control | 3.06% | 2.04% | +1.02% | number_norm=2 |
| 028 | control | 35.38% | 32.31% | +3.08% | number_norm=4 |
| 029 | control | 68.92% | 68.92% | +0.00% | number_norm=2 |
| 030 | control | 43.67% | 43.67% | +0.00% | number_norm=4 |
| 031 | daily | 14.71% | 14.71% | +0.00% | number_norm=1 |
| 032 | control | 24.05% | 22.15% | +1.90% | number_norm=5 |
| 033 | control | 69.83% | 69.83% | +0.00% | number_norm=5 |
| 034 | door | 26.14% | 26.14% | +0.00% | number_norm=1 |
| 035 | control | 46.15% | 46.15% | +0.00% | number_norm=6 |
| 036 | track | — | — | — | ❌ STT cache not found |
| 037 | control | 66.50% | 66.50% | +0.00% | number_norm=2 |
| 038 | door | 52.48% | 52.48% | +0.00% | number_norm=2 |
| 039 | control | 30.89% | 30.08% | +0.81% | number_norm=2 |
| 040 | control | 42.92% | 42.92% | +0.00% | number_norm=1 |
| 041 | control | — | — | — | ❌ STT cache not found |
| 042 | control | — | — | — | ❌ STT cache not found |
| 043 | daily | 23.53% | 25.00% | -1.47% | number_norm=2 |
| 044 | control | 24.76% | 22.86% | +1.90% | number_norm=6 |
| 045 | door | 73.43% | 73.43% | +0.00% | — |
| 046 | control | — | — | — | ❌ STT cache not found |
| 047 | control | 86.37% | 86.16% | +0.21% | number_norm=1 |
| 048 | daily | 20.00% | 20.00% | +0.00% | — |
| 049 | daily | 29.92% | 29.92% | +0.00% | number_norm=1 |
| 050 | control | 38.24% | 36.97% | +1.26% | number_norm=4 |
| 051 | daily | 2.78% | 2.78% | +0.00% | — |
| 052 | daily | 29.81% | 33.54% | -3.73% | number_norm=8 |
| 053 | daily | 17.89% | 17.89% | +0.00% | number_norm=2 |
| 054 | control | 36.53% | 36.53% | +0.00% | number_norm=5 |
| 055 | daily | 34.00% | 32.00% | +2.00% | number_norm=2 |
| 056 | daily | 20.83% | 20.83% | +0.00% | number_norm=1 |
| 057 | daily | 16.85% | 16.85% | +0.00% | number_norm=2 |
| 058 | daily | 28.57% | 25.00% | +3.57% | number_norm=2 |
| 059 | daily | — | — | — | ❌ STT cache not found |
| 060 | daily | — | — | — | ❌ STT cache not found |
| 061 | daily | 20.63% | 20.63% | +0.00% | number_norm=1 |
| 062 | daily | 15.38% | 15.38% | +0.00% | number_norm=2 |
| 063 | daily | 143.08% | 143.08% | +0.00% | number_norm=3 |