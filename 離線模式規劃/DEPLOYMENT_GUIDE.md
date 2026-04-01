# aiSpeech Local v2.0（機密版）部署指南

> 雙引擎本地離線語音辨識系統 — 適用於臺中捷運 OCC 機密通聯內容辨識

## 系統架構

```
無線電音訊                  Mac mini M4 24GB (OCC 內網)
┌──────────┐    音效卡/    ┌──────────────────────────────────────────────┐
│ 無線電通聯 │──→ 錄音 ──→ │  音檔 (.wav/.raw)                             │
└──────────┘    軟體       │       ↓                                       │
                           │  ffmpeg 格式轉換 (IMA ADPCM → 16kHz WAV)     │
                           │       ↓                                       │
                           │  ┌─────────────┐    ┌──────────────────────┐ │
                           │  │ 🅰 faster-   │ 或 │ 🅱 SenseVoiceSmall  │ │
                           │  │    whisper   │    │    + fsmn-vad       │ │
                           │  │ (Whisper     │    │ (阿里 FunASR)       │ │
                           │  │  large-v3)   │    │ + 情緒辨識 + 事件偵測│ │
                           │  └──────┬───────┘    └──────────┬──────────┘ │
                           │         └──────┬───────────────┘             │
                           │                ↓                              │
                           │  Streamlit Web UI (port 8501)                │
                           │  ┌──────────────────────────────────────┐    │
                           │  │ 辨識結果 + 情緒標註 + CSV/SRT 匯出    │    │
                           │  │ + 雙引擎比較模式                      │    │
                           │  └──────────────────────────────────────┘    │
                           └──────────────────────────────────────────────┘
                                          ↑
                              OCC 內網電腦透過瀏覽器存取
                              http://<Mac mini IP>:8501
```

## 雙引擎比較

| 項目 | 🅰 faster-whisper | 🅱 SenseVoiceSmall |
|------|-------------------|-------------------|
| 來源 | OpenAI Whisper (CTranslate2 加速) | 阿里達摩院 FunASR |
| 架構 | 自回歸 (autoregressive) | 非自回歸 (non-AR) |
| 模型大小 | 500MB ~ 3GB | ~500MB |
| CPU 推論速度 | RTF 0.15x~1.5x | **RTF ~0.1x（最快）** |
| 中文準確度 | ★★★★☆ | **★★★★★** |
| 多語言 | 99 種語言 | 中/粵/英/日/韓 + 50 語言 |
| 情緒辨識 | ❌ | ✅ 開心/悲傷/憤怒/中性/恐懼/驚訝 |
| 事件偵測 | ❌ | ✅ 背景音樂/笑聲/哭聲/咳嗽/掌聲 |
| VAD | 內建 Silero VAD | 內建 fsmn-vad |
| 專有詞彙 | initial_prompt 引導 | hotword 熱詞 |
| 微調支持 | 不方便 | ✅ 支援 fine-tune |
| 授權 | MIT | MIT (框架) + Model License (模型) |

### 使用場景建議

- **日常通聯辨識（速度優先）**→ SenseVoiceSmall
- **事件分析（需要情緒/事件資訊）**→ SenseVoiceSmall
- **正式紀錄（最高準確度）**→ faster-whisper large-v3
- **不確定哪個好？**→ 使用「雙引擎比較」分頁同時測試

## 安裝步驟

```bash
cd ~/Desktop/aiSpeech_local
chmod +x setup.sh
./setup.sh      # 自動安裝雙引擎所有依賴
./start.sh      # 啟動服務
```

安裝腳本自動完成：ffmpeg 安裝、Python 虛擬環境、faster-whisper + FunASR 套件、預下載所有模型（large-v3、medium、SenseVoiceSmall + fsmn-vad）。

## 四大功能模式

### 1. 📁 檔案辨識
上傳單一音檔，選擇引擎和模型，取得辨識結果。支援 CSV / SRT / JSON 匯出。

### 2. 🎙️ 近即時辨識
監控指定資料夾，錄音軟體將音檔寫入後自動辨識。建議使用 SenseVoiceSmall（速度最快）。

### 3. 📦 批次處理
一次辨識整個資料夾的音檔，合併匯出 CSV。

### 4. ⚖️ 雙引擎比較
上傳同一段音檔，同時用兩個引擎辨識，並排比較準確度與速度差異。用於評估哪個引擎更適合特定場景。

## 專有詞彙處理

兩個引擎使用不同的詞彙注入方式：

**faster-whisper**：透過 `initial_prompt` 將專有名詞寫成一段文字，引導模型認識這些詞彙。

**SenseVoiceSmall**：透過 `hotword` 參數傳入以空格分隔的熱詞清單。

兩種方式都已預載 120+ 臺中捷運鐵道專有詞彙（站名、CBTC 術語、設備名稱等），可在側邊欄追加自訂詞彙。

## 效能基準（Mac mini M4 24GB, CPU）

| 引擎 + 模型 | 10 秒音檔推論時間 | RTF | 中文準確度 |
|-------------|-------------------|-----|-----------|
| SenseVoiceSmall | ~1 秒 | ~0.1x | ★★★★★ |
| faster-whisper small | ~1.5 秒 | ~0.15x | ★★★☆☆ |
| faster-whisper medium | ~4 秒 | ~0.4x | ★★★★☆ |
| faster-whisper large-v3 | ~15 秒 | ~1.5x | ★★★★☆ |

## 安全注意事項

1. **完全離線**：所有辨識在本機完成，資料不經過任何雲端
2. **網路隔離**：Mac mini 建議僅連 OCC 內網
3. **存取控制**：Streamlit 無認證，建議防火牆限制 IP
4. **資料清理**：定期清除暫存音檔與辨識結果
5. **模型更新**：離線環境可用 USB 傳入模型檔案

## 故障排除

| 問題 | 解決方案 |
|------|---------|
| ffmpeg 未安裝 | `brew install ffmpeg` |
| 模型下載失敗 | 檢查網路或手動下載至 `~/.cache/` |
| FunASR import 錯誤 | `pip install funasr modelscope onnxruntime` |
| SenseVoice 輸出亂碼標籤 | 程式已內建標籤解析，無需處理 |
| 記憶體不足 | 改用 SenseVoiceSmall（僅 500MB） |
| 辨識結果空白 | 降低 VAD 閾值或關閉 VAD |
| 內網無法連線 | 確認防火牆開放 port 8501 |

## 開機自動啟動（選配）

```bash
cat > ~/Library/LaunchAgents/com.occ.aispeech-local.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.occ.aispeech-local</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>cd ~/Desktop/aiSpeech_local && ./start.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.occ.aispeech-local.plist
```

## 未來擴充

1. **說話人辨識**：整合 pyannote-audio 區分不同通話方
2. **關鍵字警示**：辨識到特定詞彙時觸發告警
3. **歷史搜尋**：SQLite 儲存 + 全文搜尋
4. **RAG 知識庫整合**：通聯紀錄匯入 ChromaDB
5. **SenseVoice fine-tune**：用 OCC 鐵道語料微調模型
6. **iPhone Shortcuts**：SSH 遠端控制啟停服務
