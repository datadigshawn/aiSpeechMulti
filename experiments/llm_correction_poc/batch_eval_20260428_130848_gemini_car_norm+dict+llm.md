# 黃金語料集批次評測報告

- **時間**: 20260428_130848
- **引擎**: `gemini`
- **後處理**: ['car_norm', 'dict', 'llm']
- **樣本**: 62/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **177.69%** |
| 平均 CER (final) | **163.22%** |
| 平均改善         | **+14.46%** |
| 平均 WER (final) | 72.37% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 22 | 227.44% | 225.83% | +1.61% |
| daily | 28 | 159.49% | 159.66% | -0.17% |
| door | 4 | 270.09% | 55.88% | +214.21% |
| emergency | 1 | 50.00% | 48.63% | +1.37% |
| track | 6 | 53.62% | 52.35% | +1.27% |
| train | 1 | 95.00% | 95.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 70.37% | 70.37% | +0.00% | — |
| 002 | daily | 89.47% | 89.47% | +0.00% | — |
| 003 | track | 66.67% | 62.50% | +4.17% | number_norm=1 |
| 004 | track | 44.35% | 40.87% | +3.48% | term_blacklist=1, number_norm=5 |
| 005 | daily | 92.86% | 92.86% | +0.00% | — |
| 006 | door | 37.14% | 37.14% | +0.00% | llm=3 |
| 007 | train | 95.00% | 95.00% | +0.00% | — |
| 008 | track | 74.24% | 74.24% | +0.00% | — |
| 009 | daily | 46.43% | 46.43% | +0.00% | — |
| 010 | control | 50.00% | 48.41% | +1.59% | number_norm=2, llm=2 |
| 011 | control | 31.03% | 27.59% | +3.45% | car_norm=3, number_norm=4, llm=5 |
| 012 | emergency | 50.00% | 48.63% | +1.37% | number_norm=2, llm=1 |
| 013 | track | 34.52% | 34.52% | +0.00% | llm=2 |
| 014 | track | 43.82% | 43.82% | +0.00% | number_norm=2, llm=1 |
| 015 | daily | 78.95% | 81.58% | -2.63% | dict=2 |
| 016 | daily | 81.58% | 81.58% | +0.00% | — |
| 017 | daily | 52.70% | 52.70% | +0.00% | number_norm=2, llm=2 |
| 018 | daily | 47.62% | 47.62% | +0.00% | number_norm=3, llm=4 |
| 019 | daily | 74.29% | 74.29% | +0.00% | number_norm=2 |
| 020 | daily | 87.50% | 93.75% | -6.25% | llm=1 |
| 021 | control | 51.54% | 51.54% | +0.00% | llm=5 |
| 022 | control | 29.33% | 27.11% | +2.22% | car_norm=2, number_norm=7, dict=2, llm=1 |
| 023 | control | 44.00% | 43.20% | +0.80% | number_norm=1, llm=2 |
| 024 | daily | 75.00% | 75.00% | +0.00% | number_norm=1, dict=1 |
| 025 | daily | 59.38% | 59.38% | +0.00% | number_norm=1, llm=1 |
| 026 | daily | 54.76% | 54.76% | +0.00% | number_norm=1, llm=3 |
| 027 | control | 12.24% | 11.22% | +1.02% | number_norm=1, llm=1 |
| 028 | control | 81.54% | 78.46% | +3.08% | number_norm=2, llm=1 |
| 029 | control | 56.87% | 55.81% | +1.06% | car_norm=1, number_norm=3, dict=1, llm=2 |
| 030 | control | 54.69% | 53.88% | +0.82% | number_norm=2, llm=3 |
| 031 | daily | 55.88% | 55.88% | +0.00% | — |
| 032 | control | 52.53% | 50.00% | +2.53% | car_norm=3, number_norm=3 |
| 033 | control | 58.97% | 58.79% | +0.17% | car_norm=1, number_norm=5 |
| 034 | door | 34.09% | 33.52% | +0.57% | number_norm=1 |
| 035 | control | 72.31% | 69.23% | +3.08% | car_norm=2, number_norm=7, llm=2 |
| 036 | track | 58.14% | 58.14% | +0.00% | number_norm=1 |
| 037 | control | 47.57% | 47.06% | +0.51% | car_norm=1, number_norm=1, llm=5 |
| 038 | door | 949.29% | 93.62% | +855.67% | llm=1 |
| 039 | control | 73.98% | 73.98% | +0.00% | llm=8 |
| 040 | control | 43.84% | 43.84% | +0.00% | number_norm=1 |
| 041 | control | 3901.49% | 3901.49% | +0.00% | — |
| 042 | control | 55.33% | 53.67% | +1.67% | car_norm=2, number_norm=4, llm=4 |
| 043 | daily | 2561.76% | 2561.76% | +0.00% | — |
| 044 | control | 38.10% | 37.14% | +0.95% | car_norm=2, number_norm=3, dict=1 |
| 045 | door | 59.84% | 59.25% | +0.59% | car_norm=3 |
| 046 | control | 76.47% | 76.47% | +0.00% | — |
| 047 | control | 60.80% | 56.60% | +4.19% | car_norm=4, number_norm=17, dict=1 |
| 048 | daily | 54.00% | 54.00% | +0.00% | dict=1 |
| 049 | daily | 64.57% | 65.35% | -0.79% | number_norm=3, dict=1 |
| 050 | control | 55.88% | 52.52% | +3.36% | llm=6 |
| 051 | daily | 58.33% | 55.56% | +2.78% | car_norm=1 |
| 052 | daily | 53.42% | 53.42% | +0.00% | number_norm=2, llm=1 |
| 053 | daily | 55.79% | 53.68% | +2.11% | number_norm=2, dict=1 |
| 054 | control | 55.25% | 50.23% | +5.02% | car_norm=5, number_norm=4, llm=3 |
| 055 | daily | 54.00% | 54.00% | +0.00% | car_norm=1, number_norm=1, llm=1 |
| 056 | daily | 48.61% | 48.61% | +0.00% | number_norm=1, dict=1, llm=1 |
| 057 | daily | 168.54% | 167.42% | +1.12% | car_norm=2, number_norm=2, dict=3 |
| 058 | daily | 57.14% | 57.14% | +0.00% | car_norm=1 |
| 059 | daily | 54.84% | 54.30% | +0.54% | car_norm=1, number_norm=2 |
| 060 | daily | — | — | — | ❌ STT cache not found |
| 061 | daily | 57.14% | 57.14% | +0.00% | number_norm=1 |
| 062 | daily | 32.31% | 32.31% | +0.00% | number_norm=2, dict=1, llm=1 |
| 063 | daily | 178.46% | 180.00% | -1.54% | number_norm=1, llm=2 |