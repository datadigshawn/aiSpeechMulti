# 黃金語料集批次評測報告

- **時間**: 20260603_164638
- **引擎**: `whisper_medium`
- **後處理**: （無）
- **樣本**: 21/159 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **69.66%** |
| 平均 CER (final) | **69.16%** |
| 平均改善         | **+0.50%** |
| 平均 WER (final) | 80.17% |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 5 | 60.13% | 59.33% | +0.79% |
| daily | 7 | 77.17% | 76.42% | +0.75% |
| door | 3 | 63.52% | 63.52% | +0.00% |
| emergency | 3 | 71.97% | 72.56% | -0.60% |
| track | 2 | 57.81% | 56.25% | +1.56% |
| train | 1 | 100.00% | 100.00% | +0.00% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 001 | daily | — | — | — | ❌ STT cache not found |
| 002 | daily | 105.26% | 100.00% | +5.26% | number_norm=1 |
| 003 | track | — | — | — | ❌ STT cache not found |
| 004 | track | — | — | — | ❌ STT cache not found |
| 005 | daily | — | — | — | ❌ STT cache not found |
| 006 | door | — | — | — | ❌ STT cache not found |
| 007 | train | 100.00% | 100.00% | +0.00% | — |
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
| 018 | daily | 65.48% | 65.48% | +0.00% | number_norm=2 |
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
| 033 | control | 56.90% | 54.83% | +2.07% | number_norm=23 |
| 034 | door | — | — | — | ❌ STT cache not found |
| 035 | control | — | — | — | ❌ STT cache not found |
| 036 | track | — | — | — | ❌ STT cache not found |
| 037 | control | — | — | — | ❌ STT cache not found |
| 038 | door | — | — | — | ❌ STT cache not found |
| 039 | control | — | — | — | ❌ STT cache not found |
| 040 | control | — | — | — | ❌ STT cache not found |
| 041 | control | — | — | — | ❌ STT cache not found |
| 042 | control | — | — | — | ❌ STT cache not found |
| 043 | daily | 69.12% | 69.12% | +0.00% | — |
| 044 | control | 47.14% | 45.24% | +1.90% | number_norm=4 |
| 045 | door | — | — | — | ❌ STT cache not found |
| 046 | control | — | — | — | ❌ STT cache not found |
| 047 | control | — | — | — | ❌ STT cache not found |
| 048 | daily | 42.00% | 42.00% | +0.00% | — |
| 049 | daily | — | — | — | ❌ STT cache not found |
| 050 | control | — | — | — | ❌ STT cache not found |
| 051 | daily | 58.33% | 58.33% | +0.00% | — |
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
| A003 | emergency | 82.09% | 82.09% | +0.00% | — |
| A004 | emergency | 40.48% | 42.26% | -1.79% | number_norm=1 |
| A005 | emergency | 93.33% | 93.33% | +0.00% | — |
| A007 | emergency | — | — | — | ❌ STT cache not found |
| A008 | emergency | — | — | — | ❌ STT cache not found |
| A009 | emergency | — | — | — | ❌ STT cache not found |
| A010 | emergency | — | — | — | ❌ STT cache not found |
| A011 | emergency | — | — | — | ❌ STT cache not found |
| A012 | emergency | — | — | — | ❌ STT cache not found |
| A013 | emergency | — | — | — | ❌ STT cache not found |
| A014 | emergency | — | — | — | ❌ STT cache not found |
| G0001 | emergency | — | — | — | ❌ STT cache not found |
| G0002 | daily | — | — | — | ❌ STT cache not found |
| G0003 | door | — | — | — | ❌ STT cache not found |
| G0004 | daily | — | — | — | ❌ STT cache not found |
| G0005 | track | — | — | — | ❌ STT cache not found |
| G0006 | door | — | — | — | ❌ STT cache not found |
| G0007 | track | — | — | — | ❌ STT cache not found |
| G0008 | door | — | — | — | ❌ STT cache not found |
| G0009 | daily | — | — | — | ❌ STT cache not found |
| G0010 | door | — | — | — | ❌ STT cache not found |
| G0011 | door | 83.33% | 83.33% | +0.00% | — |
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
| G0029 | track | 65.62% | 62.50% | +3.12% | term_blacklist=1 |
| G0030 | track | — | — | — | ❌ STT cache not found |
| G0031 | door | — | — | — | ❌ STT cache not found |
| G0032 | control | — | — | — | ❌ STT cache not found |
| G0033 | daily | 100.00% | 100.00% | +0.00% | — |
| G0034 | control | 88.89% | 88.89% | +0.00% | — |
| G0035 | control | — | — | — | ❌ STT cache not found |
| G0036 | control | — | — | — | ❌ STT cache not found |
| G0037 | emergency | — | — | — | ❌ STT cache not found |
| G0038 | emergency | — | — | — | ❌ STT cache not found |
| G0039 | control | — | — | — | ❌ STT cache not found |
| G0040 | emergency | — | — | — | ❌ STT cache not found |
| G0041 | control | — | — | — | ❌ STT cache not found |
| G0042 | control | 70.60% | 70.60% | +0.00% | number_norm=11 |
| G0043 | daily | — | — | — | ❌ STT cache not found |
| G0044 | control | — | — | — | ❌ STT cache not found |
| G0045 | control | — | — | — | ❌ STT cache not found |
| G0046 | daily | — | — | — | ❌ STT cache not found |
| G0047 | none | — | — | — | ❌ STT cache not found |
| G0048 | daily | — | — | — | ❌ STT cache not found |
| G0049 | daily | — | — | — | ❌ STT cache not found |
| G0050 | daily | — | — | — | ❌ STT cache not found |
| G0051 | daily | — | — | — | ❌ STT cache not found |
| G0052 | daily | 100.00% | 100.00% | +0.00% | — |
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
| G0063 | control | 37.11% | 37.11% | +0.00% | — |
| G0064 | track | — | — | — | ❌ STT cache not found |
| G0065 | door | — | — | — | ❌ STT cache not found |
| G0066 | door | 42.11% | 42.11% | +0.00% | — |
| G0067 | door | — | — | — | ❌ STT cache not found |
| G0068 | door | 65.11% | 65.11% | +0.00% | number_norm=3 |
| G0069 | track | 50.00% | 50.00% | +0.00% | — |
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