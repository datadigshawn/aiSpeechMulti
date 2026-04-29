"""
Gemini Client 共用 helper
==========================
封裝 google-genai 新版 SDK 的 client 建立與 API key 解析。
取代各處重複的 genai.configure(api_key=...) 呼叫。

用法：
    from utils.gemini_client import get_client, genai_types

    client = get_client()  # 自動找 GEMINI_API_KEY（多層 fallback）
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="hello",
        config=genai_types.GenerateContentConfig(temperature=0.0),
    )
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

# 新版 SDK（取代舊版 google-generativeai）
from google import genai
from google.genai import types as genai_types  # re-export 給呼叫端用

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_api_key(api_key: Optional[str] = None) -> Optional[str]:
    """
    多層級 fallback 取 GEMINI_API_KEY：
      1. 直接傳入的 api_key
      2. 環境變數 GEMINI_API_KEY
      3. utils/api_keys.json 的 GEMINI_API_KEY 欄位
    回傳 None 表示找不到（呼叫端自行處理）。
    """
    if api_key:
        return api_key

    env_key = os.environ.get("GEMINI_API_KEY")
    # 過濾無效值（例如 .env 中誤把路徑塞進來）
    if env_key and not env_key.endswith((".rtf", ".json", ".txt")) and len(env_key) > 10:
        return env_key

    json_path = PROJECT_ROOT / "utils" / "api_keys.json"
    if json_path.exists():
        try:
            cfg = json.loads(json_path.read_text(encoding="utf-8"))
            k = cfg.get("GEMINI_API_KEY")
            if k:
                return k
        except Exception:
            pass

    return None


def get_client(api_key: Optional[str] = None) -> genai.Client:
    """取得 genai.Client（新版 SDK）。找不到 API key 會 raise ValueError。"""
    key = resolve_api_key(api_key)
    if not key:
        raise ValueError(
            "找不到 GEMINI_API_KEY："
            "請設定環境變數，或在 utils/api_keys.json 加入 GEMINI_API_KEY 欄位"
        )
    return genai.Client(api_key=key)


__all__ = ["get_client", "resolve_api_key", "genai_types"]
