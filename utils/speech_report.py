"""
語音逐字稿重點整理報告產生器

使用 Gemini 把 STT 逐字稿轉為結構化 5 段報告：
  - 一句話總結
  - 核心觀點
  - 關鍵術語 / 名詞
  - 章節時間軸
  - 行動建議 / 可實作要點

純函式 + 可單測；LLM 呼叫透過 utils.gemini_client.get_client()。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


PROMPT_TEMPLATE = """你是專業的內容分析師。根據以下語音逐字稿，產出結構化重點整理報告。

【嚴格輸出格式】（使用 markdown，**章節順序與標題不可更動**）：

## 一句話總結
（30 字以內的核心訊息）

## 核心觀點
（5–8 條，每條 1 行 bullet 開頭）
- 觀點 1
- 觀點 2
...

## 關鍵術語 / 名詞
（5–15 個專業術語，每條附 1–2 句說明）
- 術語：說明
- 術語：說明

## 章節時間軸
（若逐字稿可推斷時間/章節順序，列出主要章節；若無時間戳記則寫「無法從逐字稿推斷明確時間軸」）
- 段落 1 主題
- 段落 2 主題

## 行動建議 / 可實作要點
（從內容中萃取「讀者可以實際做的事」；若無則寫「無」）
- ...

---

【逐字稿】：
{transcript}
"""


def parse_audio_time_range(filename_datetimes: dict) -> str:
    """從 STT 既有的 filename->datetime 對應推出時間範圍字串。

    - 多檔且有時間：'2025-XX-XX HH:MM:SS ~ HH:MM:SS'
    - 單檔且有時間：'2025-XX-XX HH:MM:SS'
    - 沒有任何可解析的時間（例如 YouTube 下載）：'無'
    """
    if not filename_datetimes:
        return "無"
    dts = sorted(filename_datetimes.values())
    if len(dts) == 1:
        return dts[0].strftime("%Y-%m-%d %H:%M:%S")
    return f"{dts[0].strftime('%Y-%m-%d %H:%M:%S')} ~ {dts[-1].strftime('%H:%M:%S')}"


def format_report_file(
    report_md: str,
    sources: list[str],
    audio_time_range: str,
    generated_at: Optional[datetime] = None,
) -> str:
    """把 LLM 輸出包成符合模板的最終報告 txt 字串。"""
    if generated_at is None:
        generated_at = datetime.now()
    sources_str = "、".join(sources) if sources else "（未知）"
    return (
        "============================================================\n"
        "【語音辨識報告】\n"
        f"檔名：{sources_str}\n"
        f"產出時間：{generated_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"語音時間：{audio_time_range}\n"
        "\n"
        "============================================================\n"
        "【報告內容】\n"
        "\n"
        f"{report_md.strip()}\n"
    )


def estimate_gemini_cost_twd(
    tokens_in: int,
    tokens_out: int,
    model: str = "gemini-2.5-flash",
    pricing_path: Optional[Path] = None,
) -> dict:
    """估算 Gemini 呼叫成本。

    從 config/pricing.json 讀價，回傳 {usd, twd, tokens_in, tokens_out, model}。
    若 pricing.json 沒有該 model，使用內建保守估價（會在回傳 dict 加 fallback=True）。
    """
    # 內建保守估價（Google 公開定價 2026-Q1，請以實際帳單為準）
    DEFAULT_PRICING = {
        "gemini-2.5-flash": {"usd_per_1m_in": 0.30, "usd_per_1m_out": 2.50},
        "gemini-2.5-pro":   {"usd_per_1m_in": 1.25, "usd_per_1m_out": 10.00},
    }

    if pricing_path is None:
        pricing_path = Path(__file__).parent.parent / "config" / "pricing.json"

    rate_twd = 31.0
    fallback = True
    pricing = DEFAULT_PRICING.get(model, DEFAULT_PRICING["gemini-2.5-flash"])

    try:
        cfg = json.loads(Path(pricing_path).read_text(encoding="utf-8"))
        rate_twd = cfg.get("usd_to_twd", 31.0)
        eng = cfg.get("engines", {}).get(model)
        if eng and "usd_per_1m_in" in eng and "usd_per_1m_out" in eng:
            pricing = {
                "usd_per_1m_in":  eng["usd_per_1m_in"],
                "usd_per_1m_out": eng["usd_per_1m_out"],
            }
            fallback = False
    except Exception:
        pass

    usd = (tokens_in / 1_000_000) * pricing["usd_per_1m_in"] + \
          (tokens_out / 1_000_000) * pricing["usd_per_1m_out"]
    return {
        "usd":         round(usd, 6),
        "twd":         round(usd * rate_twd, 4),
        "tokens_in":   tokens_in,
        "tokens_out":  tokens_out,
        "model":       model,
        "fallback_pricing": fallback,
    }


def generate_report(
    transcript: str,
    model: str = "gemini-2.5-flash",
    temperature: float = 0.3,
    max_output_tokens: int = 4096,
) -> dict:
    """呼叫 Gemini 產生重點整理報告。

    回傳 dict:
      report_md   - LLM 輸出的 markdown
      tokens_in   - 輸入 token 數（含 prompt template）
      tokens_out  - 輸出 token 數
      elapsed_s   - 呼叫耗時（秒）
      model       - 使用的模型
      cost        - estimate_gemini_cost_twd() 結果

    失敗時 raise RuntimeError。
    """
    if not transcript or not transcript.strip():
        raise RuntimeError("逐字稿為空，無內容可整理")

    # 懶載入：只在實際呼叫時才 import，方便單測 mock
    from utils.gemini_client import get_client, genai_types

    client = get_client()
    prompt = PROMPT_TEMPLATE.format(transcript=transcript.strip())

    t0 = time.time()
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
        )
    except Exception as e:
        raise RuntimeError(f"Gemini 呼叫失敗：{e}")
    elapsed = time.time() - t0

    report_md = (resp.text or "").strip()
    if not report_md:
        raise RuntimeError("Gemini 回傳空內容（可能被 safety filter 擋下，或 max_output_tokens 不足）")

    usage = getattr(resp, "usage_metadata", None)
    tokens_in  = getattr(usage, "prompt_token_count", 0) if usage else 0
    tokens_out = getattr(usage, "candidates_token_count", 0) if usage else 0

    return {
        "report_md":  report_md,
        "tokens_in":  tokens_in,
        "tokens_out": tokens_out,
        "elapsed_s":  round(elapsed, 1),
        "model":      model,
        "cost":       estimate_gemini_cost_twd(tokens_in, tokens_out, model=model),
    }


def safe_filename_fragment(text: str, max_len: int = 60) -> str:
    """把任意字串清成檔案系統安全的 fragment（用於組報告檔名）。"""
    if not text:
        return "report"
    t = re.sub(r'[\\/:*?"<>|\n\r\t]', "", text)
    t = re.sub(r"\s+", "_", t).strip("_")
    if len(t) > max_len:
        t = t[:max_len].rstrip("_")
    return t or "report"
