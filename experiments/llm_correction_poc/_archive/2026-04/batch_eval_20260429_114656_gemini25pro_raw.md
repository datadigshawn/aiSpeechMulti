# 黃金語料集批次評測報告

- **時間**: 20260429_114656
- **引擎**: `gemini25pro`
- **後處理**: （無）
- **樣本**: 55/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **48.90%** |
| 平均 CER (final) | **48.36%** |
| 平均改善         | **+0.53%** |
| 平均 WER (final) | 62.07% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 18 | 39.72% | 38.34% | +1.38% |
| daily | 27 | 56.09% | 56.01% | +0.08% |
| door | 4 | 38.62% | 38.62% | +0.00% |
| emergency | 1 | 36.99% | 36.99% | +0.00% |
| track | 4 | 44.62% | 44.02% | +0.60% |
| train | 1 | 90.00% | 90.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 59.26% | 59.26% | +0.00% | — |
| 002 | daily | 84.21% | 84.21% | +0.00% | number_norm=1 |
| 003 | track | 50.00% | 50.00% | +0.00% | number_norm=1 |
| 004 | track | 40.87% | 40.87% | +0.00% | term_blacklist=1, number_norm=4 |
| 005 | daily | 69.05% | 71.43% | -2.38% | term_blacklist=1 |
| 006 | door | 37.14% | 37.14% | +0.00% | number_norm=1 |
| 007 | train | 90.00% | 90.00% | +0.00% | — |
| 008 | track | — | — | — | ❌ STT cache not found |
| 009 | daily | — | — | — | ❌ STT cache not found |
| 010 | control | 38.89% | 38.89% | +0.00% | number_norm=2 |
| 011 | control | 18.97% | 18.97% | +0.00% | number_norm=1 |
| 012 | emergency | 36.99% | 36.99% | +0.00% | number_norm=2 |
| 013 | track | 39.29% | 36.90% | +2.38% | term_blacklist=1 |
| 014 | track | 48.31% | 48.31% | +0.00% | number_norm=4 |
| 015 | daily | 65.79% | 65.79% | +0.00% | term_blacklist=1 |
| 016 | daily | 71.05% | 71.05% | +0.00% | number_norm=1 |
| 017 | daily | 55.41% | 55.41% | +0.00% | — |
| 018 | daily | 42.86% | 42.86% | +0.00% | number_norm=3 |
| 019 | daily | 52.86% | 50.00% | +2.86% | number_norm=2 |
| 020 | daily | 87.50% | 87.50% | +0.00% | — |
| 021 | control | 44.62% | 44.62% | +0.00% | number_norm=2 |
| 022 | control | 23.56% | 20.89% | +2.67% | number_norm=7 |
| 023 | control | 40.00% | 40.00% | +0.00% | number_norm=1 |
| 024 | daily | 47.50% | 47.50% | +0.00% | — |
| 025 | daily | 53.12% | 53.12% | +0.00% | number_norm=1 |
| 026 | daily | 45.24% | 45.24% | +0.00% | number_norm=1 |
| 027 | control | 6.12% | 5.10% | +1.02% | number_norm=1 |
| 028 | control | 70.77% | 70.77% | +0.00% | number_norm=2 |
| 029 | control | 39.32% | 39.32% | +0.00% | number_norm=5 |
| 030 | control | 37.55% | 37.55% | +0.00% | number_norm=5 |
| 031 | daily | 52.94% | 52.94% | +0.00% | — |
| 032 | control | 38.61% | 37.97% | +0.63% | number_norm=3 |
| 033 | control | 34.83% | 34.83% | +0.00% | number_norm=9 |
| 034 | door | 25.00% | 25.00% | +0.00% | number_norm=2 |
| 035 | control | 50.38% | 50.38% | +0.00% | — |
| 036 | track | — | — | — | ❌ STT cache not found |
| 037 | control | — | — | — | ❌ STT cache not found |
| 038 | door | 40.78% | 40.78% | +0.00% | number_norm=3 |
| 039 | control | — | — | — | ❌ STT cache not found |
| 040 | control | — | — | — | ❌ STT cache not found |
| 041 | control | 64.18% | 64.18% | +0.00% | number_norm=1 |
| 042 | control | — | — | — | ❌ STT cache not found |
| 043 | daily | 58.82% | 57.35% | +1.47% | number_norm=1 |
| 044 | control | 27.14% | 25.24% | +1.90% | number_norm=4 |
| 045 | door | 51.57% | 51.57% | +0.00% | number_norm=12 |
| 046 | control | 61.76% | 61.76% | +0.00% | — |
| 047 | control | 45.91% | 45.28% | +0.63% | number_norm=5 |
| 048 | daily | 44.00% | 44.00% | +0.00% | — |
| 049 | daily | — | — | — | ❌ STT cache not found |
| 050 | control | 33.61% | 15.55% | +18.07% | term_blacklist=2, number_norm=5 |
| 051 | daily | 44.44% | 44.44% | +0.00% | — |
| 052 | daily | 49.07% | 50.93% | -1.86% | number_norm=5 |
| 053 | daily | 47.37% | 47.37% | +0.00% | number_norm=2 |
| 054 | control | 38.81% | 38.81% | +0.00% | number_norm=5 |
| 055 | daily | 56.00% | 56.00% | +0.00% | number_norm=1 |
| 056 | daily | 33.33% | 33.33% | +0.00% | number_norm=1 |
| 057 | daily | 29.21% | 29.21% | +0.00% | — |
| 058 | daily | 42.86% | 39.29% | +3.57% | number_norm=2 |
| 059 | daily | 51.61% | 51.61% | +0.00% | number_norm=2 |
| 060 | daily | 0.00% | 0.00% | +0.00% | — |
| 061 | daily | 55.56% | 55.56% | +0.00% | number_norm=1 |
| 062 | daily | 41.54% | 41.54% | +0.00% | number_norm=2 |
| 063 | daily | 173.85% | 175.38% | -1.54% | number_norm=3 |