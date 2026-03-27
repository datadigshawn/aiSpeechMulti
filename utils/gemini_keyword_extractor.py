#!/usr/bin/env python3
"""
aiSpeech Gemini 關鍵字擷取工具
版本: 1.0

功能：
- 以 Gemini API 分析捷運無線電通訊辨識文字
- 自動擷取關鍵術語並評估危害等級（0~5）
- 回傳結構化 list[dict]，可直接寫入 keywords 表

危害等級定義：
  0 = 正常
  1 = 輕微異常
  2 = 需注意
  3 = 中等（影響服務）
  4 = 嚴重
  5 = 緊急（火災／出軌／傷亡）

API Key 載入順序（與 model_gemini.py 相同）：
  1. 環境變數 GEMINI_API_KEY
  2. utils/api_keys.json → 'GEMINI_API_KEY' 欄位
  3. utils/api_keys.py  → GEMINI_API_KEY 變數
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

try:
    from .logger import get_logger
except ImportError:
    import logging
    def get_logger(name):
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)

# 可用模型清單（與 model_gemini.py 保持一致，2026/3/27 更新）
# 已移除：gemini-2.0-flash-exp（2026/3/9 停用）
_MODELS = {
    "gemini-3.1-pro-preview": "gemini-3.1-pro-preview",  # 🆕 最新旗艦 Preview
    "gemini-2.5-flash":       "gemini-2.5-flash",        # ⭐ 推薦：最佳價格/性能
    "gemini-2.5-pro":         "gemini-2.5-pro",          # 最高準確度
    "gemini-2.5-flash-lite":  "gemini-2.5-flash-lite",   # 最快、最省費
    "gemini-2.0-flash":       "gemini-2.0-flash",        # 舊穩定版（2026/6/1 停用）
}

# 預設模型（價格/性能均衡）
_DEFAULT_MODEL = "gemini-2.5-flash"

# 危害等級名稱對照（用於 prompt 說明）
_HAZARD_DESC = {
    0: "正常（無異常）",
    1: "輕微異常（例行通報）",
    2: "需注意（輕微故障或延誤）",
    3: "中等（影響服務、停電、設備故障）",
    4: "嚴重（旅客受困、大規模延誤）",
    5: "緊急（火災、出軌、傷亡）",
}


def _load_api_key() -> str:
    """
    載入 Gemini API Key（多層級 fallback）。

    優先順序：
    1. 環境變數 GEMINI_API_KEY
    2. utils/api_keys.json → 'GEMINI_API_KEY'
    3. utils/api_keys.py  → GEMINI_API_KEY

    Raises:
        ValueError: 所有方式均無法取得 API key
    """
    # 1. 環境變數
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key

    # 2. api_keys.json
    json_paths = [
        Path(__file__).parent / "api_keys.json",
        Path("utils/api_keys.json"),
    ]
    for p in json_paths:
        if p.exists():
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
                key = cfg.get("GEMINI_API_KEY")
                if key:
                    return key
            except Exception:
                pass

    # 3. api_keys.py
    py_paths = [
        Path(__file__).parent / "api_keys.py",
        Path("utils/api_keys.py"),
    ]
    for p in py_paths:
        if p.exists():
            try:
                ns: dict = {}
                exec(p.read_text(encoding="utf-8"), ns)
                key = ns.get("GEMINI_API_KEY")
                if key:
                    return key
            except Exception:
                pass

    raise ValueError(
        "找不到 Gemini API Key。\n"
        "請設定環境變數 GEMINI_API_KEY，"
        "或在 utils/api_keys.json 中加入 {'GEMINI_API_KEY': 'your-key'}。"
    )


class GeminiKeywordExtractor:
    """
    以 Gemini 分析無線電通訊文字，擷取關鍵術語並評估危害等級。

    使用方式：
        extractor = GeminiKeywordExtractor()
        keywords = extractor.extract(
            merged_transcript="OCC 收到，G05 請求疏散...",
            event_name="捷運火災事件"
        )
        # keywords → [{"keyword": "火災", "hazard_level": 5}, ...]
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL):
        """
        初始化擷取器。

        Args:
            model_name: Gemini 模型名稱（預設 gemini-2.5-flash）
        """
        import google.generativeai as genai

        self.logger = get_logger(self.__class__.__name__)
        self.model_name = _MODELS.get(model_name, model_name)

        api_key = _load_api_key()
        genai.configure(api_key=api_key)

        self._model = genai.GenerativeModel(
            model_name=self.model_name,
            generation_config={
                "temperature": 0.1,      # 低溫度確保一致性
                "top_p": 0.95,
                "max_output_tokens": 1024,
            },
        )
        self.logger.info(f"GeminiKeywordExtractor 初始化：模型={self.model_name}")

    def extract(
        self,
        merged_transcript: str,
        event_name: str = "未命名事件",
        max_keywords: int = 30,
    ) -> list:
        """
        從辨識文字擷取關鍵字及危害等級。

        Args:
            merged_transcript: 事件的彙整辨識文字（多檔合併後）
            event_name:        事件名稱（用於 prompt 上下文）
            max_keywords:      最多回傳幾個關鍵字

        Returns:
            list[dict]: 每個元素為 {"keyword": str, "hazard_level": int}
                        已去重、依危害等級降冪排序
        """
        if not merged_transcript.strip():
            self.logger.warning("辨識文字為空，跳過關鍵字擷取")
            return []

        prompt = self._build_prompt(merged_transcript, event_name, max_keywords)

        try:
            response = self._model.generate_content(prompt)
            raw_text = response.text
            self.logger.debug(f"Gemini 回傳（前200字）：{raw_text[:200]!r}")
        except Exception as e:
            self.logger.error(f"Gemini API 呼叫失敗：{e}")
            raise

        keywords = self._parse_response(raw_text)
        self.logger.info(
            f"擷取到 {len(keywords)} 個關鍵字（事件：{event_name!r}）"
        )
        return keywords

    # ── 內部工具 ────────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        transcript: str,
        event_name: str,
        max_keywords: int,
    ) -> str:
        """組合 Gemini 分析 prompt。"""
        hazard_lines = "\n".join(
            f"  {k}={v}" for k, v in _HAZARD_DESC.items()
        )
        return f"""你是台灣捷運系統緊急事件分析專家，專精無線電通訊術語。

以下是事件「{event_name}」的無線電辨識文字：

---
{transcript}
---

請從辨識文字中擷取重要術語，涵蓋以下類別：
1. 事件類型（如：火災、出軌、異物、停電、受困）
2. 地點代號（如：G05、一月台、軌道）
3. 行動指令（如：疏散、封鎖、啟動、請求支援）
4. 設備名稱（如：VVVF、轉轍器、月台門、EDRH）
5. 人員角色（如：司機員、站務員、行控人員、OCC）

危害等級定義：
{hazard_lines}

輸出格式（每行一個術語）：
術語,危害等級數字

規則：
- 只輸出「術語,數字」，不要任何其他說明文字
- 最多 {max_keywords} 個術語
- 不重複
- 若無法判斷危害等級，填 0
- 術語限 2~8 個中文字或英文字母數字組合

範例輸出：
火災,5
疏散旅客,5
G05,2
月台門,1
OCC,0
"""

    def _parse_response(self, text: str) -> list:
        """
        解析 Gemini 回傳文字為 list[dict]。

        接受格式：「術語,數字」，每行一個。
        自動過濾無效行、去重、依危害等級降冪排序。
        """
        seen = set()
        results = []

        for line in text.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # 嘗試解析「術語,數字」
            # 允許全形逗號、空白
            line = line.replace("，", ",").replace(" ", "")
            parts = line.split(",", 1)
            if len(parts) != 2:
                continue

            keyword = parts[0].strip()
            level_str = re.sub(r"[^\d]", "", parts[1])

            if not keyword or not level_str:
                continue

            # 術語長度限制（2~12 字）
            if not (2 <= len(keyword) <= 12):
                continue

            try:
                level = int(level_str)
                level = max(0, min(5, level))  # clamp 0~5
            except ValueError:
                level = 0

            if keyword not in seen:
                seen.add(keyword)
                results.append({"keyword": keyword, "hazard_level": level})

        # 依危害等級降冪排序
        results.sort(key=lambda x: x["hazard_level"], reverse=True)
        return results


# ── CLI 測試 ─────────────────────────────────────────────────────────────────

def _cli_test():
    """
    本地測試（需要有效的 GEMINI_API_KEY）。
    不依賴 Streamlit，直接在 terminal 執行：
        python3 utils/gemini_keyword_extractor.py
    """
    sample_text = """
    OCC 收到，G05 立即至月台疏散旅客。
    司機員通報列車於 G05 月台停靠，發現煙霧，疑似火災。
    行控人員指示站務員啟動緊急按鈕，封鎖月台門。
    維修人員已出發，預計 5 分鐘抵達。
    月台門故障，電聯車無法正常發車，晚點約 10 分鐘。
    """

    print("=== GeminiKeywordExtractor 測試 ===")
    try:
        extractor = GeminiKeywordExtractor()
        results = extractor.extract(sample_text, event_name="G05 煙霧事件")

        print(f"擷取到 {len(results)} 個關鍵字：")
        for r in results:
            level = r["hazard_level"]
            bar = "█" * level + "░" * (5 - level)
            print(f"  [{bar}] L{level}  {r['keyword']}")

    except ValueError as e:
        print(f"❌ API Key 錯誤：{e}")
    except Exception as e:
        print(f"❌ 執行失敗：{e}")
        raise


if __name__ == "__main__":
    _cli_test()
