# 黃金語料集批次評測報告

- **時間**: 20260501_214541
- **引擎**: `sensevoice_ft_r32`
- **後處理**: ['car_norm']
- **樣本**: 10/63 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **30.78%** |
| 平均 CER (final) | **28.68%** |
| 平均改善         | **+2.10%** |
| 平均 WER (final) | 45.56% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 3 | 34.35% | 34.04% | +0.31% |
| daily | 4 | 25.65% | 21.08% | +4.57% |
| emergency | 1 | 27.40% | 26.71% | +0.68% |
| track | 1 | 24.72% | 23.60% | +1.12% |
| train | 1 | 50.00% | 50.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | 33.33% | 33.33% | +0.00% | number_norm=2 |
| 002 | daily | — | — | — | ❌ STT cache not found |
| 003 | track | — | — | — | ❌ STT cache not found |
| 004 | track | — | — | — | ❌ STT cache not found |
| 005 | daily | — | — | — | ❌ STT cache not found |
| 006 | door | — | — | — | ❌ STT cache not found |
| 007 | train | 50.00% | 50.00% | +0.00% | — |
| 008 | track | — | — | — | ❌ STT cache not found |
| 009 | daily | 10.71% | 3.57% | +7.14% | car_norm=1, number_norm=2 |
| 010 | control | — | — | — | ❌ STT cache not found |
| 011 | control | — | — | — | ❌ STT cache not found |
| 012 | emergency | 27.40% | 26.71% | +0.68% | car_norm=1, number_norm=3 |
| 013 | track | — | — | — | ❌ STT cache not found |
| 014 | track | 24.72% | 23.60% | +1.12% | car_norm=2, number_norm=3 |
| 015 | daily | — | — | — | ❌ STT cache not found |
| 016 | daily | — | — | — | ❌ STT cache not found |
| 017 | daily | — | — | — | ❌ STT cache not found |
| 018 | daily | — | — | — | ❌ STT cache not found |
| 019 | daily | — | — | — | ❌ STT cache not found |
| 020 | daily | — | — | — | ❌ STT cache not found |
| 021 | control | — | — | — | ❌ STT cache not found |
| 022 | control | 27.11% | 25.33% | +1.78% | car_norm=2, number_norm=4 |
| 023 | control | — | — | — | ❌ STT cache not found |
| 024 | daily | — | — | — | ❌ STT cache not found |
| 025 | daily | — | — | — | ❌ STT cache not found |
| 026 | daily | — | — | — | ❌ STT cache not found |
| 027 | control | — | — | — | ❌ STT cache not found |
| 028 | control | 32.31% | 33.85% | -1.54% | car_norm=2, number_norm=3 |
| 029 | control | — | — | — | ❌ STT cache not found |
| 030 | control | — | — | — | ❌ STT cache not found |
| 031 | daily | — | — | — | ❌ STT cache not found |
| 032 | control | — | — | — | ❌ STT cache not found |
| 033 | control | 43.62% | 42.93% | +0.69% | car_norm=1, number_norm=13 |
| 034 | door | — | — | — | ❌ STT cache not found |
| 035 | control | — | — | — | ❌ STT cache not found |
| 036 | track | — | — | — | ❌ STT cache not found |
| 037 | control | — | — | — | ❌ STT cache not found |
| 038 | door | — | — | — | ❌ STT cache not found |
| 039 | control | — | — | — | ❌ STT cache not found |
| 040 | control | — | — | — | ❌ STT cache not found |
| 041 | control | — | — | — | ❌ STT cache not found |
| 042 | control | — | — | — | ❌ STT cache not found |
| 043 | daily | — | — | — | ❌ STT cache not found |
| 044 | control | — | — | — | ❌ STT cache not found |
| 045 | door | — | — | — | ❌ STT cache not found |
| 046 | control | — | — | — | ❌ STT cache not found |
| 047 | control | — | — | — | ❌ STT cache not found |
| 048 | daily | — | — | — | ❌ STT cache not found |
| 049 | daily | — | — | — | ❌ STT cache not found |
| 050 | control | — | — | — | ❌ STT cache not found |
| 051 | daily | — | — | — | ❌ STT cache not found |
| 052 | daily | — | — | — | ❌ STT cache not found |
| 053 | daily | — | — | — | ❌ STT cache not found |
| 054 | control | — | — | — | ❌ STT cache not found |
| 055 | daily | 30.00% | 26.00% | +4.00% | car_norm=1, number_norm=2 |
| 056 | daily | — | — | — | ❌ STT cache not found |
| 057 | daily | — | — | — | ❌ STT cache not found |
| 058 | daily | 28.57% | 21.43% | +7.14% | car_norm=1, number_norm=2 |
| 059 | daily | — | — | — | ❌ STT cache not found |
| 060 | daily | — | — | — | ❌ STT cache not found |
| 061 | daily | — | — | — | ❌ STT cache not found |
| 062 | daily | — | — | — | ❌ STT cache not found |
| 063 | daily | — | — | — | ❌ STT cache not found |