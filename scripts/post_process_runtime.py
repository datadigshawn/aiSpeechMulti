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

from pathlib import Path
from typing import Optional

from scripts.post_process import post_process

# 同音選字校正器（語言層，char n-gram rescoring）。
# 預設 OFF：需 ① 擴 LM 語料（會議記錄/席位逐字稿）② 在真實資料量過誤改率後才開啟。
# 見 _decisions/2026-06-12 選字問題策略 — 辭典 vs 語言模型。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LM_PKL = _PROJECT_ROOT / "experiments" / "ngram_lm" / "char_4gram.pkl"
_TERMS_TXT = _PROJECT_ROOT / "experiments" / "lm_corpus" / "glossary" / "domain_terms_zh.txt"
_HOMOPHONE_CORRECTOR = None
_HOMOPHONE_LOADED = False


def _get_homophone_corrector():
    """惰性載入校正器（缺 pypinyin / .pkl 時回 None，不影響主流程）。

    一併載入域術語表（運務處專有名詞彙編）供「保護＋偏好」。
    """
    global _HOMOPHONE_CORRECTOR, _HOMOPHONE_LOADED
    if not _HOMOPHONE_LOADED:
        _HOMOPHONE_LOADED = True
        try:
            from scripts.homophone_corrector import HomophoneCorrector
            _HOMOPHONE_CORRECTOR = HomophoneCorrector.from_pickle(
                _LM_PKL, terms_path=_TERMS_TXT
            )
        except Exception:
            _HOMOPHONE_CORRECTOR = None
    return _HOMOPHONE_CORRECTOR


def post_process_realtime(
    text: str,
    engine_hint: Optional[str] = None,
    enable_homophone_lm: bool = False,
) -> tuple[str, dict]:
    """對 final transcript 跑 deterministic 後處理（永不呼叫 LLM）。

    Args:
        text: STT final / committed 辨識文字。
        engine_hint: 上游引擎類型（如 "google_stream" / "sensevoice"），
            傳給 post_process 供規則判斷使用。
        enable_homophone_lm: 是否在 deterministic 規則後再跑同音選字 LM 校正。
            預設 False（即時路徑安全閘，待擴語料 + 量誤改率後才開啟）。

    Returns:
        (corrected_text, report_dict)。空輸入時 report 為空 dict。
    """
    if not text or not text.strip():
        return text or "", {}

    corrected, report = post_process(
        text,
        enable_llm=False,
        engine_hint=engine_hint,
    )

    if enable_homophone_lm:
        hc = _get_homophone_corrector()
        if hc is not None:
            new_text, changes = hc.correct(corrected)
            if changes:
                corrected = new_text
                report = {**report, "homophone_lm": changes}

    return corrected, report
