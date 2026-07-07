# 黃金語料集批次評測報告

- **時間**: 20260707_131933
- **引擎**: `sensevoice_ft_v2_157gt_batch01`
- **後處理**: ['car_norm', 'dict']
- **樣本**: 20/20 成功

## 📊 平均指標

| 指標 | 數值 |
|---|---|
| 平均 CER (raw)   | **27.48%** |
| 平均 CER (final) | **27.93%** |
| 平均改善         | **-0.45%** |
| 平均 WER (final) | 47.94% |

## 🛡️ Regression guard（occurrence-weighted）

| 指標 | recall | hit/ref | 幻覺 |
|---|---|---|---|
| 關鍵詞 | **66.7%** | 54/81 | 0 |
| 站碼 | **27.9%** | 31/111 | 59 |
| 車廂號 | **23.8%** | 15/63 | 31 |

## 📂 依事件類型分組

| 事件類型 | 段數 | CER raw | CER final | 改善 |
|---|---|---|---|---|
| control | 5 | 32.39% | 32.23% | +0.16% |
| door | 10 | 25.64% | 26.52% | -0.88% |
| emergency | 5 | 26.24% | 26.46% | -0.22% |

## 📋 各樣本詳細

| ID | 類型 | CER raw | CER final | 改善 | 修正項目 |
|---|---|---|---|---|---|
| 251209_水安宮旅客昏倒_185032_UltraLog063 | emergency | 32.67% | 33.66% | -0.99% | number_norm=8, dict=1 |
| 251209_水安宮旅客昏倒_185322_UltraLog063 | emergency | 15.44% | 16.18% | -0.74% | number_norm=5, dict=1, station_code=1 |
| 251209_水安宮旅客昏倒_185509_UltraLog063 | emergency | 25.64% | 25.00% | +0.64% | car_norm=1, number_norm=4, station_code=2 |
| 251209_水安宮旅客昏倒_190252_UltraLog006 | emergency | 28.88% | 28.88% | +0.00% | — |
| 251209_水安宮旅客昏倒_191505_UltraLog025 | emergency | 28.57% | 28.57% | +0.00% | — |
| 251216_九張犁車門連動_174436_UltraLog063 | door | 29.63% | 29.78% | -0.14% | car_norm=9, number_norm=18, dict=3, station_code=1 |
| 251216_九張犁車門連動_174813_UltraLog063 | door | 37.78% | 37.78% | +0.00% | number_norm=1 |
| 251216_九張犁車門連動_175200_UltraLog063 | door | 24.43% | 25.00% | -0.57% | number_norm=5, dict=1 |
| 251216_九張犁車門連動_175812_UltraLog063 | door | 25.20% | 25.20% | +0.00% | number_norm=2 |
| 251222_三軌電力異常_194517_UltraLog064 | control | 24.11% | 22.92% | +1.19% | car_norm=6, number_norm=15, dict=2, station_code=4 |
| 251222_三軌電力異常_200202_UltraLog063 | control | 32.96% | 32.67% | +0.28% | car_norm=4, number_norm=5, dict=4, station_code=2 |
| 251222_三軌電力異常_212545_UltraLog063 | control | 32.30% | 32.30% | +0.00% | car_norm=4, number_norm=5, dict=2 |
| 251222_三軌電力異常_213242_UltraLog029 | control | 36.95% | 36.95% | +0.00% | dict=1 |
| 251222_三軌電力異常_224138_UltraLog003 | control | 35.63% | 36.32% | -0.69% | car_norm=1, number_norm=1, dict=1 |
| 251222_中清車門障礙_060548_UltraLog063 | door | 21.38% | 24.83% | -3.45% | car_norm=2, number_norm=5 |
| 251222_中清車門障礙_061021_UltraLog063 | door | 14.66% | 16.38% | -1.72% | car_norm=1, number_norm=3, dict=1 |
| 251222_中清車門障礙_061126_UltraLog063 | door | 15.38% | 14.42% | +0.96% | car_norm=3, number_norm=2, dict=1, station_code=1 |
| 251222_中清車門障礙_061255_UltraLog063 | door | 28.21% | 28.21% | +0.00% | number_norm=2, dict=1, station_code=1 |
| 251222_中清車門障礙_061411_UltraLog063 | door | 19.34% | 22.36% | -3.02% | number_norm=16, dict=1 |
| 251222_中清車門障礙_062433_UltraLog011 | door | 40.42% | 41.25% | -0.83% | number_norm=2 |