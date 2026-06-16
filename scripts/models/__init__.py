"""
AI 模型模組
包含 Google STT、Whisper、Gemini、SenseVoice、Scribe 的封裝，
以及引擎契約（base）與單一工廠（factory）。

2026-06-16 第三波：改為 PEP 562 lazy import —— `import scripts.models`
（與其下的 base / factory）不再強制載入 google / gemini SDK，降低引擎層耦合。
`from scripts.models import GoogleSTTModel` 仍可用（存取時才實際載入）。
"""

import importlib

# 公開名稱 → 所屬子模組（相對路徑）
_LAZY = {
    "GoogleSTTModel": ".model_google_stt",
    "GeminiModel": ".model_gemini",
}

__all__ = list(_LAZY)


def __getattr__(name: str):
    """PEP 562：存取屬性時才 lazy import 對應引擎，避免套件載入即拉重相依。"""
    if name in _LAZY:
        mod = importlib.import_module(_LAZY[name], __name__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
