# 黃金語料集批次評測報告

- **時間**: 20260531_174240
- **引擎**: `sensevoice_ft_v2_157gt`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 19/157 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **26.20%** |
| 平均 CER (final) | **26.32%** |
| 平均改善         | **-0.11%** |
| 平均 WER (final) | 45.86% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 5 | 29.62% | 29.41% | +0.21% |
| daily | 7 | 28.36% | 28.71% | -0.35% |
| door | 3 | 22.58% | 22.82% | -0.24% |
| emergency | 1 | 21.74% | 21.74% | +0.00% |
| track | 2 | 18.40% | 18.40% | +0.00% |
| train | 1 | 25.00% | 25.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | — | — | — | ❌ STT cache not found |
| 002 | daily | 31.58% | 36.84% | -5.26% | number_norm=2 |
| 003 | track | — | — | — | ❌ STT cache not found |
| 004 | track | — | — | — | ❌ STT cache not found |
| 005 | daily | — | — | — | ❌ STT cache not found |
| 006 | door | — | — | — | ❌ STT cache not found |
| 007 | train | 25.00% | 25.00% | +0.00% | — |
| 008 | track | — | — | — | ❌ STT cache not found |
| 009 | daily | — | — | — | ❌ STT cache not found |
| 010 | control | — | — | — | ❌ STT cache not found |
| 011 | control | — | — | — | ❌ STT cache not found |
| 012 | emergency | — | — | — | ❌ STT cache not found |
| 013 | track | — | — | — | ❌ STT cache not found |
| 014 | track | — | — | — | ❌ STT cache not found |
| 015 | daily | — | — | — | ❌ STT cache not found |
| 016 | daily | — | — | — | ❌ STT cache not found |
| 017 | daily | — | — | — | ❌ STT cache not found |
| 018 | daily | 14.29% | 14.29% | +0.00% | number_norm=3 |
| 019 | daily | — | — | — | ❌ STT cache not found |
| 020 | daily | — | — | — | ❌ STT cache not found |
| 021 | control | — | — | — | ❌ STT cache not found |
| 022 | control | — | — | — | ❌ STT cache not found |
| 023 | control | — | — | — | ❌ STT cache not found |
| 024 | daily | — | — | — | ❌ STT cache not found |
| 025 | daily | — | — | — | ❌ STT cache not found |
| 026 | daily | — | — | — | ❌ STT cache not found |
| 027 | control | — | — | — | ❌ STT cache not found |
| 028 | control | — | — | — | ❌ STT cache not found |
| 029 | control | — | — | — | ❌ STT cache not found |
| 030 | control | — | — | — | ❌ STT cache not found |
| 031 | daily | — | — | — | ❌ STT cache not found |
| 032 | control | — | — | — | ❌ STT cache not found |
| 033 | control | 28.97% | 28.79% | +0.17% | car_norm=1, number_norm=11, dict=1 |
| 034 | door | — | — | — | ❌ STT cache not found |
| 035 | control | — | — | — | ❌ STT cache not found |
| 036 | track | — | — | — | ❌ STT cache not found |
| 037 | control | — | — | — | ❌ STT cache not found |
| 038 | door | — | — | — | ❌ STT cache not found |
| 039 | control | — | — | — | ❌ STT cache not found |
| 040 | control | — | — | — | ❌ STT cache not found |
| 041 | control | — | — | — | ❌ STT cache not found |
| 042 | control | — | — | — | ❌ STT cache not found |
| 043 | daily | 30.88% | 30.88% | +0.00% | number_norm=1 |
| 044 | control | 34.76% | 32.86% | +1.90% | car_norm=1, number_norm=6, dict=3 |
| 045 | door | — | — | — | ❌ STT cache not found |
| 046 | control | — | — | — | ❌ STT cache not found |
| 047 | control | — | — | — | ❌ STT cache not found |
| 048 | daily | 28.00% | 28.00% | +0.00% | dict=1 |
| 049 | daily | — | — | — | ❌ STT cache not found |
| 050 | control | — | — | — | ❌ STT cache not found |
| 051 | daily | 16.67% | 13.89% | +2.78% | car_norm=1, number_norm=1 |
| 052 | daily | — | — | — | ❌ STT cache not found |
| 053 | daily | — | — | — | ❌ STT cache not found |
| 054 | control | — | — | — | ❌ STT cache not found |
| 055 | daily | — | — | — | ❌ STT cache not found |
| 056 | daily | — | — | — | ❌ STT cache not found |
| 057 | daily | — | — | — | ❌ STT cache not found |
| 058 | daily | — | — | — | ❌ STT cache not found |
| 059 | daily | — | — | — | ❌ STT cache not found |
| 060 | daily | — | — | — | ❌ STT cache not found |
| 061 | daily | — | — | — | ❌ STT cache not found |
| 062 | daily | — | — | — | ❌ STT cache not found |
| 063 | daily | — | — | — | ❌ STT cache not found |
| A001 | emergency | — | — | — | ❌ STT cache not found |
| A002 | emergency | — | — | — | ❌ STT cache not found |
| A003 | emergency | — | — | — | ❌ STT cache not found |
| A004 | emergency | — | — | — | ❌ STT cache not found |
| A005 | emergency | — | — | — | ❌ STT cache not found |
| A007 | emergency | — | — | — | ❌ STT cache not found |
| A008 | emergency | — | — | — | ❌ STT cache not found |
| A009 | emergency | — | — | — | ❌ STT cache not found |
| A012 | emergency | — | — | — | ❌ STT cache not found |
| A013 | emergency | — | — | — | ❌ STT cache not found |
| A014 | emergency | — | — | — | ❌ STT cache not found |
| G0001 | emergency | 21.74% | 21.74% | +0.00% | — |
| G0002 | daily | — | — | — | ❌ STT cache not found |
| G0003 | door | — | — | — | ❌ STT cache not found |
| G0004 | daily | — | — | — | ❌ STT cache not found |
| G0005 | track | — | — | — | ❌ STT cache not found |
| G0006 | door | — | — | — | ❌ STT cache not found |
| G0007 | track | — | — | — | ❌ STT cache not found |
| G0008 | door | — | — | — | ❌ STT cache not found |
| G0009 | daily | — | — | — | ❌ STT cache not found |
| G0010 | door | — | — | — | ❌ STT cache not found |
| G0011 | door | 30.00% | 30.00% | +0.00% | car_norm=1, dict=1 |
| G0012 | door | — | — | — | ❌ STT cache not found |
| G0013 | emergency | — | — | — | ❌ STT cache not found |
| G0014 | daily | — | — | — | ❌ STT cache not found |
| G0015 | daily | — | — | — | ❌ STT cache not found |
| G0016 | daily | — | — | — | ❌ STT cache not found |
| G0017 | daily | — | — | — | ❌ STT cache not found |
| G0018 | daily | — | — | — | ❌ STT cache not found |
| G0019 | daily | — | — | — | ❌ STT cache not found |
| G0020 | track | — | — | — | ❌ STT cache not found |
| G0021 | emergency | — | — | — | ❌ STT cache not found |
| G0022 | daily | — | — | — | ❌ STT cache not found |
| G0023 | emergency | — | — | — | ❌ STT cache not found |
| G0024 | emergency | — | — | — | ❌ STT cache not found |
| G0025 | daily | — | — | — | ❌ STT cache not found |
| G0026 | track | — | — | — | ❌ STT cache not found |
| G0027 | daily | — | — | — | ❌ STT cache not found |
| G0028 | control | — | — | — | ❌ STT cache not found |
| G0029 | track | 12.50% | 12.50% | +0.00% | dict=2 |
| G0030 | track | — | — | — | ❌ STT cache not found |
| G0031 | door | — | — | — | ❌ STT cache not found |
| G0032 | control | — | — | — | ❌ STT cache not found |
| G0033 | daily | 33.33% | 33.33% | +0.00% | car_norm=1 |
| G0034 | control | 18.52% | 18.52% | +0.00% | — |
| G0035 | control | — | — | — | ❌ STT cache not found |
| G0036 | control | — | — | — | ❌ STT cache not found |
| G0037 | emergency | — | — | — | ❌ STT cache not found |
| G0038 | emergency | — | — | — | ❌ STT cache not found |
| G0039 | control | — | — | — | ❌ STT cache not found |
| G0040 | emergency | — | — | — | ❌ STT cache not found |
| G0041 | control | — | — | — | ❌ STT cache not found |
| G0042 | control | 44.19% | 44.19% | +0.00% | number_norm=7, dict=1 |
| G0043 | daily | — | — | — | ❌ STT cache not found |
| G0044 | control | — | — | — | ❌ STT cache not found |
| G0045 | control | — | — | — | ❌ STT cache not found |
| G0046 | daily | — | — | — | ❌ STT cache not found |
| G0047 | none | — | — | — | ❌ STT cache not found |
| G0048 | daily | — | — | — | ❌ STT cache not found |
| G0049 | daily | — | — | — | ❌ STT cache not found |
| G0050 | daily | — | — | — | ❌ STT cache not found |
| G0051 | daily | — | — | — | ❌ STT cache not found |
| G0052 | daily | 43.75% | 43.75% | +0.00% | number_norm=1 |
| G0053 | control | — | — | — | ❌ STT cache not found |
| G0054 | control | — | — | — | ❌ STT cache not found |
| G0055 | control | — | — | — | ❌ STT cache not found |
| G0056 | daily | — | — | — | ❌ STT cache not found |
| G0057 | daily | — | — | — | ❌ STT cache not found |
| G0058 | daily | — | — | — | ❌ STT cache not found |
| G0059 | daily | — | — | — | ❌ STT cache not found |
| G0060 | daily | — | — | — | ❌ STT cache not found |
| G0061 | daily | — | — | — | ❌ STT cache not found |
| G0062 | daily | — | — | — | ❌ STT cache not found |
| G0063 | control | 21.65% | 22.68% | -1.03% | number_norm=1 |
| G0064 | track | — | — | — | ❌ STT cache not found |
| G0065 | door | — | — | — | ❌ STT cache not found |
| G0066 | door | 15.79% | 15.79% | +0.00% | dict=2 |
| G0067 | door | — | — | — | ❌ STT cache not found |
| G0068 | door | 21.94% | 22.66% | -0.72% | car_norm=2, number_norm=6, dict=2 |
| G0069 | track | 24.29% | 24.29% | +0.00% | dict=2 |
| G0070 | track | — | — | — | ❌ STT cache not found |
| G0071 | daily | — | — | — | ❌ STT cache not found |
| G0072 | control | — | — | — | ❌ STT cache not found |
| G0073 | daily | — | — | — | ❌ STT cache not found |
| G0074 | control | — | — | — | ❌ STT cache not found |
| G0075 | control | — | — | — | ❌ STT cache not found |
| G0076 | control | — | — | — | ❌ STT cache not found |
| G0077 | control | — | — | — | ❌ STT cache not found |
| G0078 | control | — | — | — | ❌ STT cache not found |
| G0079 | daily | — | — | — | ❌ STT cache not found |
| G0080 | door | — | — | — | ❌ STT cache not found |
| G0081 | door | — | — | — | ❌ STT cache not found |
| G0082 | control | — | — | — | ❌ STT cache not found |
| G0083 | door | — | — | — | ❌ STT cache not found |