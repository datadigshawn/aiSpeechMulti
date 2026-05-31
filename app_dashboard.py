#!/usr/bin/env python3
"""
app_dashboard.py — DEPRECATED
====================================================================
此檔已於 2026-05-04 介面整併 P0 拆分為兩個入口：

  1. 研究工作台 Lab    →  streamlit run app_lab.py
     speech / offline_monitor / evaluation / cer_trend /
     correction_history / management / search / stats / vocabulary

  2. 即時介面         →  python app_api.py 後開瀏覽器
     :8000/           landing
     :8000/capture    擷取頁
     :8000/monitor    六路監控
     :8000/display    大螢幕投放

舊的 home / monitor / running 三頁已移除（取代為靜態 HTML WebSocket 推送版）。

本檔保留 30 天作為過渡警示，之後將刪除。請更新所有書籤與啟動腳本。
====================================================================
"""

import sys

import streamlit as st

st.set_page_config(
    page_title="aiSpeechMulti — Dashboard 已拆分",
    page_icon="⚠️",
    layout="centered",
)

st.title("⚠️ app_dashboard.py 已停用")
st.markdown(
    """
    Dashboard 已於 **2026-05-04 介面整併 P0** 拆分為兩個入口：

    | 介面 | 啟動方式 | 包含 |
    |---|---|---|
    | 🔬 **研究工作台 Lab** | `streamlit run app_lab.py` | 批次辨識、評測、詞彙、CER 趨勢、修正飛輪、事件管理 |
    | 📡 **即時介面** | `python app_api.py` 後開 `:8000/` | 擷取頁、六路監控、大螢幕投放、Landing |

    舊的 `home` / `monitor` / `running` 三頁已移除，
    對應功能改由 FastAPI 直供的靜態 HTML 提供（WebSocket 推送，體驗優於原 Streamlit 輪詢版）。

    本檔保留 30 天作為過渡警示，之後將刪除。請更新所有書籤與啟動腳本。
    """
)

st.divider()

st.info(
    "若你正在尋找原本的功能，請改執行：\n\n"
    "```\nstreamlit run app_lab.py\n```\n\n"
    "並把 `:8000/` landing 加入瀏覽器書籤。"
)

if st.button("立即跳到 Lab 啟動指引（複製指令）"):
    st.code("streamlit run app_lab.py", language="bash")

# 不繼續執行任何舊邏輯
sys.exit(0)
