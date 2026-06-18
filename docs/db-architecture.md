# DB 架構：兩個存取層、兩張表（即時 vs 研究）

> 2026-06-18（P4 文件化）。釐清 `transcripts` 與 `transcriptions` 的分工，避免命名混淆。
> SQLite 主庫：`data/aiSpeechMulti.db`（WAL 模式，migrations 在 `migrations/`）。

## TL;DR

專案有**兩個獨立的 DB 存取層**，各自寫**不同的表**，**互不交流**：

| | 即時層 | 研究／批次層 |
|---|---|---|
| 存取類別 | `app_api.py` 內嵌 `Database` | `utils/db_manager.py` `DBManager` |
| 主表 | **`transcripts`** | **`transcriptions`**（+ events / audio_files / keywords） |
| 服務流程 | WebSocket 即時辨識 | app_lab 批次辨識、評測、修正飛輪 |
| 資料模型 | 扁平、channel-based、無 event 連結 | event/audio_file 連結、含修正飛輪與後處理 audit |
| 寫入時機 | 每條 final transcript（6 路即時） | 批次辨識／人工修正／評測 |

**`transcripts` ≠ `transcriptions`** —— 一字之差，schema 與用途完全不同，**勿混用**。
`DBManager` 從不碰 `transcripts`；`app_api.Database` 從不碰 `transcriptions`。

## 為何並存（非缺陷）

兩者服務本質不同的流程，刻意分離：

- **即時層** 要的是低延遲、channel 維度、無關聯的逐筆 append（顯示頁 poll `/api/transcripts`）。
- **研究層** 要的是 event/audio_file 關聯、修正飛輪（corrected_transcript）、逐階段後處理 audit
  （after_car_norm / after_dict / after_llm）、FTS5 全文搜尋。

合併到單表會把兩種互斥的存取模式硬塞在一起，無益且有風險。**結論：維持分離。**

## 欄位重點

### `transcripts`（即時層，app_api.Database）
`id, channel_id, transcript, confidence, created_at, stt_backend, use_vad, use_denoise,
raw_transcript, pp_report`
- `transcript` = 後處理後（corrected）；`raw_transcript` = 後處理前原文；`pp_report` = post_process 報告 JSON
  （2026-06-16 P0 加入，見即時後處理接入）。

### `transcriptions`（研究層，DBManager）
`id, audio_file_id, event_id, transcript, status, error_message, created_at, use_vad, use_denoise,
corrected_transcript, corrected_at, engine_hint, raw_transcript, after_car_norm, after_dict,
after_llm, word_confidences`
- 修正飛輪：`corrected_transcript` / `corrected_at`。
- 後處理 audit：`raw_transcript` / `after_*`（每階段獨立保存）。

> 註：兩表各有一套「後處理 audit」概念（transcripts 的 raw/pp_report vs transcriptions 的
> raw/after_*），欄位不同、不共用 —— 已知重複，目前各自運作正常。

## 已知 quirk（已評估、刻意不修）

- **`transcripts.use_vad` / `use_denoise` 為 TEXT**（migration baseline 註明「歷史包袱，原計畫
  INTEGER」），生產資料存 `'0'`/`'1'`（典型 5000+ 筆）。
  - SQLite type affinity 下比較／運算正常，`app_api.Database` 也有 `CAST(... AS INTEGER)` 收斂。
  - 改 INTEGER 需 table-rebuild migration（SQLite 無法 ALTER 欄位型別），動數千筆生產資料純為
    美觀，**不值風險 → 維持現況、標為已知可接受**（2026-06-18 決策）。

## 跨表注意

- 兩表**無 FK 連結**，不要 JOIN `transcripts` × `transcriptions`（語意上是不同來源的資料）。
- Grafana 監控同時讀兩者（即時辨識量看 `transcripts`、CER 趨勢看 `cer_history` 鏡入表）。

## 相關

- `migrations/0001_baseline_schema.sql`（9 表 baseline，含本檔所述兩表的 CREATE）
- Obsidian devlog：`2026-06-18 P4 — DB 雙路徑文件化（非合併）`
