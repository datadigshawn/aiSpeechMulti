"""Lab 圖表樣式純邏輯（自 app_lab.py 原封抽出，2026-06-16 P3 第一波）。"""

from __future__ import annotations


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
