#!/usr/bin/env python3
"""
混合模式結果融合器 (ResultFuser)
版本: 1.0.0 (2026-03-30)

根據 Google STT 與 Gemini 的辨識結果，依一致性分數選取最佳輸出。

融合規則（依優先順序）：
  R1. 兩模型均有結果，互比 CER < 10%（高度一致）→ 取 Google STT
      （confidence 較可靠，繁體中文穩定）
  R2. 兩模型均有結果，互比 CER 10–40%（中度差異）→ 取 Gemini
      （語意理解較強，適合術語密集場景）
  R3. 兩模型均有結果，互比 CER > 40%（極大差異）→ 取 Google STT
      （差異過大通常代表其中一方嚴重錯誤；Google 有 confidence 作為可信度參考）
  R4. Google 有結果，Gemini 空白 → 取 Google STT
  R5. Gemini 有結果，Google 空白 → 取 Gemini
  R6. 兩者皆空，Scribe 有結果 → 取 Scribe（最後防線）
  R7. 全部失敗 → 回傳空字串 + error 欄位

CER 門檻值可透過建構子參數調整，以便依實際評測結果優化。
"""

import sys
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import get_logger
from scripts.cer_engine import calculate_cer

logger = get_logger(__name__)

# 預設 CER 門檻值
_DEFAULT_HIGH_CONSISTENCY = 0.10   # < 10%：高度一致 → 取 Google STT
_DEFAULT_MEDIUM_DIFF      = 0.40   # 10–40%：中度差異 → 取 Gemini
                                   # > 40%：極大差異 → 取 Google STT


class ResultFuser:
    """
    雙引擎辨識結果融合器（Google STT + Gemini，Scribe 作備援）。

    使用方式：
        fuser = ResultFuser()
        result = fuser.fuse(
            chunk_id="audio_001",
            google_result={"transcript": "OCC通報測試", "confidence": 0.92},
            gemini_result={"transcript": "OCC通告測試"},
        )
        print(result["transcript"])   # 最終選用文字
        print(result["source"])       # "google" | "gemini" | "scribe" | ""
        print(result["rule"])         # "R1" … "R7"
        print(result["cer_between"])  # 兩模型互比 CER，None 表示無法計算
    """

    def __init__(
        self,
        cer_high_consistency: float = _DEFAULT_HIGH_CONSISTENCY,
        cer_medium_diff: float = _DEFAULT_MEDIUM_DIFF,
    ):
        """
        Args:
            cer_high_consistency: CER 低於此值視為高度一致（預設 0.10）
            cer_medium_diff:      CER 低於此值視為中度差異（預設 0.40）
        """
        self.cer_high_consistency = cer_high_consistency
        self.cer_medium_diff      = cer_medium_diff

    def fuse(
        self,
        chunk_id: str,
        google_result: Dict,
        gemini_result: Dict,
        scribe_result: Optional[Dict] = None,
    ) -> Dict:
        """
        融合兩個（或三個）模型的辨識結果。

        Args:
            chunk_id:      音檔識別碼（用於日誌）
            google_result: GoogleSTTModel.transcribe_file() 的回傳值
            gemini_result: GeminiModel.transcribe_file() 的回傳值
            scribe_result: ScribeSTTModel.transcribe_file() 的回傳值（可為 None）

        Returns:
            {
                "transcript":        str,        # 最終選用文字
                "transcript_raw":    str,        # 同 transcript（與其他模型介面相容）
                "source":            str,        # "google" | "gemini" | "scribe" | ""
                "rule":              str,        # 套用規則 "R1"–"R7"
                "cer_between":       float|None, # 兩模型互比 CER（0.0–1.0）
                "confidence":        float,      # 選用模型的信心度（Gemini/Scribe 固定 0.0）
                "google_transcript": str,        # Google STT 原始結果（供診斷）
                "gemini_transcript": str,        # Gemini 原始結果（供診斷）
            }
        """
        g_text = (google_result.get("transcript") or "").strip()
        m_text = (gemini_result.get("transcript") or "").strip()
        s_text = (scribe_result.get("transcript") or "").strip() if scribe_result else ""
        g_conf = float(google_result.get("confidence") or 0.0)

        # ── 計算兩模型互比 CER（僅在雙方均有輸出時）────────────────────────
        cer_between: Optional[float] = None
        if g_text and m_text:
            try:
                cer_between = calculate_cer(g_text, m_text)["cer"]
            except Exception as exc:
                logger.warning(f"[{chunk_id}] CER 計算失敗：{exc}")

        # ── 套用融合規則 ─────────────────────────────────────────────────────
        if g_text and m_text and cer_between is not None:
            if cer_between < self.cer_high_consistency:        # R1：高度一致
                final, source, rule = g_text, "google", "R1"
            elif cer_between <= self.cer_medium_diff:          # R2：中度差異
                final, source, rule = m_text, "gemini", "R2"
            else:                                              # R3：極大差異
                final, source, rule = g_text, "google", "R3"
        elif g_text and not m_text:                            # R4：僅 Google
            final, source, rule = g_text, "google", "R4"
        elif m_text and not g_text:                            # R5：僅 Gemini
            final, source, rule = m_text, "gemini", "R5"
        elif s_text:                                           # R6：Scribe 備援
            final, source, rule = s_text, "scribe",  "R6"
        else:                                                  # R7：全部失敗
            final, source, rule = "",    "",          "R7"

        cer_pct = f"{cer_between:.1%}" if cer_between is not None else "N/A"
        logger.info(
            f"[{chunk_id}] 融合｜規則={rule}｜來源={source or '(空)'}｜"
            f"CER(G↔M)={cer_pct}｜"
            f"Google={len(g_text)}字 Gemini={len(m_text)}字"
        )

        return {
            "transcript":        final,
            "transcript_raw":    final,
            "source":            source,
            "rule":              rule,
            "cer_between":       cer_between,
            "confidence":        g_conf if source == "google" else 0.0,
            "google_transcript": g_text,
            "gemini_transcript": m_text,
        }
