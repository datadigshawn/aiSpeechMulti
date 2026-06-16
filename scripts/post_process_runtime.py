"""即時辨識路徑專用的 deterministic 後處理 wrapper。

app_api.py 的 final / committed transcript 透過這支接 scripts.post_process，
讓 Lab 已驗證的 deterministic 規則（車號、字典、contextual、station code、
number、term filter）真正進入生產即時辨識。

設計約束（即時路徑安全閘）：
- enable_llm 寫死 False，不接受外部開啟 —— 即時路徑不得有 LLM 延遲與成本。
- 只處理 final / committed transcript，partial 不應呼叫本函式。
- 空字串 / 純空白原樣回傳，不進 pipeline。

這支刻意獨立成檔：P1 抽共享後處理核心時直接 promote 它，讓
app_api / app_lab / batch eval 共用同一套 deterministic rules。
"""

from __future__ import annotations

from typing import Optional

from scripts.post_process import post_process


def post_process_realtime(
    text: str,
    engine_hint: Optional[str] = None,
) -> tuple[str, dict]:
    """對 final transcript 跑 deterministic 後處理（永不呼叫 LLM）。

    Args:
        text: STT final / committed 辨識文字。
        engine_hint: 上游引擎類型（如 "google_stream" / "sensevoice"），
            傳給 post_process 供規則判斷使用。

    Returns:
        (corrected_text, report_dict)。空輸入時 report 為空 dict。
    """
    if not text or not text.strip():
        return text or "", {}

    return post_process(
        text,
        enable_llm=False,
        engine_hint=engine_hint,
    )
