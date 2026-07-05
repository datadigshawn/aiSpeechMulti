# 黃金語料集批次評測報告

- **時間**: 20260705_175102
- **引擎**: `sensevoice_ft_v3c_chunk_filtered_Aseries`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 13/13 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **45.92%** |
| 平均 CER (final) | **45.97%** |
| 平均改善         | **-0.05%** |
| 平均 WER (final) | 58.51% |

## 🛡️ Regression guard（occurrence-weighted）

| 指標 | recall | hit/ref | 幻覺 |
|---|---|---|---|
| 關鍵詞 | **50.0%** | 2/4 | 0 |
| 站碼 | **100.0%** | 2/2 | 2 |
| 車廂號 | **n/a** | 0/0 | 1 |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| emergency | 13 | 45.92% | 45.97% | -0.05% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| A001 | emergency | 40.22% | 40.35% | -0.13% | car_norm=2, number_norm=2, dict=1 |
| A002 | emergency | 24.44% | 24.89% | -0.44% | number_norm=1 |
| A003 | emergency | 59.70% | 59.70% | +0.00% | — |
| A004 | emergency | 51.19% | 51.19% | +0.00% | car_norm=1, number_norm=1 |
| A005 | emergency | 76.67% | 76.67% | +0.00% | — |
| A007 | emergency | 52.35% | 52.35% | +0.00% | — |
| A008 | emergency | 42.13% | 42.13% | +0.00% | — |
| A009 | emergency | 48.15% | 48.15% | +0.00% | car_norm=1 |
| A010 | emergency | 52.57% | 52.57% | +0.00% | dict=1 |
| A011 | emergency | 30.00% | 30.00% | +0.00% | — |
| A012 | emergency | 52.06% | 52.18% | -0.12% | car_norm=1, number_norm=1, dict=1 |
| A013 | emergency | 33.33% | 33.33% | +0.00% | — |
| A014 | emergency | 34.13% | 34.13% | +0.00% | — |