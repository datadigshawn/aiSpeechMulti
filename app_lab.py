#!/usr/bin/env python3
"""
app_lab.py — aiSpeechMulti 研究工作台 (Lab)
版本: 3.0 (2026-05-04 介面整併 P0)

由 app_dashboard.py 拆出。Lab 只負責研究 / 評測 / 資料管理 9 頁，
即時多路監控 / 大螢幕投放改由 FastAPI 直供的靜態 HTML 提供。

包含頁面（9 + 1 內部執行階段）:
- speech              批次音檔辨識（含 fine-tuned SenseVoice）
  └─ running          批次辨識的執行階段（speech 內部 transition）
- offline_monitor     離線近即時監看（資料夾 watch）
- evaluation          黃金語料 CER 評測
- cer_trend           CER 趨勢看板（將遷移 Grafana）
- correction_history  錯字回饋飛輪
- management          事件管理
- search              FTS5 全文搜尋
- stats               統計報表
- vocabulary          詞彙表管理

被廢除頁面（請改用即時介面）:
- home / monitor → 改用 :8000/capture · :8000/monitor · :8000/display

啟動方式:
    streamlit run app_lab.py
    （需同時啟動 FastAPI：python app_api.py）
"""

import re
import csv
import io
import sys
import os
import json
import shutil
import time
import traceback
from pathlib import Path
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

# ============================================================================
# 路徑設定
# ============================================================================
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

EXPERIMENTS_DIR    = PROJECT_ROOT / "experiments"
TEMP_UPLOAD_DIR    = EXPERIMENTS_DIR / "temp_upload"
SUPPORTED_EXTENSIONS = ['.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac']
MAX_UPLOAD_FILES   = 100
VOCABULARY_CSV     = PROJECT_ROOT / "vocabulary" / "master_vocabulary.csv"
DB_PATH            = PROJECT_ROOT / "data" / "aiSpeechMulti.db"   # ← 統一使用 aiSpeechMulti.db

# ============================================================================
# FastAPI 即時監控常數
# ============================================================================
API_BASE     = "http://localhost:8000"
ALL_CHANNELS = ["ch1", "ch2", "ch3", "ch4", "ch5"]
CH_COLORS    = {
    "ch1": "#7eb8f7",
    "ch2": "#7ef7b0",
    "ch3": "#f7d07e",
    "ch4": "#f77eb8",
    "ch5": "#b07ef7",
}

# ============================================================================
# 批次辨識常數
# ============================================================================
HAZARD_LABELS = {
    0: "0 — 正常",
    1: "1 — 輕微異常",
    2: "2 — 需注意",
    3: "3 — 中等（影響服務）",
    4: "4 — 嚴重",
    5: "5 — 緊急（火災／出軌／傷亡）",
}

MODEL_OPTIONS = {
    "Google Cloud STT":         "google_stt",
    "Google Gemini":            "gemini",
    "OpenAI Whisper":           "whisper",
    "🔀 混合模式（Google + Gemini）": "hybrid",
    "🔒 SenseVoiceSmall（離線）": "sensevoice",
    "⭐ SenseVoice Fine-tuned（捷運專用）": "sensevoice_ft",
}

SUB_MODEL_OPTIONS = {
    "google_stt": [
        ("chirp_3 — 最新高精度（推薦）",           "chirp_3"),
        ("chirp_3 簡中+講者辨識 — 測試",           "chirp_3_hans"),
        ("chirp_2 — 一般辨識",                    "chirp_2"),
        ("chirp_telephony — 電話品質音訊",         "chirp_telephony"),
    ],
    "gemini": [
        ("gemini-2.5-pro — ⭐ 最佳辨識（baseline CER 49%，推薦）", "gemini-2.5-pro"),
        ("gemini-3.1-pro-preview — 最新旗艦 Preview（成本高）",   "gemini-3.1-pro-preview"),
        ("gemini-2.5-flash-lite — 最快、最省費",                  "gemini-2.5-flash-lite"),
        ("gemini-2.5-flash — 不推薦（重複輸出風險）",              "gemini-2.5-flash"),
        ("gemini-2.0-flash — 舊穩定版（2026/6 停用）",             "gemini-2.0-flash"),
    ],
    "whisper": [
        ("large-v3 — 最準確（推薦）", "large-v3"),
        ("turbo — 最快",            "turbo"),
        ("medium — 均衡",           "medium"),
    ],
    # hybrid：子模型為 Gemini 選項（Google STT 固定使用 chirp_3）
    "hybrid": [
        ("gemini-2.5-pro — ⭐ 最佳辨識（推薦）",           "gemini-2.5-pro"),
        ("gemini-3.1-pro-preview — 最新旗艦（成本高）",    "gemini-3.1-pro-preview"),
        ("gemini-2.5-flash-lite — 最省費",                "gemini-2.5-flash-lite"),
        ("gemini-2.5-flash — 不推薦（重複輸出風險）",      "gemini-2.5-flash"),
    ],
    # SenseVoice：只有一個模型
    "sensevoice": [
        ("SenseVoiceSmall — 🔒 離線、含情緒辨識（推薦）", "iic/SenseVoiceSmall"),
    ],
    # Fine-tuned SenseVoice（LoRA r32_e60，2026-05-01 訓練）
    "sensevoice_ft": [
        ("SenseVoice + LoRA r32 e60 — ⭐ 捷運通訊專用（CER 28.12%）", "sensevoice_ft_r32"),
    ],
}

# ============================================================================
# 詞彙表欄位定義
# ============================================================================
_VOCAB_COLUMNS = ["term", "category", "boost_value", "alert_level", "pinyin", "common_error", "description"]
_VOCAB_CATEGORIES = ["equipment", "location", "action", "personnel", "numeric", "other"]

# ============================================================================
# 頁面設定（必須在最頂層）
# ============================================================================
st.set_page_config(
    page_title="aiSpeechMulti Lab",
    page_icon="🔬",
    layout="wide",
)

# ============================================================================
# 自訂 CSS（design-system-v1: 從 static/css/ 注入 tokens + components）
# ============================================================================

def _inject_design_system():
    """注入 design tokens + Streamlit-tailored 覆寫 + Lab legacy 對映。

    經 2026-05-05 驗收教訓：
    - 不再注入 base.css（其 html/body selectors 與 Streamlit 自家 reset 衝突，
      會導致頂部 header 變白、文字色被吃掉、字體 fallback 變細）
    - 不再注入 components.css（Lab 不用大多數元件，反而干擾 Streamlit baseweb）
    - 只注入 tokens.css 的 :root 變數，加上強化版的 Streamlit 容器覆寫
    """
    tokens_path = PROJECT_ROOT / "static" / "css" / "tokens.css"
    tokens_css = tokens_path.read_text(encoding="utf-8") if tokens_path.exists() else ""

    streamlit_overrides = """
    /* ─── 全域 ─── */
    html, body, .stApp {
        background: var(--neutral-1) !important;
        color: var(--neutral-12) !important;
        font-family: var(--font-sans);
    }
    .stApp * { font-family: var(--font-sans); }
    .stApp [data-testid="stMarkdownContainer"] code,
    .stApp [data-testid="stCode"] code,
    .stApp pre,
    .stApp .mono { font-family: var(--font-mono) !important; }

    /* ─── 頂部 Header（Deploy 按鈕條） ─── */
    [data-testid="stHeader"],
    header[data-testid="stHeader"] {
        background: var(--neutral-1) !important;
        border-bottom: 1px solid var(--neutral-6);
    }
    [data-testid="stToolbar"] { background: transparent !important; }

    /* ─── 主內容容器 ─── */
    .block-container {
        padding-top: 2rem;
        max-width: 1280px;
        background: var(--neutral-1);
    }
    section.main { background: var(--neutral-1) !important; }
    section.main > div { background: var(--neutral-1); }

    /* ─── 標題與正文 ─── */
    h1, h2, h3, h4, h5, h6,
    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3 {
        color: var(--neutral-13) !important;
        font-weight: var(--fw-semibold);
    }
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li {
        color: var(--neutral-12) !important;
    }
    [data-testid="stCaptionContainer"],
    .stCaption,
    small { color: var(--neutral-10) !important; }

    /* ─── Sidebar ─── */
    section[data-testid="stSidebar"] {
        background: var(--neutral-2) !important;
        border-right: 1px solid var(--neutral-6);
    }
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] *,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stRadio label,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] h4 {
        color: var(--neutral-12) !important;
    }
    section[data-testid="stSidebar"] a {
        color: var(--brand-primary) !important;
    }
    section[data-testid="stSidebar"] a:hover {
        color: var(--brand-primary-hover) !important;
    }
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        color: var(--neutral-9) !important;
    }

    /* ─── Buttons ─── */
    button[kind="primary"], .stButton button[kind="primary"] {
        background: var(--brand-primary) !important;
        color: var(--neutral-0) !important;
        border: 1px solid var(--brand-primary) !important;
        font-weight: var(--fw-semibold);
    }
    button[kind="primary"]:hover {
        background: var(--brand-primary-hover) !important;
        border-color: var(--brand-primary-hover) !important;
    }
    button[kind="secondary"], .stButton button[kind="secondary"] {
        background: var(--neutral-3) !important;
        border: 1px solid var(--neutral-7) !important;
        color: var(--neutral-12) !important;
    }
    button[kind="secondary"]:hover {
        background: var(--neutral-4) !important;
        border-color: var(--neutral-8) !important;
    }
    /* 一般 button (無 kind) — 例如 sidebar 套用 / 各頁返回 */
    .stButton button:not([kind]) {
        background: var(--neutral-3) !important;
        border: 1px solid var(--neutral-7) !important;
        color: var(--neutral-12) !important;
    }
    .stButton button:not([kind]):hover {
        background: var(--neutral-4) !important;
        border-color: var(--neutral-8) !important;
    }
    /* download button */
    .stDownloadButton button {
        background: var(--neutral-3) !important;
        border: 1px solid var(--neutral-7) !important;
        color: var(--neutral-12) !important;
    }

    /* ─── Inputs / Selects / Textarea ─── */
    .stTextInput input,
    .stTextArea textarea,
    .stNumberInput input,
    .stDateInput input,
    .stTimeInput input,
    .stSelectbox div[role="combobox"],
    .stSelectbox div[data-baseweb="select"] > div,
    .stMultiSelect div[data-baseweb="select"] > div,
    [data-baseweb="input"] {
        background: var(--neutral-0) !important;
        border: 1px solid var(--neutral-6) !important;
        color: var(--neutral-12) !important;
    }
    .stTextInput input::placeholder,
    .stTextArea textarea::placeholder {
        color: var(--neutral-8) !important;
    }
    .stTextInput input:focus,
    .stTextArea textarea:focus,
    .stSelectbox div[role="combobox"]:focus-within {
        border-color: var(--brand-primary) !important;
    }
    /* baseweb popover (select dropdown) */
    [data-baseweb="popover"] [role="listbox"],
    [data-baseweb="menu"] {
        background: var(--neutral-3) !important;
        border: 1px solid var(--neutral-7) !important;
    }
    [data-baseweb="menu"] li { color: var(--neutral-12) !important; }
    [data-baseweb="menu"] li:hover { background: var(--neutral-4) !important; }

    /* ─── File uploader（修白色卡片問題） ─── */
    [data-testid="stFileUploader"] section,
    [data-testid="stFileUploaderDropzone"],
    [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] {
        background: var(--neutral-2) !important;
        border: 1px dashed var(--neutral-7) !important;
        color: var(--neutral-11) !important;
    }
    [data-testid="stFileUploader"] small,
    [data-testid="stFileUploader"] [data-testid="stMarkdownContainer"] {
        color: var(--neutral-10) !important;
    }
    [data-testid="stFileUploader"] button {
        background: var(--neutral-4) !important;
        color: var(--neutral-12) !important;
        border: 1px solid var(--neutral-7) !important;
    }

    /* ─── Tabs ─── */
    .stTabs [data-baseweb="tab-list"] {
        gap: var(--space-2);
        border-bottom: 1px solid var(--neutral-6);
        background: transparent;
    }
    .stTabs [data-baseweb="tab"] { color: var(--neutral-10) !important; }
    .stTabs [aria-selected="true"] { color: var(--brand-primary) !important; }

    /* ─── Radio / Checkbox / Toggle ─── */
    .stRadio label, .stCheckbox label {
        color: var(--neutral-12) !important;
    }

    /* ─── Metric (st.metric)  ─── */
    [data-testid="stMetricValue"] {
        font-family: var(--font-mono) !important;
        color: var(--neutral-13) !important;
    }
    [data-testid="stMetricLabel"] {
        color: var(--neutral-9) !important;
        text-transform: uppercase;
        letter-spacing: var(--ls-wider);
        font-size: var(--fs-caption);
    }
    [data-testid="stMetricDelta"] svg { fill: currentColor !important; }

    /* ─── Dataframe / Table ─── */
    [data-testid="stDataFrame"] {
        background: var(--neutral-2) !important;
        border: 1px solid var(--neutral-6) !important;
    }
    [data-testid="stDataFrame"] thead th {
        background: var(--neutral-3) !important;
        color: var(--neutral-11) !important;
    }

    /* ─── Alerts (st.info / st.warning / st.error / st.success) ─── */
    [data-testid="stAlert"] {
        background: var(--neutral-2) !important;
        border-left: 3px solid var(--neutral-7);
    }
    /* st.error → danger 邊條 */
    [data-testid="stAlert"][kind="error"] { border-left-color: var(--danger); }
    [data-testid="stAlert"][kind="warning"] { border-left-color: var(--warning); }
    [data-testid="stAlert"][kind="success"] { border-left-color: var(--success); }
    [data-testid="stAlert"][kind="info"] { border-left-color: var(--brand-primary); }

    /* ─── Divider / hr ─── */
    hr, [data-testid="stDivider"] hr {
        border-color: var(--neutral-6) !important;
        margin: var(--space-4) 0;
    }

    /* ─── Code blocks ─── */
    pre, code, kbd {
        background: var(--neutral-2) !important;
        color: var(--neutral-12) !important;
    }
    code { padding: 1px 5px; border-radius: var(--radius-1); }

    /* ─── Lab legacy classes ─── */
    .ch-card {
        background: var(--neutral-2);
        border: 1px solid var(--neutral-6);
        border-radius: var(--radius-3);
        padding: 14px 16px;
        min-height: 100px;
    }
    .ch-card.active { border-color: var(--success); }
    .ch-dot {
        display: inline-block;
        width: 10px; height: 10px;
        border-radius: 50%;
        margin-right: 6px;
        vertical-align: middle;
    }
    .ch-dot.on  { background: var(--success); box-shadow: 0 0 6px var(--success); }
    .ch-dot.off { background: var(--neutral-7); }
    .ch-id  { font-size: 1rem; font-weight: var(--fw-bold); color: var(--neutral-12); }
    .ch-cnt { font-size: var(--fs-caption); color: var(--neutral-9); margin-top: 4px; }
    .ch-text {
        font-size: var(--fs-small); color: var(--neutral-10); margin-top: 6px;
        overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
    }
    .tx-row {
        display: flex; gap: 10px; align-items: flex-start;
        padding: 7px 10px;
        border-radius: var(--radius-3);
        margin-bottom: 4px;
        background: var(--neutral-2);
        border-left: 3px solid var(--neutral-6);
    }
    .tx-time { font-size: var(--fs-caption); color: var(--neutral-8); white-space: nowrap; padding-top: 2px; min-width: 58px; }
    .tx-ch {
        font-size: var(--fs-caption); border-radius: var(--radius-2); padding: 1px 7px;
        white-space: nowrap; align-self: flex-start; margin-top: 2px;
        font-weight: var(--fw-semibold);
    }
    .tx-text { flex: 1; font-size: var(--fs-body); color: var(--neutral-12); line-height: var(--lh-normal); }
    .offline-banner {
        background: var(--danger-bg);
        border: 1px solid var(--danger);
        border-radius: var(--radius-3);
        padding: 10px 16px;
        color: var(--danger);
        font-size: var(--fs-body);
        margin-bottom: 12px;
    }
    .stat-num { font-size: var(--fs-stat-md); font-weight: var(--fw-bold); color: var(--brand-primary); }
    .stat-lbl { font-size: var(--fs-caption); color: var(--neutral-9); letter-spacing: var(--ls-wider); text-transform: uppercase; }
    """

    st.markdown(f"<style>{tokens_css}{streamlit_overrides}</style>", unsafe_allow_html=True)


_inject_design_system()


# Plotly figure 統一 dark theme（design-system-v1）
def lab_plotly_layout(title: str | None = None, height: int = 480) -> dict:
    """回傳統一的 plotly update_layout dict，吃 design tokens 對應 hex。

    Grafana / Lab / static HTML 三處圖表配色來自同一份 token 表，
    確保跨介面視覺一致。
    """
    return dict(
        title=title,
        height=height,
        hovermode="x unified",
        paper_bgcolor="#11141b",   # var(--neutral-2)
        plot_bgcolor="#11141b",
        font=dict(family="Inter, Noto Sans TC, sans-serif", color="#c8cdd6", size=12),  # neutral-11
        xaxis=dict(gridcolor="#262a33", linecolor="#262a33", tickcolor="#6a7180"),     # neutral-6 / 9
        yaxis=dict(gridcolor="#262a33", linecolor="#262a33", tickcolor="#6a7180"),
        margin=dict(l=48, r=24, t=48 if title else 24, b=40),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#262a33"),
    )


# 5 路 channel 色（與 static / Grafana 對齊）— design tokens hex
LAB_CHANNEL_COLORS = ["#65c8d4", "#bce26d", "#e2c46d", "#e58fc1", "#b58fe5"]
LAB_BRAND_PRIMARY  = "#3fbdc7"


# ============================================================================
# Session State 初始化
# ============================================================================
def init_session_state():
    defaults = {
        "page":           "speech",
        "model_type":     None,
        "sub_model":      None,
        "uploaded_files": [],
        "server_files":   [],
        "results":        [],
        "use_vocabulary":  True,
        "merge_results":   False,
        "preproc_vad":     False,
        "preproc_denoise": False,
        "preproc_vad_thr": 0.5,
        "event_name":     "",
        "last_event_id":  None,
        "search_query":   "",
        # 準確率評測頁面 ── 語音辨識模式
        "eval_case_name":   "",
        "eval_model_type":  None,
        "eval_sub_model":   None,
        "eval_done":        False,
        "eval_results":     None,   # dict 來自 cer_engine.evaluate_case()
        "eval_output_dir":  "",
        "eval_timestamp":   "",
        "eval_meta":        {},     # 辨識模式資訊（模型、子模型等）
        # 準確率評測頁面 ── 純文稿比對模式
        "eval_text_done":    False,
        "eval_text_results": None,
        "eval_text_meta":    {},
        # 辨識狀態（防止 re-run 重複辨識）
        "recognition_done":    False,
        "recognition_results": [],
        # 即時監控
        "api_base":       API_BASE,
        "auto_refresh":   True,
        "show_limit":     50,
        "filter_ch_sidebar": "全部",
        "q_result":       None,
        # 離線近即時監控
        "om_watch_folder":   "",
        "om_language":       "zh",
        "om_running":        False,
        "om_results":        [],
        "om_seen_files":     [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ============================================================================
# 認證設定
# ============================================================================
def setup_credentials():
    try:
        from scripts.batch_inference import setup_google_credentials
        setup_google_credentials()
    except Exception:
        pass


# ============================================================================
# 工具：從檔名解析日期時間
# ============================================================================
def parse_filename_datetime(stem: str) -> datetime | None:
    match = re.search(r'(20\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', stem)
    if not match:
        return None
    try:
        return datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3)),
            int(match.group(4)), int(match.group(5)), int(match.group(6)),
        )
    except ValueError:
        return None


# ============================================================================
# 工具：掃描伺服器音檔
# ============================================================================
def scan_server_audio_files() -> dict:
    result = {}
    if not EXPERIMENTS_DIR.exists():
        return result
    for test_case_dir in sorted(EXPERIMENTS_DIR.iterdir()):
        if not test_case_dir.is_dir() or test_case_dir.name == "temp_upload":
            continue
        audio_dir = test_case_dir / "source_audio"
        if not audio_dir.exists():
            continue
        files = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(audio_dir.glob(f"*{ext}"))
            files.extend(audio_dir.glob(f"*{ext.upper()}"))
        if files:
            result[test_case_dir.name] = sorted(set(files))
    return result







# ============================================================================
# 頁面：語音辨識設定
# ============================================================================
def render_speech_page():
    if st.button("← 回到批次辨識", key="back_home"):
        st.session_state["page"] = "speech"
        st.rerun()

    st.title("語音辨識模式")
    st.divider()

    # ── Step 1：模型類型 ─────────────────────────────────────────────────
    st.subheader("Step 1　選擇辨識模型")
    model_label = st.radio(
        "模型", options=list(MODEL_OPTIONS.keys()), horizontal=True, label_visibility="collapsed",
    )
    model_type = MODEL_OPTIONS[model_label]
    st.write("")

    # ── Step 2：子模型 ──────────────────────────────────────────────────
    st.subheader("Step 2　選擇子模型")
    sub_options = SUB_MODEL_OPTIONS[model_type]
    sub_labels  = [label for label, _ in sub_options]
    sub_val_map = {label: val for label, val in sub_options}
    sub_label   = st.radio("子模型", options=sub_labels, label_visibility="collapsed")
    sub_model   = sub_val_map[sub_label]

    if sub_model == "chirp_3_hans":
        st.info(
            "🧪 **測試模式**  \n"
            "• 語言：**簡體中文（cmn-Hans-CN）**  \n"
            "• 自動啟用**講者辨識**（Google chirp_3 官方支援）  \n"
            "• 輸出格式：`【講者A ｜ MM:SS】文字...`  \n"
            "• ⚠️ 繁體中文用語可能辨識準確度較低，僅供測試"
        )

    if model_type == "hybrid":
        st.info(
            "🔀 **混合模式說明**  \n"
            "• **Google STT chirp_3**（固定）+ **Gemini**（上方選擇）同時辨識每個音檔  \n"
            "• **融合規則**：依兩模型 CER 一致性分數自動選取最佳結果  \n"
            "　　- CER < 10%（高度一致）→ 採用 Google STT（confidence 較可靠）  \n"
            "　　- CER 10–40%（中度差異）→ 採用 Gemini（語意理解較強）  \n"
            "　　- CER > 40%（極大差異）→ 採用 Google STT（差異過大，Gemini 可能嚴重錯誤）  \n"
            "　　- 任一模型失敗 → 自動降級為另一模型  \n"
            "• ⚠️ API 費用為單模型的約 **2 倍**，建議用於高準確度需求場景"
        )

    if model_type == "sensevoice":
        st.info(
            "🔒 **SenseVoiceSmall 離線模式說明**  \n"
            "• **完全離線**，資料不離開本機，適合機密通聯  \n"
            "• **含情緒辨識**：😊 開心 / 😠 憤怒 / 😢 悲傷 / 😐 中性…  \n"
            "• **含事件偵測**：🗣️ 語音 / 🎵 背景音樂 / 😄 笑聲 / 😷 咳嗽…  \n"
            "• **RTF ≈ 0.1x**（10 分鐘音檔約 1 分鐘辨識完成）  \n"
            "• ⚠️ 首次使用會自動下載模型（約 500MB），需要網路"
        )

    if model_type == "sensevoice_ft":
        st.info(
            "⭐ **SenseVoice Fine-tuned（捷運通訊專用）**  \n"
            "• 在 SenseVoiceSmall 上以 LoRA (rank=32) 微調 60 epoch（46 段訓練語料）  \n"
            "• **全 63 段 CER**：raw 29.50% / +全 pipeline **28.12%** ⭐（baseline 65.84%）  \n"
            "• **完全離線**、含情緒/事件辨識（同基礎模型）  \n"
            "• 需要 LoRA checkpoint：`experiments/finetune_runs/sensevoice_lora_r32_e60/best.pt`  \n"
            "• ⚠️ 首次使用須安裝 `peft`，且該 checkpoint 不在 git，需從訓練機複製"
        )

    st.write("")

    # ── Step 3：音檔載入 ────────────────────────────────────────────────
    st.subheader("Step 3　載入語音檔案")
    tab_upload, tab_server = st.tabs(["上傳本機檔案", "瀏覽伺服器音檔"])

    selected_upload_files = []
    selected_server_files = []

    with tab_upload:
        uploaded = st.file_uploader(
            f"選擇音檔（最多 {MAX_UPLOAD_FILES} 個，支援 .wav .mp3 .m4a .flac .ogg .aac）",
            type=["wav", "mp3", "m4a", "flac", "ogg", "aac"],
            accept_multiple_files=True,
            key="file_uploader",
        )
        if uploaded:
            if len(uploaded) > MAX_UPLOAD_FILES:
                st.warning(f"最多只能選擇 {MAX_UPLOAD_FILES} 個檔案，目前選了 {len(uploaded)} 個，將只處理前 {MAX_UPLOAD_FILES} 個。")
                uploaded = uploaded[:MAX_UPLOAD_FILES]
            selected_upload_files = uploaded
            st.success(f"已選擇 {len(selected_upload_files)} 個檔案")
            for f in selected_upload_files:
                st.write(f"  - `{f.name}`")

    with tab_server:
        server_audio_map = scan_server_audio_files()
        if not server_audio_map:
            st.info(f"在 `experiments/` 目錄下未找到任何音檔。\n\n預設搜尋路徑：`{EXPERIMENTS_DIR}`")
        else:
            display_to_path = {}
            for test_case, files in server_audio_map.items():
                for fp in files:
                    display_name = f"[{test_case}]  {fp.name}"
                    display_to_path[display_name] = fp
            selected_display = st.multiselect(
                f"選擇要辨識的音檔（最多 {MAX_UPLOAD_FILES} 個）",
                options=list(display_to_path.keys()),
                max_selections=MAX_UPLOAD_FILES,
            )
            if selected_display:
                selected_server_files = [display_to_path[d] for d in selected_display]
                st.success(f"已選擇 {len(selected_server_files)} 個檔案")

    # ── Step 4：詞彙優化 ─────────────────────────────────────────────────
    st.write("")
    st.subheader("Step 4　詞彙優化")
    use_vocabulary = st.checkbox(
        "啟用三層詞彙系統（辨識結果後處理）",
        value=st.session_state.get("use_vocabulary", True),
        key="vocab_checkbox",
        help=(
            "套用台灣捷運無線電專用詞彙規則，修正 ASR 常見的同音異字與術語錯誤。\n\n"
            "• 第一層（辨識前）：Google PhraseSet 詞彙提示，僅限 Google STT 模型\n"
            "• 第二層（辨識後）：OCC / MCP 等核心術語修正 + 同音字修正（102 條規則）\n"
            "• 第二層+：correction_dict.py 補充詞彙，含月台編號、軍事數字讀法（+195 條規則）"
        ),
    )

    if use_vocabulary:
        col_l1, col_l2, col_l3 = st.columns(3)
        with col_l1:
            if model_type != "google_stt":
                icon, label = "⚪", "僅限 Google STT"
            elif sub_model == "chirp_3":
                icon, label = "🔴", "Chirp 3 不支援（跳過）"
            else:
                icon, label = "🟢", "啟用中"
            st.caption(f"{icon} **第一層**　PhraseSet 辨識提示\n{label}")
        with col_l2:
            st.caption("🟢 **第二層**　術語 + 同音字修正\n啟用中（102 條）")
        with col_l3:
            st.caption("🟢 **第二層+**　correction_dict 補充\n啟用中（+195 條）")
    else:
        st.caption("⚫ 詞彙優化已關閉，辨識結果將保留原始 ASR 輸出")

    # ── Step 5：音訊前處理 ──────────────────────────────────────────────────
    st.write("")
    st.subheader("Step 5　音訊前處理")

    # 從 API 取得目前設定
    _preproc_defaults = {"use_vad": False, "use_denoise": False, "vad_threshold": 0.5}
    _preproc_avail    = {"vad": True, "denoise": True}
    try:
        _resp = requests.get(f"{API_BASE}/api/settings", timeout=2)
        if _resp.ok:
            _preproc_defaults = _resp.json().get("settings", _preproc_defaults)
            _preproc_avail    = _resp.json().get("availability", _preproc_avail)
    except Exception:
        pass

    col_vad, col_denoise = st.columns(2)
    with col_vad:
        _vad_help = (
            "**Silero VAD** — 過濾靜噪/靜音片段，防止 STT 在無聲段產生幻覺文字。\n\n"
            "**無線電建議：開啟**（靜噪雜音是主要干擾源）"
        )
        if not _preproc_avail.get("vad", True):
            st.toggle("🔇 VAD 靜音過濾", value=False, disabled=True,
                      key="preproc_vad", help="Silero VAD 未安裝：pip install silero-vad")
            st.caption("⚠️ Silero VAD 未安裝")
        else:
            use_vad = st.toggle(
                "🔇 VAD 靜音過濾",
                value=st.session_state.get("preproc_vad", _preproc_defaults.get("use_vad", False)),
                key="preproc_vad",
                help=_vad_help,
            )
            if use_vad:
                vad_threshold = st.slider(
                    "靈敏度門檻（愈高愈嚴格）",
                    min_value=0.10, max_value=0.90, step=0.05,
                    value=float(st.session_state.get("preproc_vad_thr",
                                _preproc_defaults.get("vad_threshold", 0.5))),
                    key="preproc_vad_thr",
                    format="%.2f",
                )
            else:
                vad_threshold = float(_preproc_defaults.get("vad_threshold", 0.5))

    with col_denoise:
        _denoise_help = (
            "**DeepFilterNet** — AI 背景降噪。\n\n"
            "**無線電注意**：無線電為窄頻壓縮音質，降噪效果有限，"
            "建議**開/關各辨識一次**比較準確率後再決定。"
        )
        if not _preproc_avail.get("denoise", True):
            st.toggle("🎚️ DeepFilterNet 降噪", value=False, disabled=True,
                      key="preproc_denoise", help="DeepFilterNet 未安裝：pip install deepfilternet")
            st.caption("⚠️ DeepFilterNet 未安裝")
        else:
            use_denoise = st.toggle(
                "🎚️ DeepFilterNet 降噪",
                value=st.session_state.get("preproc_denoise",
                                           _preproc_defaults.get("use_denoise", False)),
                key="preproc_denoise",
                help=_denoise_help,
            )

    # 當 toggle 改變時推送到 API（讓 index.html 即時語音也同步）
    _new_vad     = st.session_state.get("preproc_vad",     False)
    _new_denoise = st.session_state.get("preproc_denoise", False)
    _new_thr     = float(st.session_state.get("preproc_vad_thr", 0.5))
    if (_new_vad     != _preproc_defaults.get("use_vad",       False) or
        _new_denoise != _preproc_defaults.get("use_denoise",   False) or
        abs(_new_thr  - _preproc_defaults.get("vad_threshold", 0.5)) > 0.001):
        try:
            requests.post(f"{API_BASE}/api/settings", json={
                "use_vad":       _new_vad,
                "use_denoise":   _new_denoise,
                "vad_threshold": _new_thr,
            }, timeout=2)
        except Exception:
            pass

    if _new_vad or _new_denoise:
        _active = []
        if _new_vad:     _active.append(f"VAD（門檻 {_new_thr:.2f}）")
        if _new_denoise: _active.append("DeepFilterNet 降噪")
        st.caption(f"✅ 已啟用：{' + '.join(_active)}")
    else:
        st.caption("⚫ 前處理關閉，直接送 STT（原始音訊）")

    # ── Step 6：後處理 Pipeline ───────────────────────────────────────────
    st.write("")
    st.subheader("Step 6　後處理 Pipeline")
    st.caption("辨識結果產出後，依序套用以下後處理修正（可獨立開關）")

    col_pp1, col_pp2, col_pp3 = st.columns(3)
    with col_pp1:
        pp_car_norm = st.checkbox(
            "🚆 車廂編號正規化",
            value=st.session_state.get("pp_car_norm", True),
            key="pp_car_norm_chk",
            help=(
                "regex 修正車廂編號格式，例如：\n"
                "  2526車 → 25/26 車\n"
                "  兩五兩六車 → 25/26 車\n"
                "  腰洞車 → 10 車（軍事數字）\n"
                "支援中文/軍事數字，零成本"
            ),
        )
    with col_pp2:
        pp_dict = st.checkbox(
            "📖 詞彙字典修正",
            value=st.session_state.get("pp_dict", True),
            key="pp_dict_chk",
            help=(
                "套用 vocabulary/correction_dict.py 的同音字/術語修正規則\n"
                "由 master_vocabulary.csv 的 common_error 欄位自動生成"
            ),
        )
    with col_pp3:
        pp_llm = st.checkbox(
            "🤖 LLM 後修正",
            value=st.session_state.get("pp_llm", False),
            key="pp_llm_chk",
            help=(
                "用 Gemini 對辨識結果做最後一輪語意校對。\n"
                "需要 GEMINI_API_KEY，每句約 1-2 秒額外時間"
            ),
        )

    # 引擎建議 caption（依 A/B 測試結論）
    _hq_engines = {"gemini", "hybrid"}
    _is_hq = model_type in _hq_engines
    if pp_llm:
        if _is_hq:
            st.warning(
                f"⚠️ 你選擇的 **{model_type}** 屬於高品質 LLM-grade 引擎，"
                "再用 LLM 後修正可能造成**過度修改**反而降低 CER（依 A/B 測試結果）。\n\n"
                "建議：勾選下方「🛡️ 智能跳過」讓系統自動為高品質引擎略過 LLM 階段。"
            )
        else:
            st.caption(
                f"💡 **{model_type}** 屬於中等品質引擎，LLM 後修正預期可降低 CER 約 1~3%。"
            )
    else:
        st.caption(
            "💡 **引擎建議**：對 chirp_3 / Whisper / SenseVoice / Scribe 等中等品質引擎勾選 LLM 後修正可改善 CER；"
            "對 Gemini / Hybrid 等高品質 LLM-grade 引擎則建議**保持關閉**。"
        )

    if pp_llm:
        col_llm1, col_llm2, col_llm3 = st.columns(3)
        with col_llm1:
            pp_llm_model = st.selectbox(
                "LLM 模型",
                options=["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-3.1-pro-preview"],
                index=0,
                key="pp_llm_model_sel",
            )
        with col_llm2:
            pp_llm_strict = st.selectbox(
                "修正強度",
                options=["strict", "conservative", "balanced"],
                index=1,
                key="pp_llm_strict_sel",
                help=(
                    "strict: 只改高信心術語錯誤\n"
                    "conservative: 修正術語+簡繁+同音字（推薦）\n"
                    "balanced: 含標點與輕度語法修正"
                ),
            )
        with col_llm3:
            pp_llm_smart_skip = st.checkbox(
                "🛡️ 智能跳過",
                value=st.session_state.get("pp_llm_smart_skip", True),
                key="pp_llm_smart_skip_chk",
                help=(
                    "啟用後，當辨識引擎為 Gemini / Hybrid 等高品質 LLM-grade 時，"
                    "自動跳過 LLM 後修正階段，避免過度修改。\n\n"
                    "依 A/B 測試結果：Gemini 3.1 Pro 經 LLM 後修正後 CER "
                    "由 26.96% 退步到 27.54%。"
                ),
            )
    else:
        pp_llm_model = "gemini-2.5-flash"
        pp_llm_strict = "conservative"
        pp_llm_smart_skip = True

    # 將設定寫入 session_state，供 running 頁面讀取
    st.session_state["pp_car_norm"] = pp_car_norm
    st.session_state["pp_dict"] = pp_dict
    st.session_state["pp_llm"] = pp_llm
    st.session_state["pp_llm_model"] = pp_llm_model
    st.session_state["pp_llm_strict"] = pp_llm_strict
    st.session_state["pp_llm_smart_skip"] = pp_llm_smart_skip
    # engine_hint 優先用 sub_model（讓 TermFilter overlay 能精準匹配
    # 例如 gemini-2.5-pro → vocabulary/engines/gemini25pro.json），
    # 沒有 sub_model 才退回 model_type
    st.session_state["pp_engine_hint"] = sub_model or model_type

    # ── 引擎規則數顯示（vocabulary/engines/{engine}.json overlay）─────────
    try:
        from scripts.term_filter import TermFilter as _DashTermFilter
        from scripts.term_filter import get_engine_audio_preprocess as _get_ap
        from scripts.contextual_corrector import ContextualCorrector as _DashCC
        _hint = sub_model or model_type
        _dash_tf = _DashTermFilter(engine_hint=_hint)
        _dash_cc = _DashCC(engine_hint=_hint)
        _ap_cfg = _get_ap(_hint)
        _tf_ov = _dash_tf.overlay_summary
        _cc_ov = _dash_cc.overlay_summary
        _has_overlay = _tf_ov.get("applied") or _cc_ov.get("applied")
        _audio_label = "🎧 ON" if _ap_cfg.get("enabled") else "🎧 OFF"
        if _has_overlay:
            st.success(
                f"📦 已套用引擎 `{_hint}` 專屬規則  "
                f"→ blacklist **{len(_dash_tf.blacklist)}** 條 "
                f"(+{_tf_ov.get('blacklist_added', 0)})  "
                f"｜  whitelist **{len(_dash_tf.whitelist)}** 條 "
                f"(+{_tf_ov.get('whitelist_added', 0)})  "
                f"｜  contextual **{len(_dash_cc.rules)}** 條 "
                f"(+{_cc_ov.get('rules_added', 0)})  "
                f"｜  音訊預處理 {_audio_label}"
            )
        else:
            st.caption(
                f"📦 引擎 `{_hint}` 無專屬規則（僅套基底）"
                f"：blacklist {len(_dash_tf.blacklist)} 條 / "
                f"whitelist {len(_dash_tf.whitelist)} 條 / "
                f"contextual {len(_dash_cc.rules)} 條 / 音訊預處理 {_audio_label}。"
                f" 可建立 `vocabulary/engines/{_hint}.json` 為此引擎客製規則。"
            )

        # Phase 1.C：規則明細彈出（可展開查看當前生效的所有規則）
        with st.expander(f"🔍 查看 `{_hint}` 規則明細", expanded=False):
            tab_bl, tab_wl, tab_ctx = st.tabs([
                f"Blacklist ({len(_dash_tf.blacklist)})",
                f"Whitelist ({len(_dash_tf.whitelist)})",
                f"Contextual ({len(_dash_cc.rules)})",
            ])
            with tab_bl:
                if _dash_tf.blacklist:
                    import pandas as pd
                    st.dataframe(
                        pd.DataFrame(
                            [{"wrong (錯字)": w, "right (修正)": r}
                             for w, r in _dash_tf.blacklist.items()]
                        ),
                        use_container_width=True, hide_index=True,
                    )
                else:
                    st.caption("（無）")
            with tab_wl:
                if _dash_tf.whitelist:
                    st.write(", ".join(f"`{w}`" for w in _dash_tf.whitelist))
                else:
                    st.caption("（無）")
                if _dash_tf.protected_patterns:
                    st.caption("**Protected patterns（regex）**")
                    st.code("\n".join(p.pattern for p in _dash_tf.protected_patterns), language="regex")
            with tab_ctx:
                if _dash_cc.rules:
                    import pandas as pd
                    st.dataframe(
                        pd.DataFrame(
                            [{"prefix": r.prefix, "wrong (錯字)": r.wrong,
                              "suffix": r.suffix, "right (修正)": r.right,
                              "gap": r.gap, "note": r.note}
                             for r in _dash_cc.rules]
                        ),
                        use_container_width=True, hide_index=True,
                    )
                else:
                    st.caption("（無）")
    except Exception as _tf_err:
        st.caption(f"⚠️ 無法載入 TermFilter / ContextualCorrector 設定：{_tf_err}")

    # ── Step 7：彙整輸出 ─────────────────────────────────────────────────
    st.write("")
    st.subheader("Step 7　彙整輸出")
    merge_results = st.checkbox(
        "將辨識結果彙整到單一檔案",
        value=st.session_state.get("merge_results", False),
        key="merge_checkbox",
        help=(
            "依照檔名日期+時間排序，將所有辨識結果合併為一個文字檔。\n\n"
            "輸出資料夾命名格式：{事件名}_{日期}_{開始時分}-{結束時分}\n"
            "例：捷運火災_20251222_1922-1947"
        ),
    )

    event_name = st.session_state.get("event_name", "")
    if merge_results:
        event_name = st.text_input(
            "事件名稱　（必填）",
            value=event_name,
            key="event_name_input",
            placeholder="例如：捷運火災事故",
            help="用於命名輸出資料夾與彙整檔案，最多 30 個字",
            max_chars=30,
        )
        if not event_name.strip():
            st.warning("⚠️ 請輸入事件名稱，才能執行彙整輸出。")
    else:
        event_name = ""

    # ── 執行按鈕 ─────────────────────────────────────────────────────────
    st.divider()
    has_files  = bool(selected_upload_files or selected_server_files)
    can_execute = has_files and (not merge_results or bool(event_name.strip()))
    col_btn, col_hint = st.columns([2, 5])

    with col_btn:
        if st.button("執行辨識", type="primary", disabled=not can_execute, use_container_width=True):
            st.session_state["model_type"]     = model_type
            st.session_state["sub_model"]      = sub_model
            st.session_state["uploaded_files"] = selected_upload_files
            st.session_state["server_files"]   = selected_server_files
            st.session_state["use_vocabulary"] = use_vocabulary
            st.session_state["merge_results"]  = merge_results
            st.session_state["event_name"]     = event_name.strip()
            st.session_state["results"]             = []
            st.session_state["recognition_done"]    = False
            st.session_state["recognition_results"] = []
            st.session_state["page"]                = "running"
            st.rerun()

    with col_hint:
        if not has_files:
            st.caption("請先在上方載入至少一個音檔")
        elif merge_results and not event_name.strip():
            st.caption("請輸入事件名稱後再執行")


# ============================================================================
# 工具：inline diff 渲染（人工修正 UI 用）
# ============================================================================
def _render_inline_diff(raw: str, edited: str) -> None:
    """字元級 inline diff：紅色刪除（含刪除線）+ 綠色新增。"""
    import html as _html
    from difflib import SequenceMatcher
    sm = SequenceMatcher(None, raw or "", edited or "", autojunk=False)
    parts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        a = _html.escape(raw[i1:i2])
        b = _html.escape(edited[j1:j2])
        if tag == "equal":
            parts.append(a)
        elif tag == "delete":
            parts.append(
                f"<span style='background:#5a2a2a;color:#ffd6d6;"
                f"text-decoration:line-through;padding:0 2px;border-radius:2px'>{a}</span>"
            )
        elif tag == "insert":
            parts.append(
                f"<span style='background:#1f4d2a;color:#c8f7c8;"
                f"padding:0 2px;border-radius:2px'>{b}</span>"
            )
        elif tag == "replace":
            parts.append(
                f"<span style='background:#5a2a2a;color:#ffd6d6;"
                f"text-decoration:line-through;padding:0 2px;border-radius:2px'>{a}</span>"
            )
            parts.append(
                f"<span style='background:#1f4d2a;color:#c8f7c8;"
                f"padding:0 2px;border-radius:2px'>{b}</span>"
            )
    body = "".join(parts).replace("\n", "<br>")
    st.markdown(
        f"<div style='padding:12px;background:#1e1e1e;border-radius:6px;color:#e0e0e0;"
        f"font-family:monospace;line-height:1.7;white-space:pre-wrap;"
        f"border:1px solid #333'>{body}</div>",
        unsafe_allow_html=True,
    )


# ============================================================================
# 工具：Gemini 長音檔自動切段辨識
# ============================================================================
def transcribe_gemini_with_chunking(engine, audio_file: Path, output_dir: Path, max_duration: float = 1500.0) -> dict:
    """
    Gemini 長音檔辨識：超過 max_duration（預設 25 分鐘）自動切段。
    使用 pydub 按固定時長切段，逐段上傳 Gemini 辨識，最後合併結果。
    """
    from pydub import AudioSegment
    import logging
    _logger = logging.getLogger(__name__)

    try:
        audio = AudioSegment.from_file(str(audio_file))
        duration_sec = len(audio) / 1000.0
    except Exception as e:
        _logger.warning(f"⚠️ 無法讀取音檔時長，直接送 Gemini: {e}")
        return engine.transcribe_file(audio_file)

    # 短音檔直接辨識
    if duration_sec <= max_duration:
        _logger.info(f"音檔 {duration_sec:.0f}s <= {max_duration:.0f}s，直接辨識")
        return engine.transcribe_file(audio_file)

    # 長音檔：按 max_duration 切段
    chunk_length_ms = int(max_duration * 1000)
    total_ms = len(audio)
    num_chunks = (total_ms + chunk_length_ms - 1) // chunk_length_ms
    _logger.info(f"🔪 音檔 {duration_sec:.0f}s 超過 {max_duration:.0f}s，切為 {num_chunks} 段")

    chunks_dir = output_dir / "gemini_chunks" / audio_file.stem
    chunks_dir.mkdir(parents=True, exist_ok=True)

    all_transcripts = []
    for i in range(num_chunks):
        start_ms = i * chunk_length_ms
        end_ms = min((i + 1) * chunk_length_ms, total_ms)
        chunk = audio[start_ms:end_ms]

        chunk_file = chunks_dir / f"{audio_file.stem}_chunk_{i + 1:03d}.wav"
        chunk.export(str(chunk_file), format="wav")
        _logger.info(f"  段 {i + 1}/{num_chunks}: {start_ms // 1000}s ~ {end_ms // 1000}s ({chunk_file.name})")

        try:
            chunk_result = engine.transcribe_file(chunk_file)
            chunk_text = chunk_result.get("transcript", "").strip()
            if chunk_text:
                all_transcripts.append(chunk_text)
        except Exception as e:
            _logger.error(f"  ❌ 段 {i + 1} 辨識失敗: {e}")

    # 清理暫存切段
    import shutil
    shutil.rmtree(chunks_dir, ignore_errors=True)

    return {"transcript": "\n\n".join(all_transcripts)}


# ============================================================================
# 工具：Google STT VAD 切段辨識
# ============================================================================
def transcribe_google_stt_with_vad(engine, audio_file: Path, output_dir: Path, max_duration: float = 55.0) -> dict:
    import soundfile as sf
    try:
        info     = sf.info(str(audio_file))
        duration = info.duration
    except Exception:
        duration = 0

    if duration <= max_duration:
        return engine.transcribe_file(audio_file)

    from scripts.vad_preprocess import VADPreprocessor
    vad_chunks_dir = output_dir / "vad_chunks" / audio_file.stem
    vad_chunks_dir.mkdir(parents=True, exist_ok=True)

    preprocessor = VADPreprocessor(
        vad_method="energy", max_chunk_length=50.0,
        min_silence_duration=0.5, min_speech_duration=0.3,
    )
    vad_result = preprocessor.process_audio_file(audio_file, vad_chunks_dir)

    if vad_result.get("status") != "success" or vad_result.get("chunks", 0) == 0:
        return engine.transcribe_file(audio_file)

    chunk_files     = sorted(vad_chunks_dir.glob(f"{audio_file.stem}_chunk_*.wav"))
    all_transcripts = []
    has_diarization = False

    for chunk_file in chunk_files:
        try:
            chunk_result = engine.transcribe_file(chunk_file)
            chunk_text   = chunk_result.get("transcript", "").strip()
            if chunk_result.get("has_diarization"):
                has_diarization = True
            if chunk_text:
                all_transcripts.append(chunk_text)
        except Exception:
            pass

    separator = "\n\n" if has_diarization else " "
    return {"transcript": separator.join(all_transcripts), "has_diarization": has_diarization}


# ============================================================================
# 輔助函式：辨識完成後的結果區（可安全重複渲染，不會重觸辨識）
# ============================================================================
def _render_results_section(all_results, total, output_dir, timestamp,
                             merge_results, event_name, filename_datetimes):
    """顯示辨識摘要、下載按鈕、危害等級設定與返回首頁按鈕。"""
    success_count = sum(1 for r in all_results if r["status"] == "success")
    error_count   = total - success_count

    st.divider()
    st.success(f"辨識完成　成功：{success_count} 個　失敗：{error_count} 個")
    st.caption(f"結果已儲存至：`{output_dir}`")

    if merge_results and event_name:
        def _dt_sort_key(r):
            return filename_datetimes.get(Path(r["filename"]).stem, datetime.max)

        sorted_results = sorted(all_results, key=_dt_sort_key)
        sorted_dts_m   = sorted(filename_datetimes.values()) if filename_datetimes else []
        if sorted_dts_m:
            time_range = (
                f"{sorted_dts_m[0].strftime('%Y-%m-%d %H:%M')}"
                f" ─ {sorted_dts_m[-1].strftime('%Y-%m-%d %H:%M')}"
            )
        else:
            time_range = "（無法從檔名解析時間）"

        lines = [
            f"事件名稱：{event_name}",
            f"彙整時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"檔案數量：{len(sorted_results)} 個",
            f"時間範圍：{time_range}",
            "=" * 60, "",
        ]
        for r in sorted_results:
            dt         = filename_datetimes.get(Path(r["filename"]).stem)
            time_label = dt.strftime("%H:%M:%S") if dt else "??:??:??"
            lines.append(f"【{time_label}】{r['filename']}")
            if r["status"] == "success":
                lines.append(r["transcript"] if r["transcript"] else "（無辨識結果）")
            else:
                lines.append(f"（辨識失敗：{r.get('error', '未知錯誤')}）")
            lines.append("")

        merged_content  = "\n".join(lines)
        merged_filename = f"{event_name}_彙整.txt"
        merged_file     = output_dir / merged_filename
        merged_file.write_text(merged_content, encoding="utf-8")
        st.info(f"📄 彙整檔案已儲存：`{merged_filename}`")
        st.download_button(
            f"⬇️ 下載彙整結果（{merged_filename}）",
            data=merged_content.encode("utf-8"),
            file_name=f"{event_name}_彙整_{timestamp}.txt",
            mime="text/plain",
            key="dl_merged",
        )
    else:
        full_text = "\n\n".join(
            f"=== {r['filename']} ===\n{r['transcript']}" for r in all_results
        )
        st.download_button(
            "⬇️ 下載全部結果（TXT）",
            data=full_text.encode("utf-8"),
            file_name=f"asr_results_{timestamp}.txt",
            mime="text/plain",
            key="dl_all",
        )

    # ── 危害等級設定 ──────────────────────────────────────────────────────
    last_eid = st.session_state.get("last_event_id")
    if last_eid:
        st.divider()
        st.subheader("⚠️ 設定危害等級")
        selected_hazard = st.selectbox(
            "此次事件的危害等級",
            options=list(HAZARD_LABELS.keys()),
            format_func=lambda x: HAZARD_LABELS[x],
            index=0,
            key="hazard_select_running",
        )
        if st.button("💾 儲存危害等級", key="save_hazard_running"):
            try:
                from utils.db_manager import DBManager as _DBM
                _db = _DBM(DB_PATH)
                _db.update_event_hazard(last_eid, selected_hazard)
                _db.close()
                st.success(f"✅ 已儲存：{HAZARD_LABELS[selected_hazard]}")
            except Exception as _he:
                st.warning(f"⚠️ 儲存失敗：{_he}")

    st.divider()
    if st.button("回到批次辨識", type="primary", key="go_home_final"):
        shutil.rmtree(TEMP_UPLOAD_DIR / "source_audio", ignore_errors=True)
        st.session_state["page"] = "speech"
        st.rerun()




# ============================================================================
# 頁面：執行辨識
# ============================================================================
def render_running_page():
    model_type     = st.session_state["model_type"]
    sub_model      = st.session_state["sub_model"]
    use_vocabulary = st.session_state.get("use_vocabulary", True)
    merge_results  = st.session_state.get("merge_results", False)
    event_name     = st.session_state.get("event_name", "").strip()
    uploaded_files = st.session_state.get("uploaded_files") or []
    server_files   = st.session_state.get("server_files") or []
    use_vad        = st.session_state.get("preproc_vad",     False)
    use_denoise    = st.session_state.get("preproc_denoise", False)
    vad_threshold  = float(st.session_state.get("preproc_vad_thr", 0.5))

    model_label = {v: k for k, v in MODEL_OPTIONS.items()}.get(model_type, model_type)

    if st.button("← 返回設定", key="back_speech"):
        st.session_state["page"] = "speech"
        st.rerun()

    st.title("執行語音辨識")
    vocab_badge   = "🟢 詞彙優化：開啟" if use_vocabulary else "⚫ 詞彙優化：關閉"
    merge_badge   = f"　　🔵 彙整輸出：{event_name}" if (merge_results and event_name) else ""
    _preproc_parts = []
    if use_vad:     _preproc_parts.append(f"VAD({vad_threshold:.2f})")
    if use_denoise: _preproc_parts.append("降噪")
    preproc_badge = f"　　🔧 前處理：{'+'.join(_preproc_parts)}" if _preproc_parts else ""
    st.write(f"模型：**{model_label}**　　子模型：`{sub_model}`　　{vocab_badge}{merge_badge}{preproc_badge}")
    st.divider()

    # ── 準備音檔清單 ──────────────────────────────────────────────────────
    audio_paths = []
    if uploaded_files:
        upload_dir = TEMP_UPLOAD_DIR / "source_audio"
        upload_dir.mkdir(parents=True, exist_ok=True)
        for uf in uploaded_files:
            dest = upload_dir / uf.name
            dest.write_bytes(uf.getbuffer())
            audio_paths.append(dest)
    audio_paths.extend([Path(p) for p in server_files])

    if not audio_paths:
        st.error("找不到音檔，請返回重新選擇。")
        return

    # ── 輸出目錄 ──────────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_datetimes: dict = {}
    for p in audio_paths:
        dt = parse_filename_datetime(p.stem)
        if dt:
            filename_datetimes[p.stem] = dt

    if merge_results and event_name:
        sorted_dts = sorted(filename_datetimes.values())
        if sorted_dts:
            date_str    = sorted_dts[0].strftime("%Y%m%d")
            start_hhmm  = sorted_dts[0].strftime("%H%M")
            end_hhmm    = sorted_dts[-1].strftime("%H%M")
            folder_name = f"{event_name}_{date_str}_{start_hhmm}-{end_hhmm}_{sub_model}"
        else:
            folder_name = f"{event_name}_{timestamp}_{sub_model}"
        output_dir = TEMP_UPLOAD_DIR / "ASR_Evaluation" / folder_name
    elif model_type == "hybrid":
        output_dir = TEMP_UPLOAD_DIR / "ASR_Evaluation" / f"hybrid_google+{sub_model}_{timestamp}"
    else:
        output_dir = TEMP_UPLOAD_DIR / "ASR_Evaluation" / f"{model_type}_{sub_model}_{timestamp}"

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 若已辨識完畢，直接從 session_state 取回結果，跳過辨識迴圈 ────────
    if st.session_state.get("recognition_done"):
        _render_results_section(
            all_results          = st.session_state["recognition_results"],
            total                = st.session_state["recognition_total"],
            output_dir           = Path(st.session_state["recognition_output_dir"]),
            timestamp            = st.session_state["recognition_timestamp"],
            merge_results        = merge_results,
            event_name           = event_name,
            filename_datetimes   = st.session_state.get("recognition_filename_datetimes", {}),
        )
        return

    # ── 初始化模型 ────────────────────────────────────────────────────────
    total        = len(audio_paths)
    progress_bar = st.progress(0, text="初始化模型中，請稍候...")
    status_msg   = st.empty()
    all_results  = []

    try:
        from scripts.batch_inference import BatchInference, setup_google_credentials
        setup_google_credentials()

        PHRASESET_INCOMPATIBLE = {"chirp_3", "chirp_3_hans"}
        vocabulary_file = None
        if use_vocabulary and model_type == "google_stt" and sub_model not in PHRASESET_INCOMPATIBLE:
            vocab_path = PROJECT_ROOT / "vocabulary" / "google_phrases.json"
            if vocab_path.exists():
                vocabulary_file = str(vocab_path)

        if model_type == "google_stt" and sub_model == "chirp_3_hans":
            actual_stt_model     = "chirp_3"
            actual_language_code = "cmn-Hans-CN"
        else:
            actual_stt_model     = sub_model
            actual_language_code = "cmn-Hant-TW"

        if model_type == "whisper":
            from scripts.models.model_whisper import transcribe_with_whisper as whisper_transcribe
            engine = None
        elif model_type == "hybrid":
            # hybrid：Google STT chirp_3（固定）+ Gemini（sub_model 為 Gemini 版本）
            engine = BatchInference(
                input_dir=str(audio_paths[0].parent),
                output_dir=str(output_dir),
                model_type="hybrid",
                stt_model="chirp_3",
                gemini_model=sub_model,
                vocabulary_file=vocabulary_file,
                language_code="cmn-Hant-TW",
            )
        elif model_type == "sensevoice":
            engine = BatchInference(
                input_dir=str(audio_paths[0].parent),
                output_dir=str(output_dir),
                model_type="sensevoice",
            )
        elif model_type == "sensevoice_ft":
            engine = BatchInference(
                input_dir=str(audio_paths[0].parent),
                output_dir=str(output_dir),
                model_type="sensevoice_ft",
            )
        else:
            engine = BatchInference(
                input_dir=str(audio_paths[0].parent),
                output_dir=str(output_dir),
                model_type=model_type,
                stt_model=actual_stt_model if model_type == "google_stt" else "chirp_3",
                gemini_model=sub_model if model_type == "gemini" else "gemini-2.5-flash",
                vocabulary_file=vocabulary_file,
                language_code=actual_language_code if model_type == "google_stt" else "cmn-Hant-TW",
            )

        status_msg.empty()

        # ── 匯入前處理工具（懶載入，避免未安裝時整頁崩潰）─────────────────
        _denoise_fn  = None
        _vad_fn      = None
        if use_denoise:
            try:
                from utils.noise_filter import denoise_wav_file as _denoise_fn
            except ImportError:
                st.warning("⚠️ DeepFilterNet 未安裝，降噪功能略過（pip install deepfilternet）")
                use_denoise = False
        if use_vad:
            try:
                from utils.vad_filter import has_speech_in_wav_sr as _vad_fn
            except ImportError:
                st.warning("⚠️ Silero VAD 未安裝，VAD 功能略過（pip install silero-vad）")
                use_vad = False

        for i, audio_file in enumerate(audio_paths):
            audio_file = Path(audio_file)
            progress_bar.progress(i / total, text=f"辨識中：{audio_file.name}  ({i + 1}/{total})")
            try:
                # ── 音訊前處理（降噪 → VAD）─────────────────────────────────
                preproc_file = audio_file   # 預設使用原始檔
                _skipped     = False

                if (use_denoise or use_vad) and audio_file.suffix.lower() == ".wav":
                    import shutil as _shutil
                    import tempfile as _tempfile
                    # 複製到暫存檔，避免修改原始音檔
                    _tmp_fd, _tmp_path = _tempfile.mkstemp(suffix=".wav", prefix="preproc_")
                    os.close(_tmp_fd)
                    _shutil.copy2(str(audio_file), _tmp_path)
                    preproc_file = Path(_tmp_path)

                    if use_denoise and _denoise_fn:
                        _, _ok = _denoise_fn(str(preproc_file), output_wav=str(preproc_file))
                        if not _ok:
                            st.caption(f"　　ℹ️ {audio_file.name}：降噪模組不可用，使用原始音訊")

                    if use_vad and _vad_fn:
                        _has_speech = _vad_fn(str(preproc_file), threshold=vad_threshold)
                        if not _has_speech:
                            st.info(f"🔇 {audio_file.name}　→ VAD 判定無語音，略過 STT")
                            all_results.append({
                                "filename": audio_file.name,
                                "transcript": "",
                                "status": "skipped_vad",
                            })
                            preproc_file.unlink(missing_ok=True)
                            _skipped = True

                if _skipped:
                    continue

                # ── smart-preproc：依引擎 overlay 自動套用 ffmpeg loudnorm ────
                # 規則：vocabulary/engines/{engine}.json 的 audio_preprocess.enabled=true 才套
                # 04-29 baseline 實證：gemini-2.5-pro / sensevoice 可改善 -0.5%；
                #                       chirp3 / scribe 反而退步，已停用
                try:
                    from scripts.term_filter import get_engine_audio_preprocess as _get_ap
                    _ap_cfg = _get_ap(sub_model or model_type)
                    if _ap_cfg.get("enabled") and preproc_file.suffix.lower() == ".wav":
                        import subprocess as _subp
                        import tempfile as _tempfile
                        _ap_fd, _ap_path = _tempfile.mkstemp(suffix=".wav", prefix="loudnorm_")
                        os.close(_ap_fd)
                        _ap_filter = _ap_cfg.get("filter") or "loudnorm=I=-16:TP=-1.5:LRA=11"
                        _ap_cmd = [
                            "ffmpeg", "-y", "-i", str(preproc_file),
                            "-af", _ap_filter,
                            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                            _ap_path,
                        ]
                        _ap_proc = _subp.run(_ap_cmd, capture_output=True, timeout=120)
                        if _ap_proc.returncode == 0:
                            # 若原 preproc_file 是 denoise/vad 產生的暫存檔，先 unlink
                            if preproc_file != audio_file:
                                preproc_file.unlink(missing_ok=True)
                            preproc_file = Path(_ap_path)
                        else:
                            Path(_ap_path).unlink(missing_ok=True)
                            st.caption(f"　　ℹ️ {audio_file.name}：smart-preproc loudnorm 失敗，使用原始音訊")
                except Exception as _ape:
                    st.caption(f"　　ℹ️ smart-preproc 略過：{_ape}")

                if model_type == "whisper":
                    raw_text = whisper_transcribe(str(preproc_file), model_size=sub_model)
                    result   = {"transcript": raw_text}
                elif model_type == "google_stt":
                    result = transcribe_google_stt_with_vad(engine, preproc_file, output_dir)
                elif model_type == "gemini":
                    result = transcribe_gemini_with_chunking(engine, preproc_file, output_dir)
                else:
                    # hybrid / sensevoice / sensevoice_ft 共用此路徑
                    result = engine.transcribe_file(preproc_file)

                # 暫存檔清理
                if preproc_file != audio_file:
                    preproc_file.unlink(missing_ok=True)

                transcript = result.get("transcript", "")

                # SenseVoice / Whisper 輸出為簡體中文，轉換為繁體中文（台灣用詞）
                if model_type in ("sensevoice", "sensevoice_ft", "whisper") and transcript:
                    try:
                        import opencc as _opencc
                        _cc = _opencc.OpenCC("s2twp")
                        transcript = _cc.convert(transcript)
                    except ImportError:
                        pass

                # ── 後處理 Pipeline（Step 6）─────────────────────────────
                # 讀取使用者在 Step 6 設定的開關
                _pp_car  = st.session_state.get("pp_car_norm", True)
                _pp_dict = st.session_state.get("pp_dict", True) and use_vocabulary
                _pp_llm  = st.session_state.get("pp_llm", False)
                _pp_model    = st.session_state.get("pp_llm_model", "gemini-2.5-flash")
                _pp_strict   = st.session_state.get("pp_llm_strict", "conservative")
                _pp_smart_skip = st.session_state.get("pp_llm_smart_skip", True)
                _pp_engine_hint = st.session_state.get("pp_engine_hint", model_type)

                _pp_report = None
                if transcript and (_pp_car or _pp_dict or _pp_llm):
                    try:
                        from scripts.post_process import post_process as _post_process
                        transcript, _pp_report = _post_process(
                            transcript,
                            enable_car_norm=_pp_car,
                            enable_dict=_pp_dict,
                            enable_llm=_pp_llm,
                            llm_model=_pp_model,
                            llm_strictness=_pp_strict,
                            engine_hint=_pp_engine_hint,
                            auto_skip_llm_for_high_quality=_pp_smart_skip,
                        )
                    except Exception as _ppe:
                        # fallback：仍套用舊版 fix_radio_jargon
                        if use_vocabulary:
                            try:
                                from utils.text_cleaner import fix_radio_jargon
                                transcript = fix_radio_jargon(transcript)
                            except Exception:
                                pass
                        st.warning(f"⚠️ 後處理 pipeline 失敗，已退回舊版修正：{_ppe}")
                elif use_vocabulary and transcript:
                    # 三層全部關閉但使用者勾選了詞彙修正：保留向後相容
                    try:
                        from utils.text_cleaner import fix_radio_jargon
                        transcript = fix_radio_jargon(transcript)
                    except Exception:
                        pass

                txt_file = output_dir / f"{audio_file.stem}.txt"
                txt_file.write_text(transcript, encoding="utf-8")
                _result_entry = {"filename": audio_file.name, "transcript": transcript, "status": "success"}
                if _pp_report:
                    _result_entry["post_process"] = _pp_report
                all_results.append(_result_entry)
                st.success(f"**{audio_file.name}**　完成")
                st.text_area(
                    label="辨識結果",
                    value=transcript if transcript else "（無辨識結果）",
                    height=80, key=f"result_{i}", disabled=True,
                )

                # smart_skip 通知（即使 total_changes=0 也顯示）
                if _pp_report:
                    for _s in _pp_report.get("stages", []):
                        if _s["name"] == "llm" and _s.get("skipped_reason"):
                            st.info(f"🛡️ **LLM 智能跳過**：{_s['skipped_reason']}")
                            break

                # 後處理修正診斷面板
                if _pp_report and _pp_report.get("total_changes", 0) > 0:
                    _stage_summary = "　".join(
                        f"{s['name']}={s['change_count']}"
                        for s in _pp_report["stages"] if s["applied"]
                    )
                    with st.expander(
                        f"🔧 後處理修正　共 {_pp_report['total_changes']} 處　[{_stage_summary}]",
                        key=f"expander_pp_{i}",
                    ):
                        for _s in _pp_report["stages"]:
                            if not _s["applied"] or _s["change_count"] == 0:
                                continue
                            _label = {
                                "car_norm": "🚆 車廂編號正規化",
                                "dict":     "📖 詞彙字典修正",
                                "llm":      "🤖 LLM 後修正",
                            }.get(_s["name"], _s["name"])
                            st.caption(f"**{_label}**　({_s['change_count']} 處)")
                            if _s.get("error"):
                                st.warning(_s["error"])
                            for _c in _s["changes"][:20]:
                                _from = _c.get("from", "")
                                _to   = _c.get("to", "")
                                _rule = _c.get("rule") or _c.get("type", "")
                                _cnt  = f" ×{_c['count']}" if _c.get("count", 0) > 1 else ""
                                st.markdown(f"- `{_from}` → `{_to}`{_cnt}　_{_rule}_")
                            if len(_s["changes"]) > 20:
                                st.caption(f"... 還有 {len(_s['changes']) - 20} 處未顯示")
                # hybrid 模式：顯示融合診斷資訊
                if model_type == "hybrid":
                    _rule         = result.get("rule", "")
                    _source       = result.get("source", "")
                    _cer_between  = result.get("cer_between")
                    _g_text       = result.get("google_transcript", "")
                    _m_text       = result.get("gemini_transcript", "")
                    _source_label = {"google": "Google STT", "gemini": "Gemini", "scribe": "Scribe", "": "（空）"}.get(_source, _source)
                    _cer_str      = f"{_cer_between:.1%}" if _cer_between is not None else "N/A"
                    with st.expander(
                        f"🔀 融合診斷　規則={_rule}　來源={_source_label}　CER(G↔M)={_cer_str}",
                        key=f"expander_fuse_{i}",
                    ):
                        col_g, col_m = st.columns(2)
                        with col_g:
                            st.caption("**Google STT（chirp_3）**")
                            st.text(_g_text or "（無結果）")
                        with col_m:
                            st.caption(f"**Gemini（{sub_model}）**")
                            st.text(_m_text or "（無結果）")

                # SenseVoice 模式：顯示情緒/事件偵測結果
                if model_type in ("sensevoice", "sensevoice_ft"):
                    _emotion_label = result.get("emotion_label")
                    _events        = result.get("events", [])
                    _segments      = result.get("segments", [])
                    _parts = []
                    if _emotion_label:
                        _parts.append(f"情緒：{_emotion_label}")
                    _notable_events = [e for e in _events if "語音" not in e]
                    if _notable_events:
                        _parts.append(f"事件：{' '.join(_notable_events)}")
                    if _parts:
                        st.caption("　　".join(_parts))
                    if _segments:
                        with st.expander(f"🔍 逐段詳細結果（{len(_segments)} 段）",
                                         key=f"expander_sv_{i}"):
                            for seg in _segments:
                                _conf = "🟢" if (seg.get("no_speech_prob", 0) < 0.3) else "🟡"
                                _ts   = f"{seg['start']:.1f}s → {seg['end']:.1f}s"
                                _emo  = seg.get("emotion_label") or ""
                                _evts = " ".join(
                                    e for e in seg.get("events", []) if "語音" not in e
                                )
                                _line = f"{_conf} **[{_ts}]** {seg['text']}"
                                if _emo:
                                    _line += f"　{_emo}"
                                if _evts:
                                    _line += f"　{_evts}"
                                st.markdown(_line)
            except Exception as e:
                all_results.append({"filename": audio_file.name, "transcript": "", "status": "error", "error": str(e)})
                st.error(f"**{audio_file.name}**　辨識失敗：{e}")

        progress_bar.progress(1.0, text=f"完成！共處理 {total} 個檔案")

        json_file = output_dir / f"results_{timestamp}.json"
        json_file.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

        # ── 快取辨識結果，防止 Streamlit re-run 重複辨識 ──────────────
        st.session_state["recognition_done"]               = True
        st.session_state["recognition_results"]            = all_results
        st.session_state["recognition_total"]              = total
        st.session_state["recognition_output_dir"]         = str(output_dir)
        st.session_state["recognition_timestamp"]          = timestamp
        st.session_state["recognition_filename_datetimes"] = filename_datetimes

        # ── 儲存至資料庫 ──────────────────────────────────────────────
        try:
            from utils.db_manager import DBManager
            from utils.audio_archiver import AudioArchiver

            db       = DBManager(DB_PATH)
            archiver = AudioArchiver(PROJECT_ROOT / "data" / "audio_archive")

            sorted_dts_db   = sorted(filename_datetimes.values()) if filename_datetimes else []
            event_date_db   = sorted_dts_db[0].date() if sorted_dts_db else None
            effective_name  = event_name if event_name else f"{model_type}_{sub_model}_{timestamp}"

            event_id = db.create_event(
                event_name=effective_name,
                model_type=model_type,
                sub_model=sub_model,
                event_date=event_date_db,
            )

            for result in all_results:
                fname    = result["filename"]
                src_path = next((p for p in audio_paths if p.name == fname), None)
                arc_path, file_hash, file_size = None, None, None
                if src_path and Path(src_path).exists():
                    try:
                        arc_path, file_hash, file_size = archiver.archive_file(
                            Path(src_path), effective_name,
                            ref_datetime=sorted_dts_db[0] if sorted_dts_db else None,
                        )
                        arc_path = str(arc_path)
                    except Exception:
                        pass

                audio_id = db.save_audio_file(
                    event_id=event_id,
                    original_filename=fname,
                    archive_path=arc_path,
                    file_hash=file_hash,
                    file_size=file_size,
                    recorded_at=filename_datetimes.get(Path(fname).stem),
                )
                _tid = db.save_transcription(
                    audio_file_id=audio_id,
                    event_id=event_id,
                    transcript=result.get("transcript", ""),
                    status=result.get("status", "success"),
                    error_message=result.get("error"),
                    use_vad=use_vad,
                    use_denoise=use_denoise,
                )

                # #17 版本管理：寫入 raw / after_car_norm / after_dict / after_llm
                _pp_rep = result.get("post_process") or {}
                _snapshots = _pp_rep.get("snapshots") or {}
                if _snapshots and _tid:
                    try:
                        db.update_transcript_stages(
                            transcription_id=_tid,
                            snapshots=_snapshots,
                            engine_hint=sub_model or model_type,
                        )
                    except Exception as _vse:
                        st.caption(f"　　⚠️ 版本快照寫入失敗（不影響辨識結果）：{_vse}")

                # #5 逐字 confidence：scribe 才有 'words' 欄位
                _words = result.get("words") or []
                if _words and _tid:
                    try:
                        db.update_word_confidences(transcription_id=_tid, words=_words)
                    except Exception as _wce:
                        st.caption(f"　　⚠️ 逐字 confidence 寫入失敗（不影響辨識結果）：{_wce}")

            db.close()
            st.session_state["last_event_id"] = event_id
            st.info(f"💾 已儲存至資料庫（事件 ID: {event_id}，共 {len(all_results)} 筆）")

        except Exception as db_err:
            st.warning(f"⚠️ 資料庫儲存失敗（不影響辨識結果）：{db_err}")

        # ── 辨識完成後顯示結果區 ──────────────────────────────────────
        _render_results_section(
            all_results        = all_results,
            total              = total,
            output_dir         = output_dir,
            timestamp          = timestamp,
            merge_results      = merge_results,
            event_name         = event_name,
            filename_datetimes = filename_datetimes,
        )

    except Exception as e:
        progress_bar.empty()
        status_msg.empty()
        st.error(f"執行失敗：{e}")
        with st.expander("詳細錯誤訊息"):
            st.code(traceback.format_exc())


# ============================================================================
# 頁面：事件管理
# ============================================================================
def render_management_page():
    if st.button("← 回到批次辨識", key="back_home_mgmt"):
        st.session_state["page"] = "speech"
        st.rerun()

    st.title("📋 事件管理")
    st.caption("瀏覽歷史辨識事件，設定危害等級，管理 AI 與手動關鍵字。")
    st.divider()

    try:
        from utils.db_manager import DBManager
        db = DBManager(DB_PATH)
    except Exception as e:
        st.error(f"無法連線資料庫：{e}")
        return

    events = db.list_events(limit=200)
    if not events:
        st.info("📭 尚無事件記錄。請先執行語音辨識以建立事件。")
        db.close()
        return

    def _event_label(e):
        date_str   = (e["event_date"] or "")[:10]
        hazard     = e["hazard_level"] or 0
        hazard_tag = f"[L{hazard}] " if hazard > 0 else ""
        return f"{hazard_tag}{date_str}　{e['event_name']}　（{e['model_type']}/{e['sub_model']}）"

    event_labels = [_event_label(e) for e in events]
    selected_idx = st.selectbox(
        "選擇事件",
        options=range(len(events)),
        format_func=lambda i: event_labels[i],
        key="mgmt_event_select",
    )
    ev       = events[selected_idx]
    event_id = ev["id"]
    st.divider()

    # ── 基本資訊 ──────────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("事件名稱", ev["event_name"])
    m2.metric("事件日期", (ev["event_date"] or "—")[:10])
    m3.metric("模型", f"{ev['model_type']} / {ev['sub_model']}")
    m4.metric("建立時間", (ev["created_at"] or "—")[:16])
    st.divider()

    # ── 危害等級 ──────────────────────────────────────────────────────────
    st.subheader("⚠️ 危害等級")
    current_hazard = ev["hazard_level"] or 0
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        new_hazard = st.selectbox(
            "危害等級",
            options=list(HAZARD_LABELS.keys()),
            format_func=lambda x: HAZARD_LABELS[x],
            index=current_hazard,
            key=f"hazard_sel_{event_id}",
            label_visibility="collapsed",
        )
    with col_h2:
        if st.button("💾 更新", key=f"save_hazard_{event_id}", use_container_width=True):
            db.update_event_hazard(event_id, new_hazard)
            st.success(f"✅ 已更新：{HAZARD_LABELS[new_hazard]}")
            st.rerun()

    # ── 備注 ──────────────────────────────────────────────────────────────
    st.subheader("📝 備注")
    current_notes = ev["notes"] or ""
    new_notes = st.text_area(
        "備注", value=current_notes, height=80,
        key=f"notes_{event_id}", label_visibility="collapsed", placeholder="輸入事件備注…",
    )
    if st.button("💾 儲存備注", key=f"save_notes_{event_id}"):
        db.update_event_notes(event_id, new_notes)
        st.success("✅ 備注已儲存")
        st.rerun()

    st.divider()

    # ── 辨識結果（含人工修正） ─────────────────────────────────────────────
    st.subheader("📄 辨識結果")
    transcriptions = db.get_event_transcriptions(event_id)
    if not transcriptions:
        st.info("此事件無辨識結果。")
    else:
        # 統計：已修正幾筆
        _corrected_n = sum(1 for t in transcriptions if t["corrected_transcript"])
        if _corrected_n > 0:
            st.caption(f"✏️ 已人工修正 **{_corrected_n}** / {len(transcriptions)} 筆")

        for t in transcriptions:
            rec_time    = (t["recorded_at"] or "??:??:??")[:19]
            fname       = t["original_filename"]
            status_icon = "✅" if t["status"] == "success" else "❌"
            corrected_icon = "  ✏️" if t["corrected_transcript"] else ""
            with st.expander(f"{status_icon}{corrected_icon} {rec_time}　{fname}"):
                if t["status"] == "success":
                    raw_text = t["transcript"] or ""
                    edit_key = f"trans_edit_{t['id']}"
                    # 預設值：已有修正版本則用之，否則用原文
                    if edit_key not in st.session_state:
                        st.session_state[edit_key] = t["corrected_transcript"] or raw_text

                    edited = st.text_area(
                        "辨識文字（可直接編輯，diff 會即時顯示）",
                        height=120,
                        key=edit_key,
                    )

                    # ── inline diff highlight（即時對照原文 vs 當前編輯）─────
                    if edited != raw_text:
                        st.caption("🔍 與原文差異（紅刪/綠增）")
                        _render_inline_diff(raw_text, edited)
                    else:
                        st.caption("（與原文相同）")

                    # ── #5 逐字 confidence 標記（低信心字標黃底）─────────────
                    _words_conf = db.get_word_confidences(t["id"])
                    if _words_conf:
                        # 統計信心分布
                        _high = sum(1 for w in _words_conf if w.get("confidence", 1.0) >= 0.9)
                        _mid  = sum(1 for w in _words_conf if 0.7 <= w.get("confidence", 1.0) < 0.9)
                        _low  = sum(1 for w in _words_conf if w.get("confidence", 1.0) < 0.7)
                        _total = len(_words_conf)
                        with st.expander(
                            f"🟡 逐字 confidence 標記（{_total} 字 · "
                            f"🟢{_high} 🟡{_mid} 🔴{_low}）",
                            expanded=(_low > 0),
                        ):
                            import html as _html
                            parts = []
                            for w in _words_conf:
                                txt = _html.escape(w.get("text", ""))
                                conf = w.get("confidence", 1.0)
                                if conf < 0.7:
                                    parts.append(
                                        f"<span style='background:#5a4a1a;color:#fff3cd;"
                                        f"padding:0 2px;border-radius:2px' "
                                        f"title='conf={conf:.3f}'>{txt}</span>"
                                    )
                                elif conf < 0.9:
                                    parts.append(
                                        f"<span style='background:#3a3a1a;color:#e8e0a0;"
                                        f"padding:0 2px;border-radius:2px' "
                                        f"title='conf={conf:.3f}'>{txt}</span>"
                                    )
                                else:
                                    parts.append(txt)
                            html_str = "".join(parts).replace("\n", "<br>")
                            st.markdown(
                                f"<div style='padding:12px;background:#1e1e1e;border-radius:6px;"
                                f"color:#e0e0e0;font-family:monospace;line-height:1.8;"
                                f"white-space:pre-wrap;border:1px solid #333'>{html_str}</div>",
                                unsafe_allow_html=True,
                            )
                            st.caption(
                                "💡 黃底：信心 0.7~0.9 ｜ 深黃底：信心 < 0.7（重點檢查）"
                            )

                    # ── #17 版本管理：各階段對照 ─────────────────────────────
                    _stages = db.get_transcript_stages(t["id"])
                    if _stages and any(_stages.get(k) for k in
                                       ("raw_transcript", "after_car_norm", "after_dict", "after_llm")):
                        with st.expander("📊 各階段對照（raw → car_norm → dict → llm → final）", expanded=False):
                            _ss = [
                                ("raw",            _stages.get("raw_transcript"),  "原始 STT"),
                                ("after_car_norm", _stages.get("after_car_norm"),  "車號+數字正規化後"),
                                ("after_dict",     _stages.get("after_dict"),      "dict + contextual 後"),
                                ("after_llm",      _stages.get("after_llm"),       "LLM 後修正後"),
                                ("final",          _stages.get("final_transcript"),"最終（= transcript 欄）"),
                                ("corrected",      _stages.get("corrected_transcript"), "✏️ 人工修正"),
                            ]
                            for _name, _val, _desc in _ss:
                                if not _val:
                                    continue
                                st.caption(f"**{_name}** — {_desc}")
                                st.code(_val[:300] + ("…" if len(_val) > 300 else ""), language=None)

                    col_a, col_b, col_c = st.columns([1, 1, 4])
                    save_clicked = col_a.button("💾 儲存修正", key=f"save_{t['id']}", type="primary")
                    revert_clicked = col_b.button("↩️ 還原原文", key=f"revert_{t['id']}")
                    if t["corrected_transcript"]:
                        col_c.caption(
                            f"上次修正：{(t['corrected_at'] or '')[:19]}"
                            + (f"  ｜  引擎：{t['engine_hint']}" if t['engine_hint'] else "")
                        )

                    if save_clicked:
                        if edited.strip() == raw_text.strip():
                            st.info("與原文相同，未儲存修正")
                        else:
                            _hint = st.session_state.get("pp_engine_hint")
                            db.update_corrected_transcript(t["id"], edited, engine_hint=_hint)
                            st.success("✅ 修正已儲存（將供 extract_error_pairs 抽規則用）")
                            st.rerun()
                    elif revert_clicked:
                        if t["corrected_transcript"]:
                            db.update_corrected_transcript(t["id"], "")  # 空字串 = 清除修正
                            # 清掉 session state 的編輯內容，下次 rerun 會用 raw_text
                            st.session_state.pop(edit_key, None)
                            st.success("已清除人工修正，恢復原文")
                            st.rerun()
                        else:
                            # 還沒儲存的編輯狀態：把 textarea 內容重置為原文
                            st.session_state[edit_key] = raw_text
                            st.rerun()
                else:
                    st.error(f"辨識失敗：{t['transcript']}")

    st.divider()

    # ── 關鍵字管理 ────────────────────────────────────────────────────────
    st.subheader("🔑 關鍵字")
    keywords   = db.get_event_keywords(event_id)
    ai_kws     = [k for k in keywords if k["source"] == "ai"]
    manual_kws = [k for k in keywords if k["source"] == "manual"]

    kw_col1, kw_col2 = st.columns(2)
    with kw_col1:
        st.markdown("**🤖 AI 擷取**")
        if ai_kws:
            for kw in ai_kws:
                lv = kw["hazard_level"]
                c1, c2 = st.columns([4, 1])
                c1.markdown(
                    f"`{kw['keyword']}` "
                    f"<span style='color:{'#e74c3c' if lv>=4 else '#f39c12' if lv>=2 else '#27ae60'};'>L{lv}</span>",
                    unsafe_allow_html=True,
                )
                if c2.button("×", key=f"del_kw_{kw['id']}", help="刪除"):
                    db.delete_keyword(kw["id"])
                    st.rerun()
        else:
            st.caption("尚無 AI 關鍵字")

    with kw_col2:
        st.markdown("**✏️ 手動新增**")
        if manual_kws:
            for kw in manual_kws:
                lv = kw["hazard_level"]
                c1, c2 = st.columns([4, 1])
                c1.markdown(
                    f"`{kw['keyword']}` "
                    f"<span style='color:{'#e74c3c' if lv>=4 else '#f39c12' if lv>=2 else '#27ae60'};'>L{lv}</span>",
                    unsafe_allow_html=True,
                )
                if c2.button("×", key=f"del_mkw_{kw['id']}", help="刪除"):
                    db.delete_keyword(kw["id"])
                    st.rerun()
        else:
            st.caption("尚無手動關鍵字")

    # ── CSV 下載 ──────────────────────────────────────────────────────────
    st.write("")
    if keywords:
        import io as _io
        _kw_buf = _io.StringIO()
        _kw_writer = csv.writer(_kw_buf)
        _kw_writer.writerow(["keyword", "hazard_level", "source"])
        for kw in keywords:
            _kw_writer.writerow([kw["keyword"], kw["hazard_level"], kw["source"]])
        st.download_button(
            label=f"⬇️ 下載關鍵字 CSV（{len(keywords)} 筆）",
            data=_kw_buf.getvalue().encode("utf-8-sig"),
            file_name=f"keywords_event{event_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            key=f"dl_kw_{event_id}",
        )

    st.write("")
    with st.expander("＋ 手動新增關鍵字"):
        add_col1, add_col2, add_col3 = st.columns([3, 2, 1])
        with add_col1:
            new_kw = st.text_input("關鍵字", key=f"new_kw_{event_id}", placeholder="e.g. 疏散")
        with add_col2:
            new_kw_hazard = st.selectbox(
                "危害等級", options=list(HAZARD_LABELS.keys()),
                format_func=lambda x: HAZARD_LABELS[x], key=f"new_kw_hazard_{event_id}",
            )
        with add_col3:
            st.write("")
            st.write("")
            if st.button("＋ 新增", key=f"add_kw_{event_id}", use_container_width=True):
                if new_kw.strip():
                    _kw_text = new_kw.strip()
                    _existing = db.find_keyword_in_event(event_id, _kw_text)
                    if _existing and _existing["hazard_level"] == new_kw_hazard:
                        st.warning(f"⚠️ 關鍵字「{_kw_text}」已存在（L{_existing['hazard_level']}），未重複新增")
                    elif _existing:
                        st.warning(
                            f"⚠️ 關鍵字「{_kw_text}」已存在但危害等級不同"
                            f"（現有 L{_existing['hazard_level']} → 新設 L{new_kw_hazard}）"
                            f"，請至列表刪除後再新增，或確認等級設定。"
                        )
                    else:
                        db.add_keyword(event_id=event_id, keyword=_kw_text, source="manual", hazard_level=new_kw_hazard)
                        st.success(f"✅ 已新增關鍵字：{_kw_text}")
                        st.rerun()
                else:
                    st.warning("請輸入關鍵字")

    # ── CSV 上傳匯入 ──────────────────────────────────────────────────────
    with st.expander("📤 從 CSV 匯入關鍵字"):
        st.caption("格式：`keyword,hazard_level,source`（source 可省略，預設 manual）")
        uploaded_kw_csv = st.file_uploader(
            "選擇關鍵字 CSV 檔案",
            type=["csv"],
            key=f"upload_kw_{event_id}",
            help="請上傳符合下載格式的 CSV 檔（UTF-8 或 UTF-8 BOM）",
        )
        if uploaded_kw_csv is not None:
            try:
                import io as _io
                _raw = uploaded_kw_csv.read().decode("utf-8-sig").strip()
                _reader = csv.DictReader(_io.StringIO(_raw))

                # 驗證必要欄位
                if "keyword" not in (_reader.fieldnames or []):
                    st.error("❌ CSV 格式錯誤：缺少 `keyword` 欄位")
                else:
                    _rows = [r for r in _reader if r.get("keyword", "").strip()]

                    if not _rows:
                        st.warning("⚠️ CSV 內容為空，無可匯入的關鍵字")
                    else:
                        # ── 逐筆分析：分成三類 ───────────────────────────
                        _to_import   = []   # 可直接匯入
                        _exact_dup   = []   # 完全重複（同詞同等級）→ 跳過
                        _conflict    = []   # 同詞不同等級 → 警告

                        for _r in _rows:
                            _kw  = _r["keyword"].strip()
                            try:
                                _lv = int(_r.get("hazard_level", 0))
                                _lv = max(0, min(5, _lv))
                            except (ValueError, TypeError):
                                _lv = 0
                            _src = _r.get("source", "manual").strip() or "manual"

                            _ex = db.find_keyword_in_event(event_id, _kw)
                            if _ex is None:
                                _to_import.append({"keyword": _kw, "hazard_level": _lv, "source": _src})
                            elif _ex["hazard_level"] == _lv:
                                _exact_dup.append(_kw)
                            else:
                                _conflict.append({
                                    "keyword": _kw,
                                    "existing_level": _ex["hazard_level"],
                                    "new_level": _lv,
                                    "source": _src,
                                })

                        # ── 顯示預覽 ─────────────────────────────────────
                        _c1, _c2, _c3 = st.columns(3)
                        _c1.metric("可匯入", f"{len(_to_import)} 筆", delta=None)
                        _c2.metric("完全重複（略過）", f"{len(_exact_dup)} 筆")
                        _c3.metric("等級衝突（警告）", f"{len(_conflict)} 筆",
                                   delta="需確認" if _conflict else None,
                                   delta_color="inverse" if _conflict else "off")

                        if _exact_dup:
                            st.info(f"ℹ️ 以下關鍵字已存在且等級相同，匯入時將自動跳過：\n"
                                    + "、".join(f"`{k}`" for k in _exact_dup))

                        if _conflict:
                            st.warning("⚠️ **等級衝突關鍵字**（已存在但危害等級不同）：")
                            _cf_rows = []
                            for _cf in _conflict:
                                _cf_rows.append({
                                    "關鍵字": _cf["keyword"],
                                    "現有等級": f"L{_cf['existing_level']}",
                                    "CSV 等級": f"L{_cf['new_level']}",
                                })
                            st.dataframe(_cf_rows, use_container_width=True, hide_index=True)
                            st.caption("衝突關鍵字預設**不匯入**，請先刪除現有關鍵字後再重新匯入，或手動修改。")

                        if _to_import:
                            st.write("**預覽可匯入關鍵字：**")
                            _prev_df = [{"關鍵字": r["keyword"],
                                         "危害等級": f"L{r['hazard_level']}",
                                         "來源": r["source"]} for r in _to_import]
                            st.dataframe(_prev_df, use_container_width=True, hide_index=True)

                            if st.button(f"✅ 確認匯入 {len(_to_import)} 筆", key=f"confirm_import_{event_id}",
                                         type="primary", use_container_width=True):
                                _imported = 0
                                for _item in _to_import:
                                    db.add_keyword(
                                        event_id=event_id,
                                        keyword=_item["keyword"],
                                        source=_item["source"],
                                        hazard_level=_item["hazard_level"],
                                    )
                                    _imported += 1
                                st.success(f"✅ 成功匯入 {_imported} 筆關鍵字！"
                                           + (f"　略過重複 {len(_exact_dup)} 筆" if _exact_dup else "")
                                           + (f"　衝突未匯入 {len(_conflict)} 筆" if _conflict else ""))
                                st.rerun()
                        elif not _conflict:
                            st.info("ℹ️ 所有關鍵字皆已存在，無需匯入")

            except Exception as _csv_err:
                st.error(f"❌ CSV 解析失敗：{_csv_err}")

    st.divider()

    # ── AI 關鍵字擷取 ─────────────────────────────────────────────────────
    st.subheader("🤖 AI 分析關鍵字（Gemini）")
    st.caption("合併此事件所有辨識文字，以 Gemini 自動擷取關鍵術語與危害等級。")

    ai_model_col, ai_btn_col = st.columns([2, 1])
    with ai_model_col:
        ai_model = st.selectbox(
            "Gemini 模型",
            options=[
                "gemini-2.5-flash",         # ⭐ 推薦
                "gemini-2.5-pro",
                "gemini-2.5-flash-lite",
                "gemini-3.1-pro-preview",   # 🆕 最新旗艦
            ],
            index=0, key=f"ai_model_{event_id}",
        )
    with ai_btn_col:
        st.write("")
        st.write("")
        run_ai = st.button("🤖 開始分析", key=f"run_ai_{event_id}", use_container_width=True, type="primary")

    if run_ai:
        merged = "\n".join(
            t["transcript"] for t in transcriptions if t["status"] == "success" and t["transcript"]
        )
        if not merged.strip():
            st.warning("此事件無有效辨識文字，無法進行 AI 分析。")
        else:
            with st.spinner("Gemini 分析中，請稍候…"):
                try:
                    from utils.gemini_keyword_extractor import GeminiKeywordExtractor
                    extractor = GeminiKeywordExtractor(model_name=ai_model)
                    extracted = extractor.extract(merged, event_name=ev["event_name"])
                    if not extracted:
                        st.info("Gemini 未擷取到關鍵字。")
                    else:
                        saved = 0
                        for item in extracted:
                            db.add_keyword(event_id=event_id, keyword=item["keyword"], source="ai", hazard_level=item["hazard_level"])
                            saved += 1
                        st.success(f"✅ 已新增 {saved} 個 AI 關鍵字！")
                        st.rerun()
                except ValueError as ve:
                    st.error(f"❌ API Key 錯誤：{ve}")
                except Exception as ge:
                    st.error(f"❌ Gemini 分析失敗：{ge}")
                    with st.expander("詳細錯誤"):
                        st.code(traceback.format_exc())

    db.close()


# ============================================================================
# 頁面：全文搜尋
# ============================================================================
def render_search_page():
    if st.button("← 回到批次辨識", key="back_home_search"):
        st.session_state["page"] = "speech"
        st.rerun()

    st.title("🔍 全文搜尋")
    st.caption("跨所有事件搜尋辨識文字。FTS5 引擎（≥3 字元），短查詢自動切換 LIKE 模式。")
    st.divider()

    query = st.text_input(
        "搜尋關鍵字",
        placeholder="例：疏散、G05、月台門故障、OCC 收到",
        key="search_query",
    )
    col_limit, _ = st.columns([2, 3])
    with col_limit:
        limit = st.selectbox("最多顯示筆數", [20, 50, 100, 200], index=0, key="search_limit")

    if not query.strip():
        st.info("請輸入搜尋關鍵字（至少 1 個字）")
        return

    try:
        from utils.db_manager import DBManager
        db = DBManager(DB_PATH)
    except Exception as e:
        st.error(f"無法連線資料庫：{e}")
        return

    q       = query.strip()
    use_fts = len(q) >= 3

    with st.spinner("搜尋中…"):
        try:
            if use_fts:
                rows       = db.search_transcriptions(q, limit=limit)
                mode_label = "FTS5"
            else:
                rows       = db.search_transcriptions_like(q, limit=limit)
                mode_label = "LIKE"
        except Exception as e:
            st.error(f"搜尋失敗：{e}")
            db.close()
            return

    db.close()

    if not rows:
        st.warning(f"未找到包含「{q}」的辨識結果。")
        return

    st.success(f"找到 **{len(rows)}** 筆結果（{mode_label} 模式）")
    st.divider()

    for row in rows:
        transcript = row["transcript"] or ""
        event_name = row["event_name"]
        filename   = row["original_filename"]
        created_at = (row["created_at"] or "")[:16]
        highlighted = transcript.replace(q, f"**:orange[{q}]**")
        with st.expander(f"📁 {event_name}　｜　{filename}　（{created_at}）"):
            st.markdown(highlighted)


# ============================================================================
# 頁面：統計報表
# ============================================================================
def _make_csv_bytes(rows, fieldnames: list) -> bytes:
    buf    = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r[k] for k in fieldnames})
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def render_stats_page():
    if st.button("← 回到批次辨識", key="back_home_stats"):
        st.session_state["page"] = "speech"
        st.rerun()

    st.title("📊 統計報表")
    st.divider()

    try:
        from utils.db_manager import DBManager
        db = DBManager(DB_PATH)
    except Exception as e:
        st.error(f"無法連線資料庫：{e}")
        return

    # ── 摘要 ────────────────────────────────────────────────────────────────
    summary = db.get_stats_summary()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("總事件數",     summary.get("total_events",   0))
    c2.metric("總音檔數",     summary.get("total_audios",   0))
    c3.metric("辨識成功筆數", summary.get("total_trans",    0))
    c4.metric("關鍵字總數",   summary.get("total_keywords", 0))
    st.divider()

    # ── 事件趨勢 ──────────────────────────────────────────────────────────
    st.subheader("📅 事件趨勢（按日期）")
    date_rows = db.get_stats_by_date()
    if date_rows:
        df_date = pd.DataFrame(
            [(r["event_date"], r["count"]) for r in date_rows], columns=["日期", "事件數"],
        ).set_index("日期")
        st.bar_chart(df_date)
    else:
        st.info("尚無日期資料（事件缺少 event_date）")

    st.divider()

    # ── 模型使用分布 ──────────────────────────────────────────────────────
    st.subheader("🤖 模型使用分布")
    model_rows = db.get_stats_by_model()
    if model_rows:
        df_model = pd.DataFrame(
            [(f"{r['model_type']} / {r['sub_model']}", r["count"]) for r in model_rows],
            columns=["模型", "事件數"],
        ).set_index("模型")
        st.bar_chart(df_model)
    else:
        st.info("尚無模型統計資料")

    st.divider()

    # ── 危害等級分布 ──────────────────────────────────────────────────────
    st.subheader("⚠️ 危害等級分布")
    hazard_rows = db.get_stats_by_hazard()
    if hazard_rows:
        label_map = {
            0: "L0 正常", 1: "L1 輕微異常", 2: "L2 需注意",
            3: "L3 中等",  4: "L4 嚴重",    5: "L5 緊急",
        }
        df_hazard = pd.DataFrame(
            [(label_map.get(r["hazard_level"], f"L{r['hazard_level']}"), r["count"]) for r in hazard_rows],
            columns=["危害等級", "事件數"],
        ).set_index("危害等級")
        st.bar_chart(df_hazard)
    else:
        st.info("尚無危害等級資料")

    st.divider()

    # ── 資料匯出 ──────────────────────────────────────────────────────────
    st.subheader("⬇️ 資料匯出")
    st.caption("匯出所有事件、音檔與辨識結果為 CSV（UTF-8 BOM，Excel 相容）")

    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        if st.button("產生事件完整匯出 CSV", use_container_width=True):
            export_rows = db.export_all_events_csv()
            if export_rows:
                fieldnames = [
                    "event_id", "event_name", "event_date", "model_type", "sub_model",
                    "hazard_level", "notes", "event_created_at",
                    "original_filename", "recorded_at", "file_size",
                    "transcript", "transcription_status",
                    "use_vad", "use_denoise",
                ]
                csv_bytes = _make_csv_bytes(export_rows, fieldnames)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    "⬇️ 下載 CSV", data=csv_bytes,
                    file_name=f"aiSpeechMulti_export_{ts}.csv", mime="text/csv",
                )
            else:
                st.info("資料庫尚無資料可匯出")

    with col_exp2:
        events_for_export = db.list_events(limit=500)
        if events_for_export:
            fieldnames_ev = ["id", "event_name", "event_date", "model_type", "sub_model", "hazard_level", "notes", "created_at"]
            csv_events = _make_csv_bytes(events_for_export, fieldnames_ev)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                "⬇️ 下載事件清單 CSV", data=csv_events,
                file_name=f"aiSpeechMulti_events_{ts}.csv", mime="text/csv",
                use_container_width=True,
            )

    db.close()


# ============================================================================
# 詞彙表工具函式
# ============================================================================
def _vocab_api_base() -> str:
    return st.session_state.get("api_base", API_BASE).rstrip("/")


def _load_vocabulary_csv() -> list:
    """讀詞彙：API 優先（P3-Vocab），失敗則 fallback 直接讀 CSV。"""
    try:
        r = requests.get(f"{_vocab_api_base()}/api/vocabulary", timeout=2)
        if r.ok:
            data = r.json()
            if data.get("ok"):
                return data.get("rows", [])
    except Exception:
        pass

    if not VOCABULARY_CSV.exists():
        return []
    rows = []
    with VOCABULARY_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("term", "").startswith("#"):
                continue
            rows.append(row)
    return rows


def _save_vocabulary_csv(rows: list) -> None:
    """寫詞彙：直接寫 CSV（API 採增量 PUT/POST/DELETE，整批存仍走 CSV 最簡單）。

    註：未來若 Lab 改成單筆 PUT/POST/DELETE 即時寫，可移除此函式。
    """
    with VOCABULARY_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_VOCAB_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ============================================================================
# 頁面：語音準確率辨識計算
# ============================================================================
def render_evaluation_page():
    """語音辨識準確率評測頁面（CER / 差異分析）。"""
    import json as _json

    if st.button("← 回到批次辨識", key="back_home_eval"):
        for k in ("eval_done", "eval_results", "eval_text_done", "eval_text_results"):
            st.session_state[k] = False if "done" in k else None
        st.session_state["page"] = "speech"
        st.rerun()

    st.title("📊 語音準確率辨識計算")
    st.caption("對照標準文稿（ground truth），計算 CER（字元錯誤率）與辨識準確率，並輸出差異高亮分析。")
    st.divider()

    # ── 頂層 Tab：選擇評測模式 ────────────────────────────────────────────
    tab_audio, tab_text = st.tabs([
        "🎙️ 語音辨識 + 準確率計算",
        "📄 純文稿比對",
    ])

    with tab_audio:
        _render_audio_eval_mode(_json)

    with tab_text:
        _render_text_compare_mode(_json)


def _render_audio_eval_mode(_json):
    """Tab A：語音辨識 → 準確率計算（原有流程）。"""

    # ── 若評測已完成，直接顯示結果 ─────────────────────────────────────────
    if st.session_state.get("eval_done") and st.session_state.get("eval_results"):
        _render_eval_results(
            results     = st.session_state["eval_results"],
            case_name   = st.session_state.get("eval_case_name", ""),
            output_dir  = Path(st.session_state.get("eval_output_dir", ".")),
            timestamp   = st.session_state.get("eval_timestamp", ""),
            meta        = st.session_state.get("eval_meta", {}),
            key_suffix  = "_audio",
        )
        st.divider()
        if st.button("🔄 重新評測", key="eval_reset"):
            st.session_state["eval_done"]    = False
            st.session_state["eval_results"] = None
            st.session_state["eval_meta"]    = {}
            st.rerun()
        return

    # ── Step 1：選擇案例 ────────────────────────────────────────────────────
    st.subheader("Step 1　選擇評測案例")

    # 掃描 experiments/ 下所有子目錄
    all_cases = sorted(
        [d.name for d in EXPERIMENTS_DIR.iterdir()
         if d.is_dir() and d.name != "temp_upload"],
        key=str.lower
    ) if EXPERIMENTS_DIR.exists() else []

    # ── 「使用現有案例」下拉選單（唯一的 case_name 來源）──────────────────
    if not all_cases:
        st.warning("experiments/ 目錄下找不到任何案例。請先用下方「新建案例」建立。")
        case_name = ""
    else:
        case_name = st.selectbox(
            "選擇案例（experiments/ 子目錄）",
            options=all_cases,
            key="eval_case_select",
        )

    # ── 新建案例（僅負責建立目錄，不改變 case_name 選擇）────────────────────
    with st.expander("➕ 新建案例", expanded=False):
        new_case_input = st.text_input(
            "新案例名稱（將自動建立子目錄）",
            placeholder="例如：Test_03_Airport",
            key="eval_new_case_name",
        )
        if st.button("建立案例", key="eval_create_case"):
            name = new_case_input.strip()
            if name:
                new_dir = EXPERIMENTS_DIR / name
                for sub in ["source_audio", "ground_truth", "asr_output", "evaluation"]:
                    (new_dir / sub).mkdir(parents=True, exist_ok=True)
                st.success(f"✅ 已建立：experiments/{name}/　請在上方下拉選單選擇此案例。")
                st.rerun()
            else:
                st.error("請輸入案例名稱。")

    if not case_name:
        return

    case_dir = EXPERIMENTS_DIR / case_name
    st.session_state["eval_case_name"] = case_name

    # 顯示目錄結構狀態
    src_dir = case_dir / "source_audio"
    gt_dir  = case_dir / "ground_truth"
    asr_dir = case_dir / "asr_output"
    eval_dir = case_dir / "evaluation"

    _GT_EXTS  = {".txt", ".csv"}
    _ASR_EXTS = {".txt", ".csv"}
    _AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}

    # 重新計算（確保每次 rerun 都是最新值）
    src_dir.mkdir(parents=True, exist_ok=True)
    gt_dir.mkdir(parents=True, exist_ok=True)
    asr_dir.mkdir(parents=True, exist_ok=True)

    n_src = len([f for f in src_dir.iterdir() if f.suffix.lower() in _AUDIO_EXTS])
    n_gt  = len([f for f in gt_dir.iterdir()  if f.suffix.lower() in _GT_EXTS])
    n_asr = len([f for f in asr_dir.iterdir() if f.suffix.lower() in _ASR_EXTS])

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("🎵 語音檔案", f"{n_src} 個",
                  help=f"完整路徑：\n{src_dir}")
    with col_b:
        icon = "✅" if n_gt > 0 else "⚠️"
        st.metric(f"{icon} 標準文稿", f"{n_gt} 份",
                  help=f"完整路徑：\n{gt_dir}")
    with col_c:
        st.metric("📝 辨識結果", f"{n_asr} 份",
                  help=f"完整路徑：\n{asr_dir}")

    # 顯示各目錄的完整路徑，方便使用者確認放錯位置
    with st.expander("📂 查看各目錄完整路徑", expanded=(n_src == 0)):
        st.code(f"語音檔案  ➜  {src_dir}", language=None)
        st.code(f"標準文稿  ➜  {gt_dir}",  language=None)
        st.code(f"辨識結果  ➜  {asr_dir}", language=None)
        st.caption("請確認語音檔案已放置在上方「語音檔案」路徑內，而非其他同名資料夾。")

    st.divider()

    # ── Step 1.5：上傳語音檔案（source_audio）────────────────────────────────
    st.subheader("Step 1.5　載入語音檔案")

    with st.expander(
        f"📤 上傳語音檔案到 source_audio/（目前 {n_src} 個）",
        expanded=(n_src == 0),
    ):
        uploaded_audios = st.file_uploader(
            f"選擇語音檔案（支援 .wav .mp3 .m4a .flac .ogg .aac，最多 {MAX_UPLOAD_FILES} 個）",
            type=["wav", "mp3", "m4a", "flac", "ogg", "aac"],
            accept_multiple_files=True,
            key="eval_audio_upload",
        )
        if uploaded_audios and st.button("儲存語音檔案", key="eval_save_audio"):
            for uf in uploaded_audios:
                (src_dir / uf.name).write_bytes(uf.getbuffer())
            st.success(f"✅ 已儲存 {len(uploaded_audios)} 個語音檔案至 source_audio/")
            st.rerun()

    # 已有語音檔清單 + 刪除
    if n_src > 0:
        src_files = sorted(f for f in src_dir.iterdir() if f.suffix.lower() in _AUDIO_EXTS)
        with st.expander(f"已載入 {n_src} 個語音檔案（點擊展開 / 刪除）", expanded=False):
            for af in src_files:
                col_aname, col_abtn = st.columns([8, 1])
                with col_aname:
                    st.caption(f"  • 🎵　{af.name}")
                with col_abtn:
                    if st.button("🗑️", key=f"del_src_{af.stem}_{af.suffix}",
                                 help=f"刪除 {af.name}"):
                        af.unlink()
                        st.toast(f"已刪除：{af.name}", icon="🗑️")
                        st.rerun()

    st.divider()

    # ── Step 2：上傳 / 確認 Ground Truth ────────────────────────────────────
    st.subheader("Step 2　標準文稿（Ground Truth）")

    st.caption(
        "支援 **.csv**（與辨識結果下載格式相同，自動讀取「辨識文字」欄）"
        " 或 **.txt**（純文字），"
        "檔名須與對應音檔主檔名相同。"
    )

    with st.expander("📤 上傳標準文稿（.csv 或 .txt，一個音檔對應一個文稿）", expanded=(n_gt == 0)):
        uploaded_gts = st.file_uploader(
            "選擇標準文稿（.csv / .txt，檔名須與音檔主檔名相同）",
            type=["csv", "txt"],
            accept_multiple_files=True,
            key="eval_gt_upload",
        )
        if uploaded_gts and st.button("儲存標準文稿", key="eval_save_gt"):
            gt_dir.mkdir(parents=True, exist_ok=True)
            for uf in uploaded_gts:
                dest = gt_dir / uf.name
                dest.write_bytes(uf.getbuffer())
            st.success(f"✅ 已儲存 {len(uploaded_gts)} 份標準文稿至 ground_truth/")
            st.rerun()

    if n_gt > 0:
        gt_files = sorted(
            f for f in gt_dir.iterdir() if f.suffix.lower() in _GT_EXTS
        )
        st.success(f"找到 {n_gt} 份標準文稿：")

        # 逐列顯示檔名 + 刪除按鈕
        for gf in gt_files:
            fmt_tag = "📊 CSV" if gf.suffix.lower() == ".csv" else "📄 TXT"
            col_name, col_btn = st.columns([8, 1])
            with col_name:
                st.caption(f"  • {fmt_tag}　{gf.name}")
            with col_btn:
                if st.button("🗑️", key=f"del_gt_{gf.stem}_{gf.suffix}",
                             help=f"刪除 {gf.name}"):
                    gf.unlink()
                    st.toast(f"已刪除：{gf.name}", icon="🗑️")
                    st.rerun()

        # 比對音檔 ↔ 標準文稿 對應關係
        if n_src > 0:
            src_stems    = {f.stem for f in src_dir.iterdir()
                            if f.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}}
            gt_stems     = {f.stem for f in gt_files}
            unpaired_src = src_stems - gt_stems
            if unpaired_src:
                st.warning(f"⚠️ 以下音檔尚無對應標準文稿：{', '.join(sorted(unpaired_src))}")
    else:
        st.warning("⚠️ 請先上傳標準文稿（.csv 或 .txt）才能執行評測。")

    st.divider()

    # ── Step 3：選擇辨識模型 ────────────────────────────────────────────────
    st.subheader("Step 3　選擇辨識模型")

    # 若已有 asr_output，提供「跳過辨識」選項
    skip_asr = False
    if n_asr > 0:
        skip_asr = st.checkbox(
            f"使用已有辨識結果（asr_output/ 內有 {n_asr} 份）跳過重新辨識，直接計算準確率",
            value=True,
            key="eval_skip_asr",
        )

    # 模型選擇（skip_asr 時仍顯示但 disabled，保留使用者設定）
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        eval_model_type = st.radio(
            "辨識模型",
            options=list(MODEL_OPTIONS.keys()),
            key="eval_model_radio",
            horizontal=True,
            disabled=skip_asr,
        )
        # eval_model_type 此時為 display label（如 "Google Cloud STT"）
        eval_model_value = MODEL_OPTIONS[eval_model_type]

    with col_m2:
        sub_options = SUB_MODEL_OPTIONS.get(eval_model_value, [])
        if sub_options:
            eval_sub_model = st.radio(
                "子模型",
                options=[v for _, v in sub_options],
                format_func=lambda v: next((k for k, vv in sub_options if vv == v), v),
                key="eval_sub_radio",
                disabled=skip_asr,
            )
        else:
            eval_sub_model = eval_model_value

    if skip_asr:
        st.caption("🔒 模型選擇已鎖定（使用現有辨識結果）")

    # 存入 session_state 備用
    st.session_state["eval_model_type"] = eval_model_value
    st.session_state["eval_sub_model"]  = eval_sub_model

    st.divider()

    # ── Step 4：執行 ────────────────────────────────────────────────────────
    st.subheader("Step 4　執行評測")

    # 前置條件檢查（只顯示警告，不中斷渲染）
    if n_gt == 0:
        st.warning("⚠️ ground_truth/ 中尚無標準文稿，請先完成 Step 2 上傳。")
        return

    if not skip_asr and n_src == 0:
        st.warning("⚠️ source_audio/ 中找不到語音檔案。請先將音檔放入該目錄，或勾選上方「跳過辨識」。")
        return

    # 按鈕
    if skip_asr:
        btn_label = "📊 計算準確率（使用現有辨識結果）"
    else:
        btn_label = f"🚀 辨識 {n_src} 個語音檔並計算準確率"

    st.info(
        "📌 **評測流程**：\n"
        + ("① 略過辨識　" if skip_asr else f"① 辨識 source_audio/ 下 {n_src} 個語音檔　")
        + "② 逐檔與標準文稿比對　③ 計算 CER / 準確率　④ 輸出差異分析"
    )

    if st.button(btn_label, type="primary", key="eval_run", use_container_width=True):
        timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
        eval_dir.mkdir(parents=True, exist_ok=True)
        run_asr_dir = asr_dir

        # ── 辨識 ──────────────────────────────────────────────────────────
        if not skip_asr:
            audio_exts  = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
            audio_files = sorted([
                f for f in src_dir.iterdir() if f.suffix.lower() in audio_exts
            ])
            run_asr_dir.mkdir(parents=True, exist_ok=True)
            prog = st.progress(0, text="初始化辨識模型...")

            try:
                from scripts.batch_inference import BatchInference, setup_google_credentials
                setup_google_credentials()

                engine = BatchInference(
                    input_dir    = str(src_dir),
                    output_dir   = str(run_asr_dir),
                    model_type   = eval_model_value,
                    stt_model    = eval_sub_model if eval_model_value == "google_stt" else "chirp_3",
                    gemini_model = eval_sub_model if eval_model_value in ("gemini", "hybrid") else "gemini-2.5-flash",
                    language_code= "cmn-Hant-TW",
                ) if eval_model_value != "whisper" else None

                for idx, af in enumerate(audio_files):
                    prog.progress(
                        idx / len(audio_files),
                        text=f"辨識中：{af.name}  ({idx + 1}/{len(audio_files)})"
                    )
                    try:
                        if eval_model_value == "whisper":
                            from scripts.models.model_whisper import transcribe_with_whisper
                            txt = transcribe_with_whisper(str(af), model_size=eval_sub_model)
                        else:
                            result = engine.transcribe_file(af)
                            txt    = result.get("transcript", "")
                        (run_asr_dir / f"{af.stem}.txt").write_text(txt, encoding="utf-8")
                    except Exception as e:
                        st.warning(f"⚠️ {af.name} 辨識失敗：{e}")

                prog.progress(1.0, text="辨識完成！")

            except Exception as e:
                st.error(f"❌ 辨識失敗：{e}")
                return

        # ── 計算 CER ──────────────────────────────────────────────────────
        with st.spinner("計算 CER 與差異分析中..."):
            try:
                from scripts.cer_engine import evaluate_case, generate_text_report
                results = evaluate_case(gt_dir, run_asr_dir)
            except Exception as e:
                st.error(f"CER 計算失敗：{e}")
                return

        # ── 建立 meta（評測資訊）──────────────────────────────────────────
        _model_label = {v: k for k, v in MODEL_OPTIONS.items()}.get(eval_model_value, eval_model_value)
        meta = {
            "mode":        "audio_asr",
            "model_label": _model_label,
            "sub_model":   eval_sub_model if not skip_asr else "（使用已有辨識結果）",
            "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # ── 儲存報告 ───────────────────────────────────────────────────────
        summary_file = eval_dir / f"summary_{timestamp}.json"
        report_file  = eval_dir / f"report_{timestamp}.txt"
        summary_file.write_text(
            _json.dumps({**results["overall"], "meta": meta}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report_text = generate_text_report(case_name, results, meta=meta)
        report_file.write_text(report_text, encoding="utf-8")

        # ── 快取到 session_state ───────────────────────────────────────────
        st.session_state["eval_done"]       = True
        st.session_state["eval_results"]    = results
        st.session_state["eval_output_dir"] = str(eval_dir)
        st.session_state["eval_timestamp"]  = timestamp
        st.session_state["eval_meta"]       = meta
        st.rerun()


def _render_text_compare_mode(_json):
    """Tab B：純文稿比對（直接上傳 ASR 結果 + 標準文稿進行 CER 比對）。"""

    # ── 若已完成，顯示結果 ────────────────────────────────────────────────
    if st.session_state.get("eval_text_done") and st.session_state.get("eval_text_results"):
        meta = st.session_state.get("eval_text_meta", {})
        ts   = meta.get("timestamp", datetime.now().strftime("%Y%m%d_%H%M%S")).replace(" ", "_").replace(":", "")
        _render_eval_results(
            results      = st.session_state["eval_text_results"],
            case_name    = "純文稿比對",
            output_dir   = Path("."),
            timestamp    = ts,
            meta         = meta,
            save_to_disk = False,
            key_suffix   = "_text",
        )
        st.divider()
        if st.button("🔄 重新比對", key="eval_text_reset"):
            st.session_state["eval_text_done"]    = False
            st.session_state["eval_text_results"] = None
            st.session_state["eval_text_meta"]    = {}
            st.rerun()
        return

    st.write("")
    st.info(
        "**適用情境**：已有辨識結果文字檔，想直接與標準文稿比對，"
        "無需重新辨識語音。支援 **.csv** 與 **.txt** 格式。"
    )
    st.divider()

    # ── Step A：標準文稿 ──────────────────────────────────────────────────
    st.subheader("Step A　上傳標準文稿（Ground Truth）")
    st.caption("支援 .csv（自動讀取「辨識文字」欄）或 .txt 純文字。")
    gt_file = st.file_uploader(
        "選擇標準文稿（單一檔案）",
        type=["csv", "txt"],
        accept_multiple_files=False,
        key="tc_gt_upload",
    )

    # ── Step B：辨識結果文稿 ──────────────────────────────────────────────
    st.subheader("Step B　上傳辨識結果文稿")
    st.caption("支援 .csv（從「語音辨識模式」下載的格式）或 .txt。")
    asr_file = st.file_uploader(
        "選擇辨識結果文稿（單一檔案）",
        type=["csv", "txt"],
        accept_multiple_files=False,
        key="tc_asr_upload",
    )

    # ── Step C：執行比對 ──────────────────────────────────────────────────
    st.subheader("Step C　執行準確率計算")

    if gt_file and asr_file:
        st.success(f"✅ 標準文稿：{gt_file.name}　│　辨識結果：{asr_file.name}")
        if st.button("📊 計算準確率", type="primary", key="tc_run", use_container_width=True):
            with st.spinner("讀取文稿並計算 CER..."):
                try:
                    from scripts.cer_engine import read_transcript_file, compare_two_texts
                    import tempfile, os

                    # 暫存到磁碟供 read_transcript_file 讀取
                    def _save_tmp(uf):
                        suffix = Path(uf.name).suffix
                        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                        tmp.write(uf.getbuffer())
                        tmp.flush()
                        return tmp.name

                    gt_tmp  = _save_tmp(gt_file)
                    asr_tmp = _save_tmp(asr_file)
                    gt_text  = read_transcript_file(Path(gt_tmp))
                    asr_text = read_transcript_file(Path(asr_tmp))
                    os.unlink(gt_tmp)
                    os.unlink(asr_tmp)

                    results = compare_two_texts(
                        gt_text,
                        asr_text,
                        gt_name  = Path(gt_file.name).stem,
                        asr_name = Path(asr_file.name).stem,
                    )

                    now = datetime.now()
                    meta = {
                        "mode":         "text_compare",
                        "gt_filename":  gt_file.name,
                        "asr_filename": asr_file.name,
                        "timestamp":    now.strftime("%Y-%m-%d %H:%M:%S"),
                    }

                    st.session_state["eval_text_done"]    = True
                    st.session_state["eval_text_results"] = results
                    st.session_state["eval_text_meta"]    = meta
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ 比對失敗：{e}")
    else:
        st.info("請先上傳標準文稿（Step A）與辨識結果文稿（Step B）。")


def _render_eval_results(
    results: dict,
    case_name: str,
    output_dir: Path,
    timestamp: str,
    meta: dict = None,
    save_to_disk: bool = True,
    key_suffix: str = "",
):
    """顯示評測結果：評測資訊 + 整體統計 + 逐檔差異分析 + 下載按鈕。"""
    import json as _json
    meta = meta or {}
    ov   = results["overall"]

    # ── 評測資訊摘要 ──────────────────────────────────────────────────────
    mode_label = {
        "audio_asr":    "🎙️ 語音辨識 + 準確率計算",
        "text_compare": "📄 純文稿比對",
    }.get(meta.get("mode", ""), "—")

    with st.expander("ℹ️ 評測資訊", expanded=True):
        info_cols = st.columns(3)
        info_cols[0].markdown(f"**評測模式**  \n{mode_label}")
        if meta.get("mode") == "audio_asr":
            info_cols[1].markdown(f"**辨識模型**  \n{meta.get('model_label','—')}")
            info_cols[2].markdown(f"**子模型**  \n{meta.get('sub_model','—')}")
        elif meta.get("mode") == "text_compare":
            info_cols[1].markdown(f"**標準文稿**  \n{meta.get('gt_filename','—')}")
            info_cols[2].markdown(f"**辨識文稿**  \n{meta.get('asr_filename','—')}")
        st.caption(f"評測時間：{meta.get('timestamp','—')}")

    st.divider()

    # ── 整體統計卡 ────────────────────────────────────────────────────────
    st.subheader("📈 整體統計")

    # CER 區塊
    st.markdown("**CER 字元錯誤率**")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("整體準確率（加權）", f"{ov['micro_accuracy']:.1%}")
    m2.metric("平均準確率",         f"{ov['mean_accuracy']:.1%}")
    m3.metric("整體 CER",           f"{ov['micro_cer']:.1%}")
    m4.metric("總字元數",           f"{ov['total_chars']:,}")
    m5.metric("比對檔案",           f"{ov['n_files_matched']} / {ov['n_files_total']}")

    # CER 準確率進度條
    acc = ov["micro_accuracy"]
    bar_color = "#4CAF50" if acc >= 0.85 else ("#FF9800" if acc >= 0.65 else "#F44336")
    st.markdown(
        f'<div style="background:#222; border-radius:8px; height:18px; margin:4px 0 12px 0;">'
        f'<div style="background:{bar_color}; border-radius:8px; height:18px; '
        f'width:{acc*100:.1f}%; transition:width 0.4s;"></div></div>',
        unsafe_allow_html=True,
    )

    # WER 區塊（若有資料）
    if ov.get("total_words", 0) > 0:
        st.markdown("**WER 詞錯誤率**"
                    + (f"　　<span style='color:#777; font-size:0.85em;'>分詞器：{ov.get('wer_tokenizer','jieba')}</span>"
                       if ov.get("wer_tokenizer") else ""),
                    unsafe_allow_html=True)
        w1, w2, w3, w4, w5 = st.columns(5)
        w1.metric("整體 WER 準確率（加權）", f"{ov.get('micro_wer_accuracy', 0):.1%}")
        w2.metric("平均 WER 準確率",         f"{ov.get('mean_wer_accuracy', 0):.1%}")
        w3.metric("整體 WER",               f"{ov.get('micro_wer', 0):.1%}")
        w4.metric("總詞數",                 f"{ov.get('total_words', 0):,}")
        w5.metric("總詞錯誤數",             f"{ov.get('total_wer_errors', 0):,}")

        wer_acc = ov.get("micro_wer_accuracy", 0)
        wbar_color = "#4CAF50" if wer_acc >= 0.85 else ("#FF9800" if wer_acc >= 0.65 else "#F44336")
        st.markdown(
            f'<div style="background:#222; border-radius:8px; height:18px; margin:4px 0 12px 0;">'
            f'<div style="background:{wbar_color}; border-radius:8px; height:18px; '
            f'width:{wer_acc*100:.1f}%; transition:width 0.4s;"></div></div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ── 逐檔明細 ─────────────────────────────────────────────────────────
    st.subheader("🔍 逐檔差異分析")

    per_file = results["per_file"]
    # 彙整成 DataFrame 概覽表
    import pandas as pd
    df_rows = []
    for r in per_file:
        df_rows.append({
            "檔名":       r["stem"],
            "CER 準確率": f"{r['accuracy']:.1%}",
            "CER":        f"{r['cer']:.1%}",
            "WER 準確率": f"{r.get('wer_accuracy', 0):.1%}" if r["matched"] else "—",
            "WER":        f"{r.get('wer', 0):.1%}"          if r["matched"] else "—",
            "字元數":     r["n_ref"],
            "詞數":       r.get("n_words", 0),
            "替換":       r["sub"],
            "刪除":       r["del_"],
            "插入":       r["ins"],
            "狀態":       "✅" if r["matched"] else "❌ 缺少辨識結果",
        })
    st.dataframe(pd.DataFrame(df_rows), use_container_width=True, hide_index=True)

    st.write("")

    # 逐檔展開差異
    for r in per_file:
        acc_label = f"{r['accuracy']:.1%}" if r["matched"] else "❌"
        with st.expander(
            f"{'✅' if r['matched'] else '❌'}  {r['stem']}　│　"
            f"CER準確率 {acc_label}　│　CER {r['cer']:.1%}"
            + (f"　│　WER {r.get('wer', 0):.1%}" if r["matched"] else ""),
            expanded=False,
        ):
            if r["matched"]:
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("CER 準確率", f"{r['accuracy']:.1%}")
                c2.metric("CER",        f"{r['cer']:.1%}")
                c3.metric("WER 準確率", f"{r.get('wer_accuracy', 0):.1%}")
                c4.metric("WER",        f"{r.get('wer', 0):.1%}")
                c5.metric("詞數",       r.get("n_words", 0))
                st.markdown(r["diff_html"], unsafe_allow_html=True)
            else:
                st.error(r["diff_html"])

    st.divider()

    # ── 下載區 ───────────────────────────────────────────────────────────
    st.subheader("⬇️ 下載報告")
    col_d1, col_d2 = st.columns(2)

    from scripts.cer_engine import generate_text_report
    report_text = generate_text_report(case_name, results, meta=meta)

    _ts_label = timestamp.replace("-", "").replace(" ", "_").replace(":", "")[:15]
    _fname    = case_name if case_name != "純文稿比對" else (
        Path(meta.get("asr_filename", "compare")).stem
    )

    with col_d1:
        st.download_button(
            "📄 下載文字報告 (.txt)",
            data=report_text.encode("utf-8"),
            file_name=f"{_fname}_CER報告_{_ts_label}.txt",
            mime="text/plain",
            key=f"dl_eval_report{key_suffix}",
        )
    with col_d2:
        summary_payload = {**results["overall"], "meta": meta}
        st.download_button(
            "📊 下載 JSON 統計",
            data=_json.dumps(summary_payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"{_fname}_CER統計_{_ts_label}.json",
            mime="application/json",
            key=f"dl_eval_json{key_suffix}",
        )
    if save_to_disk and str(output_dir) != ".":
        st.caption(f"評測結果已儲存至：`{output_dir}`")


# ============================================================================
# 頁面：詞彙表管理
# ============================================================================
def render_vocabulary_page():
    if st.button("← 回到批次辨識", key="back_home_vocab"):
        st.session_state["page"] = "speech"
        st.rerun()

    st.title("📚 詞彙表管理")
    st.caption(f"資料來源：`{VOCABULARY_CSV.relative_to(PROJECT_ROOT)}`")
    st.divider()

    rows = _load_vocabulary_csv()

    # ── 篩選 ──────────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns([3, 2, 2])
    with col_f1:
        filter_term = st.text_input("搜尋術語 / 說明", placeholder="OCC、疏散…", key="vocab_filter_term")
    with col_f2:
        filter_cat = st.selectbox("類別", ["全部"] + _VOCAB_CATEGORIES, key="vocab_filter_cat")
    with col_f3:
        filter_alert = st.selectbox("告警等級", ["全部", "0", "1", "2", "3", "4", "5"], key="vocab_filter_alert")

    filtered_indices = list(range(len(rows)))
    if filter_term.strip():
        q_lower = filter_term.strip().lower()
        filtered_indices = [
            i for i in filtered_indices
            if q_lower in rows[i].get("term", "").lower()
            or q_lower in rows[i].get("description", "").lower()
            or q_lower in rows[i].get("common_error", "").lower()
        ]
    if filter_cat != "全部":
        filtered_indices = [i for i in filtered_indices if rows[i].get("category") == filter_cat]
    if filter_alert != "全部":
        filtered_indices = [i for i in filtered_indices if str(rows[i].get("alert_level", "")) == filter_alert]

    filtered = [rows[i] for i in filtered_indices]
    st.caption(f"共 **{len(filtered)}** 筆 / 總計 **{len(rows)}** 筆")

    # ── 表格（行內編輯） ──────────────────────────────────────────────────
    if filtered:
        df = pd.DataFrame(filtered, columns=_VOCAB_COLUMNS)
        df["boost_value"] = pd.to_numeric(df["boost_value"], errors="coerce").fillna(0).astype(int)
        df["alert_level"] = pd.to_numeric(df["alert_level"], errors="coerce").fillna(0).astype(int)

        edited_df = st.data_editor(
            df, use_container_width=True, hide_index=True, num_rows="fixed",
            column_config={
                "term":         st.column_config.TextColumn("術語", width="small"),
                "category":     st.column_config.SelectboxColumn("類別", options=_VOCAB_CATEGORIES, width="small"),
                "boost_value":  st.column_config.NumberColumn("加權值", min_value=0, max_value=20, step=1, width="small"),
                "alert_level":  st.column_config.NumberColumn("告警等級", min_value=0, max_value=5, step=1, width="small"),
                "pinyin":       st.column_config.TextColumn("拼音/讀法"),
                "common_error": st.column_config.TextColumn("常見錯誤"),
                "description":  st.column_config.TextColumn("說明"),
            },
            key="vocab_editor",
        )
        st.caption("💡 直接點擊儲存格即可編輯，完成後點下方「儲存變更」。")

        if st.button("💾 儲存變更", type="primary", key="vocab_save_btn"):
            for df_idx, row_idx in enumerate(filtered_indices):
                row = edited_df.iloc[df_idx]
                rows[row_idx] = {
                    "term":         str(row["term"]).strip(),
                    "category":     str(row["category"]),
                    "boost_value":  str(int(row["boost_value"])),
                    "alert_level":  str(int(row["alert_level"])),
                    "pinyin":       str(row["pinyin"]).strip(),
                    "common_error": str(row["common_error"]).strip(),
                    "description":  str(row["description"]).strip(),
                }
            _save_vocabulary_csv(rows)
            st.success("✅ 已儲存變更")
            st.rerun()
    else:
        st.info("沒有符合條件的詞條")

    st.divider()

    # ── 新增詞條 ──────────────────────────────────────────────────────────
    st.subheader("➕ 新增詞條")
    with st.form("add_vocab_form"):
        a1, a2, a3, a4 = st.columns([3, 2, 1, 1])
        new_term  = a1.text_input("術語 *", placeholder="EDRH")
        new_cat   = a2.selectbox("類別 *", _VOCAB_CATEGORIES)
        new_boost = a3.number_input("加權值", min_value=0, max_value=20, value=10)
        new_alert = a4.number_input("告警等級", min_value=0, max_value=5, value=0)
        b1, b2    = st.columns(2)
        new_pinyin = b1.text_input("拼音/讀法", placeholder="E-D-R-H")
        new_error  = b2.text_input("常見錯誤", placeholder="eDR|e d r")
        new_desc   = st.text_input("說明", placeholder="緊急門釋放把手")
        submitted  = st.form_submit_button("✅ 新增", type="primary")
        if submitted:
            if not new_term.strip():
                st.warning("術語為必填欄位")
            elif any(r.get("term", "").strip() == new_term.strip() for r in rows):
                st.warning(f"術語「{new_term.strip()}」已存在")
            else:
                rows.append({
                    "term": new_term.strip(), "category": new_cat,
                    "boost_value": str(new_boost), "alert_level": str(new_alert),
                    "pinyin": new_pinyin.strip(), "common_error": new_error.strip(),
                    "description": new_desc.strip(),
                })
                _save_vocabulary_csv(rows)
                st.success(f"✅ 已新增詞條：{new_term.strip()}")
                st.rerun()

    st.divider()

    # ── 刪除詞條 ──────────────────────────────────────────────────────────
    st.subheader("🗑️ 刪除詞條")
    if rows:
        del_options = [r["term"] for r in rows]
        del_term    = st.selectbox("選擇要刪除的術語", del_options, key="vocab_del_select")
        if st.button("🗑️ 刪除選定術語", type="secondary", key="vocab_del_btn"):
            rows_new = [r for r in rows if r.get("term") != del_term]
            _save_vocabulary_csv(rows_new)
            st.success(f"✅ 已刪除：{del_term}")
            st.rerun()
    else:
        st.info("詞彙表為空")

    st.divider()

    # ── 下載詞彙表 ────────────────────────────────────────────────────────
    if rows:
        buf    = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_VOCAB_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        csv_bytes = ("\ufeff" + buf.getvalue()).encode("utf-8")
        st.download_button(
            "⬇️ 下載詞彙表 CSV", data=csv_bytes,
            file_name=f"master_vocabulary_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )


# ============================================================================
# 頁面：離線近即時資料夾監控
# ============================================================================
def render_offline_monitor_page():
    """
    監控指定資料夾，對新出現的音檔自動以 SenseVoiceSmall 辨識。
    每次 Streamlit rerun 掃描一次資料夾，新檔案加入辨識佇列並即時顯示結果。
    """
    if st.button("← 回到批次辨識", key="offline_back"):
        st.session_state["page"] = "speech"
        st.rerun()

    st.title("🔒 離線近即時資料夾監控")
    st.caption("監控指定資料夾，自動對新音檔進行 SenseVoice 離線辨識（含情緒/事件偵測）")
    st.divider()

    # ── 側邊欄設定 ──────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ 監控設定")

        _om_is_running = st.session_state.get("om_running", False)
        # 若監控中，顯示目前的路徑（唯讀提示）；否則允許輸入
        if _om_is_running:
            st.text_input(
                "監控資料夾路徑",
                value=st.session_state.get("om_watch_folder", ""),
                key="om_watch_folder_input",
                disabled=True,
                help="監控進行中，停止後可修改路徑",
            )
        else:
            # value 優先使用上次存入的路徑，方便停止後再度啟動
            _default_path = st.session_state.get("om_watch_folder", "")
            st.text_input(
                "監控資料夾路徑",
                value=_default_path,
                placeholder="/Users/apple/incoming_audio",
                key="om_watch_folder_input",
                help="新音檔放入此資料夾後將自動辨識（支援 wav/mp3/m4a/flac/ogg）",
            )

        lang_opts = [("zh", "中文（推薦）"), ("en", "英文"), ("ja", "日文"),
                     ("yue", "粵語"), ("ko", "韓文"), ("auto", "自動偵測")]
        lang_labels = {k: v for k, v in lang_opts}
        language = st.selectbox(
            "辨識語言",
            options=[k for k, _ in lang_opts],
            format_func=lambda x: lang_labels[x],
            index=0,
            key="om_language_select",
            disabled=_om_is_running,
        )

        st.divider()

        _currently_running = st.session_state.get("om_running", False)

        if not _currently_running:
            if st.button("▶ 啟動監控", use_container_width=True, type="primary",
                         key="om_btn_start"):
                # 讀取 text_input 目前的值（Streamlit 自動存入 session_state[key]）
                _path = st.session_state.get("om_watch_folder_input", "").strip()
                if _path:
                    st.session_state["om_watch_folder"] = _path
                    st.session_state["om_language"]     = st.session_state.get(
                        "om_language_select", "zh")
                    st.session_state["om_running"]      = True
                    st.session_state["om_seen_files"]   = []
                    st.rerun()
                else:
                    st.warning("⚠️ 請先在上方輸入監控資料夾路徑！")
        else:
            if st.button("⏹ 停止監控", use_container_width=True, key="om_btn_stop"):
                st.session_state["om_running"] = False
                st.rerun()

        if st.button("🗑 清除結果", use_container_width=True, key="om_btn_clear"):
            st.session_state["om_results"]    = []
            st.session_state["om_seen_files"] = []
            st.rerun()

        st.divider()
        if st.button("← 回到批次辨識", key="offline_back2", use_container_width=True):
            st.session_state["om_running"] = False
            st.session_state["page"]       = "speech"
            st.rerun()

    # ── 狀態列 ──────────────────────────────────────────────────────────
    om_running     = st.session_state.get("om_running", False)
    om_folder      = st.session_state.get("om_watch_folder", "")
    om_language    = st.session_state.get("om_language", "zh")
    om_results     = st.session_state.get("om_results", [])
    om_seen_files  = st.session_state.get("om_seen_files", [])

    col_st, col_cnt = st.columns([4, 2])
    with col_st:
        if om_running and om_folder:
            st.success(f"🟢 監控中：`{om_folder}`")
        elif om_folder:
            st.warning(f"⏸ 已停止：`{om_folder}`")
        else:
            st.info("請在左側設定資料夾路徑，然後按「▶ 啟動監控」")
    with col_cnt:
        st.metric("已辨識", f"{len(om_results)} 個檔案")

    if not om_folder:
        return

    folder_path = Path(om_folder)
    if not folder_path.exists():
        st.error(f"❌ 資料夾不存在：{om_folder}")
        return

    # ── 掃描資料夾，找出新音檔 ───────────────────────────────────────────
    AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
    all_files  = sorted(
        f for f in folder_path.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTS
    )

    seen_set  = set(om_seen_files)
    new_files = [f for f in all_files if f.name not in seen_set]

    if om_running and new_files:
        # 載入模型（每頁面週期懶載入）
        try:
            from scripts.models.model_sensevoice import SenseVoiceModel

            vocab_csv = PROJECT_ROOT / "vocabulary" / "master_vocabulary.csv"
            sv_model  = SenseVoiceModel(
                language=om_language,
                vocabulary_csv=str(vocab_csv) if vocab_csv.exists() else None,
            )

            progress = st.progress(0, text="辨識中…")
            for idx, audio_file in enumerate(new_files):
                progress.progress(
                    (idx + 1) / len(new_files),
                    text=f"辨識：{audio_file.name}  ({idx + 1}/{len(new_files)})",
                )
                try:
                    result = sv_model.transcribe_file(str(audio_file))

                    om_results.append({
                        "filename":      audio_file.name,
                        "transcript":    result.get("transcript", ""),
                        "emotion":       result.get("emotion"),
                        "emotion_label": result.get("emotion_label"),
                        "events":        result.get("events", []),
                        "segments":      result.get("segments", []),
                        "timestamp":     datetime.now().strftime("%H:%M:%S"),
                        "status":        "success",
                    })
                except Exception as exc:
                    om_results.append({
                        "filename":  audio_file.name,
                        "transcript": "",
                        "status":    "error",
                        "error":     str(exc),
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                    })

                om_seen_files.append(audio_file.name)

            progress.empty()
            st.session_state["om_results"]    = om_results
            st.session_state["om_seen_files"] = om_seen_files
            st.rerun()

        except ImportError:
            st.error(
                "❌ funasr 未安裝，無法使用 SenseVoice 離線模式。\n\n"
                "請執行：`pip install funasr>=1.1.0 modelscope onnxruntime`"
            )

    elif om_running and not new_files:
        st.caption(
            f"⏳ 等待新音檔…（資料夾共 {len(all_files)} 個已辨識）　"
            f"每 {5} 秒自動掃描一次"
        )

    # ── 辨識結果顯示 ─────────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### 辨識結果（共 {len(om_results)} 筆）")

    if not om_results:
        st.markdown(
            '<div style="color:#445; padding:20px; text-align:center;">'
            '尚無辨識結果，等待新音檔…</div>',
            unsafe_allow_html=True,
        )
    else:
        # CSV 匯出
        csv_rows = []
        for r in om_results:
            csv_rows.append({
                "時間":     r.get("timestamp", ""),
                "檔名":     r["filename"],
                "辨識文字": r.get("transcript", ""),
                "情緒":     r.get("emotion_label", ""),
                "事件":     " ".join(r.get("events", [])),
                "狀態":     r.get("status", ""),
            })
        _buf = io.StringIO()
        _writer = csv.DictWriter(_buf, fieldnames=["時間", "檔名", "辨識文字", "情緒", "事件", "狀態"])
        _writer.writeheader()
        _writer.writerows(csv_rows)
        _csv_bytes = ("\ufeff" + _buf.getvalue()).encode("utf-8")
        st.download_button(
            "⬇️ 下載辨識結果 CSV",
            data=_csv_bytes,
            file_name=f"offline_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

        st.write("")

        for r in reversed(om_results):  # 最新在上
            fname   = r["filename"]
            ts      = r.get("timestamp", "")
            status  = r.get("status", "success")

            if status == "error":
                with st.expander(f"❌ `{fname}`　{ts}", expanded=False):
                    st.error(r.get("error", "未知錯誤"))
                continue

            text          = r.get("transcript", "") or "（無辨識結果）"
            emotion_label = r.get("emotion_label", "")
            events        = r.get("events", [])
            segments      = r.get("segments", [])

            notable_events = [e for e in events if "語音" not in e]
            badge_parts    = []
            if emotion_label:
                badge_parts.append(emotion_label)
            badge_parts.extend(notable_events)
            badge_str = "　".join(badge_parts)

            header = f"✅ `{fname}`　{ts}"
            if badge_str:
                header += f"　｜　{badge_str}"

            with st.expander(header, expanded=True):
                st.markdown(
                    f'<div style="font-size:0.9rem; color:#d0d8ef; '
                    f'background:#1a1d27; padding:10px; border-radius:6px;">'
                    f'{text}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if segments:
                    st.write("")
                    seg_lines = []
                    for seg in segments:
                        _ts_str = f"{seg['start']:.1f}s→{seg['end']:.1f}s"
                        _emo    = seg.get("emotion_label") or ""
                        _evts   = " ".join(
                            e for e in seg.get("events", []) if "語音" not in e
                        )
                        _line   = f"**[{_ts_str}]** {seg['text']}"
                        if _emo:
                            _line += f"　{_emo}"
                        if _evts:
                            _line += f"　{_evts}"
                        seg_lines.append(_line)
                    st.caption("逐段詳細")
                    for line in seg_lines:
                        st.markdown(f"&emsp;{line}")

    # ── 自動刷新（監控中時） ─────────────────────────────────────────────
    if om_running:
        time.sleep(5)
        st.rerun()


# ============================================================================
# 頁面：CER 趨勢看板
# ============================================================================
def render_cer_trend_page():
    if st.button("← 回首頁", key="cer_trend_back"):
        st.session_state["page"] = "speech"
        st.rerun()

    st.title("📈 CER 趨勢看板")
    st.caption("歷次 batch_eval 跑分結果聚合 — 看每引擎 final CER 隨時間變化")

    # 介面整併 P2：本頁將遷移到 Grafana
    st.warning(
        "🔄 **本頁已於 2026-05-04 規劃遷移到 Grafana**（介面整併 P2）。\n\n"
        "Grafana 看板已加入 3 個新 panel（時間序列 + 各引擎最佳 CER + 事件類型 × 引擎）。\n"
        "資料來自 `cer_history` / `cer_event_type_history` SQLite 表，"
        "請定期跑 `python -m aispeech data sync-cer` 同步。\n\n"
        f"Grafana：[localhost:3000](http://localhost:3000) → 「aiSpeechMulti 語音辨識監控」→ 最末尾 CER 趨勢區。"
    )
    st.caption("本頁保留 30 天作為過渡，期間若 Grafana 數字異常請以本頁為準。")

    history_csv = PROJECT_ROOT / "experiments" / "llm_correction_poc" / "cer_history.csv"
    if not history_csv.exists():
        st.warning(
            "尚無 cer_history.csv。請先跑 `python3 scripts/build_cer_index.py --rebuild` "
            "從現有 batch_eval JSON 報告建索引。"
        )
        return

    import pandas as pd
    try:
        df = pd.read_csv(history_csv)
    except Exception as e:
        st.error(f"讀取失敗：{e}")
        return

    if df.empty:
        st.info("索引為空")
        return

    # ── Regression detection（防靜默退步）────────────────────────────────
    # 對每個 (engine, post_process) 組合：取「最新一筆」與「歷史最佳」對照
    # 若最新 final CER 比歷史最佳高 > 5 個百分點，視為 regression 警告
    REGRESSION_THRESHOLD_PCT = 5.0  # 5 個百分點絕對差
    df_sorted = df.sort_values("timestamp")
    regressions: list[dict] = []
    for (eng, pp), grp in df_sorted.groupby(["engine_label", "post_process"]):
        if len(grp) < 2:
            continue
        latest = grp.iloc[-1]
        best = grp.loc[grp["avg_cer_final"].idxmin()]
        latest_pct = float(latest["avg_cer_final"]) * 100
        best_pct = float(best["avg_cer_final"]) * 100
        delta = latest_pct - best_pct
        if delta > REGRESSION_THRESHOLD_PCT:
            regressions.append({
                "engine": eng,
                "post_process": pp,
                "latest_pct": latest_pct,
                "best_pct": best_pct,
                "delta_pct": delta,
                "latest_ts": latest["timestamp"],
                "best_ts": best["timestamp"],
                "latest_source": latest["source_json"],
            })

    if regressions:
        st.error(
            f"🚨 偵測到 **{len(regressions)}** 個組合疑似退步（最新 final CER 高於歷史最佳 > "
            f"{REGRESSION_THRESHOLD_PCT}%）"
        )
        with st.expander("查看 regression 明細", expanded=True):
            for r in regressions:
                st.warning(
                    f"**{r['engine']} / {r['post_process']}**："
                    f"最新 {r['latest_pct']:.2f}% (`{r['latest_ts']}`) vs "
                    f"歷史最佳 {r['best_pct']:.2f}% (`{r['best_ts']}`) "
                    f"→ **+{r['delta_pct']:.2f}%**"
                )
                st.caption(f"     對應 JSON: `{r['latest_source']}`")
    else:
        st.success("✅ 無 regression：所有組合最新跑分皆在歷史最佳 + 5% 以內")

    # 統計摘要
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    col_s1.metric("總跑分數", len(df))
    col_s2.metric("引擎數", df["engine_label"].nunique())
    col_s3.metric("最新時間", df["timestamp_iso"].max()[:19] if not df["timestamp_iso"].isna().all() else "—")
    best_row = df.loc[df["avg_cer_final"].idxmin()]
    col_s4.metric(
        "歷史最佳",
        f"{float(best_row['avg_cer_final']) * 100:.2f}%",
        f"{best_row['engine_label']} / {best_row['post_process']}",
    )

    st.divider()

    # 篩選器
    col_f1, col_f2 = st.columns([2, 2])
    engines_all = sorted(df["engine_label"].unique().tolist())
    with col_f1:
        sel_engines = st.multiselect(
            "引擎",
            engines_all,
            default=engines_all,
            key="cer_trend_engines",
        )
    with col_f2:
        pp_all = sorted(df["post_process"].unique().tolist())
        sel_pp = st.multiselect(
            "後處理組合",
            pp_all,
            default=pp_all,
            key="cer_trend_pp",
        )

    df_f = df[df["engine_label"].isin(sel_engines) & df["post_process"].isin(sel_pp)].copy()
    if df_f.empty:
        st.info("篩選後無資料")
        return

    # 折線圖
    df_f["dt"] = pd.to_datetime(df_f["timestamp_iso"], errors="coerce")
    df_f = df_f.sort_values("dt")
    df_f["cer_final_pct"] = df_f["avg_cer_final"].astype(float) * 100
    df_f["cer_raw_pct"] = df_f["avg_cer_raw"].astype(float) * 100
    df_f["label"] = df_f["engine_label"] + " / " + df_f["post_process"]

    try:
        import plotly.express as px
        fig = px.line(
            df_f,
            x="dt",
            y="cer_final_pct",
            color="label",
            markers=True,
            title="各引擎 + 後處理組合 final CER 隨時間趨勢",
            labels={"dt": "時間", "cer_final_pct": "final CER (%)", "label": "engine / post_process"},
            color_discrete_sequence=LAB_CHANNEL_COLORS + [LAB_BRAND_PRIMARY],
        )
        fig.update_layout(**lab_plotly_layout(title="各引擎 + 後處理組合 final CER 隨時間趨勢", height=520))
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.warning("⚠️ plotly 未安裝，改用內建折線圖（pip install plotly 可看完整版）")
        st.line_chart(
            df_f.pivot_table(index="dt", columns="label", values="cer_final_pct"),
        )

    st.divider()

    # 各引擎最佳表
    st.subheader("📊 各引擎歷史最佳（final CER 最低）")
    best_by_engine = (
        df_f.sort_values("avg_cer_final")
        .groupby("engine_label")
        .first()
        .reset_index()[
            ["engine_label", "post_process", "avg_cer_raw", "avg_cer_final",
             "avg_improvement", "timestamp"]
        ]
    )
    best_by_engine["raw %"] = (best_by_engine["avg_cer_raw"].astype(float) * 100).round(2)
    best_by_engine["final %"] = (best_by_engine["avg_cer_final"].astype(float) * 100).round(2)
    best_by_engine["improve %"] = (best_by_engine["avg_improvement"].astype(float) * 100).round(2)
    st.dataframe(
        best_by_engine[["engine_label", "post_process", "raw %", "final %", "improve %", "timestamp"]],
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # 完整明細
    with st.expander(f"📋 完整明細（{len(df_f)} 筆）", expanded=False):
        df_show = df_f[[
            "timestamp", "engine_label", "post_process",
            "avg_cer_raw", "avg_cer_final", "avg_improvement",
            "sample_count", "source_json",
        ]].copy()
        df_show["raw %"] = (df_show["avg_cer_raw"].astype(float) * 100).round(2)
        df_show["final %"] = (df_show["avg_cer_final"].astype(float) * 100).round(2)
        df_show["improve %"] = (df_show["avg_improvement"].astype(float) * 100).round(2)
        st.dataframe(
            df_show[["timestamp", "engine_label", "post_process",
                     "raw %", "final %", "improve %", "sample_count", "source_json"]],
            use_container_width=True,
            hide_index=True,
        )

    # 事件類型分組（細粒度）
    et_csv = PROJECT_ROOT / "experiments" / "llm_correction_poc" / "cer_event_type_history.csv"
    if et_csv.exists():
        st.divider()
        st.subheader("🗂️ 依事件類型分組")
        st.caption("細粒度看 daily / track / door / emergency / control / train 各自走勢")
        try:
            df_et = pd.read_csv(et_csv)
            df_et = df_et[df_et["engine_label"].isin(sel_engines) & df_et["post_process"].isin(sel_pp)].copy()
            if not df_et.empty:
                df_et["dt"] = pd.to_datetime(df_et["timestamp_iso"], errors="coerce")
                df_et = df_et.sort_values("dt")
                df_et["cer_final_pct"] = df_et["avg_cer_final"].astype(float) * 100

                event_types_all = sorted(df_et["event_type"].unique().tolist())
                sel_et = st.multiselect(
                    "事件類型",
                    event_types_all,
                    default=event_types_all,
                    key="cer_trend_et",
                )
                df_et_f = df_et[df_et["event_type"].isin(sel_et)]

                # 每引擎一張小圖（依事件類型上色）
                try:
                    import plotly.express as px
                    eng_options = sorted(df_et_f["engine_label"].unique().tolist())
                    sel_eng_for_et = st.selectbox(
                        "看哪個引擎的事件類型走勢", eng_options, key="cer_trend_et_eng",
                    )
                    df_eng_et = df_et_f[df_et_f["engine_label"] == sel_eng_for_et].copy()
                    df_eng_et["label"] = df_eng_et["event_type"] + " / " + df_eng_et["post_process"]
                    fig_et = px.line(
                        df_eng_et, x="dt", y="cer_final_pct",
                        color="label", markers=True,
                        title=f"{sel_eng_for_et} 各事件類型 final CER 趨勢",
                        labels={"dt": "時間", "cer_final_pct": "final CER (%)", "label": "event_type / pp"},
                        color_discrete_sequence=LAB_CHANNEL_COLORS + [LAB_BRAND_PRIMARY],
                    )
                    fig_et.update_layout(**lab_plotly_layout(
                        title=f"{sel_eng_for_et} 各事件類型 final CER 趨勢", height=440))
                    st.plotly_chart(fig_et, use_container_width=True)
                except ImportError:
                    st.warning("⚠️ plotly 未安裝，事件類型走勢圖暫時無法顯示")

                # 各引擎 × 各事件類型最佳值表
                st.caption("**各引擎 × 各事件類型歷史最佳 final CER**")
                pivot = (
                    df_et_f.sort_values("avg_cer_final")
                    .groupby(["engine_label", "event_type"])
                    .first()
                    .reset_index()
                )
                pivot["final %"] = (pivot["avg_cer_final"].astype(float) * 100).round(2)
                pivot_table = pivot.pivot_table(
                    index="engine_label", columns="event_type", values="final %", aggfunc="min",
                )
                st.dataframe(pivot_table, use_container_width=True)
        except Exception as e:
            st.caption(f"⚠️ 事件類型分組載入失敗：{e}")

    st.caption(
        "💡 索引由 `scripts/build_cer_index.py` 維護；"
        "每次 `batch_eval.py` 跑完會自動 append 新的一筆。"
    )


# ============================================================================
# 頁面：修正歷程查詢（#15 飛輪可視化）
# ============================================================================
def render_correction_history_page():
    if st.button("← 回首頁", key="ch_back"):
        st.session_state["page"] = "speech"
        st.rerun()

    st.title("✏️ 修正歷程查詢")
    st.caption("看人工修正了哪些段、哪些字 pattern 最常出現 — #15 錯字回饋飛輪可視化")

    from utils.db_manager import DBManager
    from difflib import SequenceMatcher
    from collections import Counter
    db = DBManager(DB_PATH)
    rows = db.get_correction_pairs(limit=10000)
    if not rows:
        st.info("尚無人工修正紀錄。請到事件管理頁編輯辨識結果並儲存修正。")
        return

    # 4 個 metric cards
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    col_s1.metric("總修正筆數", len(rows))
    engines = [r["engine_hint"] or "_unknown" for r in rows]
    col_s2.metric("涵蓋引擎數", len(set(engines)))
    latest_ts = max((r["corrected_at"] or "" for r in rows), default="—")
    col_s3.metric("最新修正", latest_ts[:19] if latest_ts else "—")
    # 抽出所有替換對統計
    all_pairs: Counter = Counter()
    for r in rows:
        raw = (r["transcript"] or "")
        cor = (r["corrected_transcript"] or "")
        sm = SequenceMatcher(None, raw, cor, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "replace":
                continue
            w, right = raw[i1:i2], cor[j1:j2]
            if w and right and w != right and len(w) <= 10 and len(right) <= 10:
                all_pairs[(w, right)] += 1
    col_s4.metric("獨特錯字對", len(all_pairs))

    st.divider()

    # 篩選
    engine_options = ["（全部）"] + sorted(set(engines))
    sel_engine = st.selectbox("依引擎篩選", engine_options, key="ch_engine_sel")

    rows_f = rows if sel_engine == "（全部）" else [r for r in rows if (r["engine_hint"] or "_unknown") == sel_engine]
    st.caption(f"目前顯示 **{len(rows_f)}** 筆修正紀錄")

    # 高頻錯字對 Top 30
    if sel_engine != "（全部）":
        pairs_f: Counter = Counter()
        for r in rows_f:
            raw = (r["transcript"] or "")
            cor = (r["corrected_transcript"] or "")
            sm = SequenceMatcher(None, raw, cor, autojunk=False)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag != "replace":
                    continue
                w, right = raw[i1:i2], cor[j1:j2]
                if w and right and w != right and len(w) <= 10 and len(right) <= 10:
                    pairs_f[(w, right)] += 1
    else:
        pairs_f = all_pairs

    if pairs_f:
        st.subheader("📊 高頻錯字 pattern Top 30")
        import pandas as pd
        df_pairs = pd.DataFrame([
            {"次數": c, "raw（被改前）": w, "corrected（改後）": r, "字長": len(w)}
            for (w, r), c in pairs_f.most_common(30)
        ])
        st.dataframe(df_pairs, use_container_width=True, hide_index=True)

    st.divider()

    # 修正紀錄明細
    st.subheader(f"📋 修正紀錄明細（顯示前 50 筆）")
    for r in rows_f[:50]:
        raw = r["transcript"] or ""
        cor = r["corrected_transcript"] or ""
        ts = (r["corrected_at"] or "")[:19]
        eng = r["engine_hint"] or "_unknown"
        with st.expander(f"id={r['id']} ｜ {ts} ｜ 引擎={eng}"):
            st.caption("**raw（STT 原文）**")
            st.code(raw[:300] + ("…" if len(raw) > 300 else ""), language=None)
            st.caption("**corrected（人工修正後）**")
            st.code(cor[:300] + ("…" if len(cor) > 300 else ""), language=None)
            st.caption("**inline diff**")
            _render_inline_diff(raw, cor)

    if len(rows_f) > 50:
        st.caption(f"⋯ 還有 {len(rows_f) - 50} 筆未顯示")


# ============================================================================
# 主程式
# ============================================================================
PAGES = [
    ("speech",             "🎙️ 批次辨識"),
    ("offline_monitor",    "🔒 離線監看"),
    ("evaluation",         "📊 準確率評測"),
    ("cer_trend",          "📈 CER 趨勢（將遷移 Grafana）"),
    ("correction_history", "✏️ 修正歷程"),
    ("management",         "🗂️ 事件管理"),
    ("search",             "🔍 全文搜尋"),
    ("stats",              "📋 統計報表"),
    ("vocabulary",         "📚 詞彙表"),
]

PAGE_RENDERERS = {
    "speech":             lambda: render_speech_page(),
    "running":            lambda: render_running_page(),  # speech 流程的執行階段
    "offline_monitor":    lambda: render_offline_monitor_page(),
    "evaluation":         lambda: render_evaluation_page(),
    "cer_trend":          lambda: render_cer_trend_page(),
    "correction_history": lambda: render_correction_history_page(),
    "management":         lambda: render_management_page(),
    "search":             lambda: render_search_page(),
    "stats":              lambda: render_stats_page(),
    "vocabulary":         lambda: render_vocabulary_page(),
}


def render_lab_sidebar():
    """研究工作台統一側邊欄：9 頁導航 + 方案 C 跨介面連結。"""
    with st.sidebar:
        st.markdown("### 🔬 研究工作台")
        st.caption("aiSpeechMulti Lab")

        current = st.session_state.get("page", "speech")
        labels = [label for _, label in PAGES]
        keys   = [k for k, _ in PAGES]
        try:
            idx = keys.index(current)
        except ValueError:
            idx = 0
        choice = st.radio("頁面", labels, index=idx, label_visibility="collapsed", key="lab_nav_radio")
        chosen_key = keys[labels.index(choice)]
        if chosen_key != current:
            st.session_state["page"] = chosen_key
            st.rerun()

        st.markdown("---")
        st.markdown("#### 🔗 其他介面")
        api_base = st.session_state.get("api_base", API_BASE)
        st.markdown(
            f"""
            - [🎙️ 即時擷取]({api_base}/capture)
            - [📡 五路監控]({api_base}/monitor)
            - [📺 大螢幕投放]({api_base}/display)
            - [📊 Grafana](http://localhost:3000)
            """
        )
        st.caption("即時監控/大螢幕請改開靜態頁，Lab 不再代管。")

        st.markdown("---")
        st.markdown("#### ⚙️ Backend")
        api_input = st.text_input("FastAPI URL", value=api_base, key="lab_api_base_input")
        if st.button("套用", key="lab_apply_api_base"):
            st.session_state["api_base"] = api_input
            st.cache_data.clear()
            st.rerun()


def main():
    init_session_state()
    setup_credentials()

    render_lab_sidebar()

    # 舊路由相容：home/monitor 已廢除，導到 speech
    page = st.session_state.get("page", "speech")
    if page in ("home", "monitor"):
        st.session_state["page"] = "speech"
        st.rerun()

    renderer = PAGE_RENDERERS.get(page)
    if renderer is None:
        st.session_state["page"] = "speech"
        st.rerun()
    else:
        renderer()


if __name__ == "__main__":
    main()
