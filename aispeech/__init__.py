"""aiSpeechMulti 統一 CLI 包（P3 介面整併）。

提供 `python -m aispeech` 進入點，把分散的 scripts/*.py 收斂為單一指令樹。
不重寫既有邏輯，只是 thin wrapper：subprocess 透傳所有參數給對應的舊腳本。
"""

__version__ = "0.1.0"
