# aiSpeechMulti UI Mockup

> 純 HTML/CSS 介面預覽，**不做真正辨識**。給新手互點看版面、收集 UI/UX 回饋用。

## 怎麼開

打開 Finder 或 VS Code，雙擊 `index.html`，瀏覽器會直接打開。

或在終端機跑：

```bash
open /Users/apple/Projects/projectArea/aiSpeechMulti/docs/mockup/index.html
```

> 不需要啟動任何 server，也不需要安裝 Python 或 Docker。

## 簡報模式（reveal.js）

雙擊 `slides.html` 即進 21 頁簡報模式（fade 切換，按 F 全螢幕）：

```bash
open /Users/apple/Projects/projectArea/aiSpeechMulti/docs/mockup/slides.html
```

公網：https://testui-aispeech.netlify.app/slides.html

導覽：←/→ 切片、ESC 看概覽、F 全螢幕、S 看演講者備忘。

---

## 包含 8 個介面

| 檔案 | 對應實際 URL | 角色 |
|---|---|---|
| `index.html` | `:8000/` | Landing（5 個入口卡片）|
| `capture.html` | `:8000/capture` | 場域端 6 路麥克風 |
| `monitor.html` | `:8000/monitor` | 操作員 6 路監看 + 成本 status bar |
| `display.html` | `:8000/display` | 控制室大螢幕 |
| `lab.html` | `:8501/` | Streamlit Lab（9 個分頁皆內嵌）|
| `grafana.html` | `:3000/` | Grafana dashboard 模擬 |
| `assets/style.css` | — | 共用樣式（dark-cool / dark-warm 雙主題）|
| `assets/nav.js` | — | 導航 + mock toast |

## 互動規則

- **頁面之間的連結**：可以點，會正常跳轉
- **送出、上傳、辨識、儲存等按鈕**：點下去會跳「🚧 這是 mock 介面，按鈕功能未啟用」的右下角 toast
- **下拉選單 / radio pill**：可以正常切換選項（純前端，不會送任何資料）
- **三主題循環 🌙 → ☀️ → 🔥**：右上角圖示按鈕，每次點切下一主題
  - 🌙 dark（cool，日班）
  - ☀️ light（白班，**新增**）
  - 🔥 dark-warm（夜班，低藍光）
  - 切換記在 `localStorage['aism-theme']`
- **Lab 左側 9 個分頁**：用 `#hash` 切換，可彼此互點

## 主題系統（2026-05-18 更新）

採用 Claude Design v1.0.0 設計 kit + dark-warm 補丁，三主題並存。

**assets/ 檔案**：

| 檔案 | 來源 | 角色 |
|---|---|---|
| `aism-theme.css` | kit（35KB）| design tokens + base + 12 components（dark + light） |
| `aism-theme-warm.css` | 補丁 | 補 `[data-theme="dark-warm"]` 暖色覆寫 + `--ch-6`（kit 只有 5 通道） |
| `aism-theme.js` | kit | 主題初始化 + Theme API + localStorage |
| `aism-icons.js` | kit | 1.5px stroke 圖示集（選用） |
| `style.css` | 本 mockup | 自訂 component 樣式（lane、cost-bar、entry-card 等），token 映射到 kit |
| `nav.js` | 本 mockup | 3 主題循環邏輯 + mock toast + hash 路由 |

## 給回饋的方式

走完一輪後，請依以下格式回報：

```markdown
### 介面：{landing / capture / monitor / display / Lab-哪一頁 / grafana}
### 我覺得不直覺的地方
- ...
### 我建議的改法
- ...
### 我為什麼這樣建議
- ...
### 嚴重度
- 高 / 中 / 低
```

完整的「新手 30 分鐘走法」見 `docs/操作手冊-新手版.md`。

---

*建立：2026-05-18 · 純前端，無後端依賴*
