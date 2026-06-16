"""STT 引擎單一工廠：create_engine(name, **opts) -> STTEngine。

2026-06-16 第三波（P2）。把分散的引擎實例化收斂到單一入口。本波先讓
app_api.create_stt_model 委派給它；scripts/batch_stt_eval.make_engine 與
app_lab inline 實例化留待後波收斂。

新增 WhisperModel：把唯一的函式型 outlier transcribe_with_whisper() 包成
具 transcribe_file() 的類別、回傳 STTResult，使其也符合 STTEngine 契約。
"""

from __future__ import annotations

from typing import Any

from scripts.models.base import STTEngine, STTResult


class WhisperModel:
    """把 transcribe_with_whisper() 函式包成符合 STTEngine 契約的類別。

    既有函式 transcribe_with_whisper 維持不變；此類別僅提供 transcribe_file()
    薄封裝並回傳 STTResult（示範新契約；無既有 dict 消費端，故安全）。
    """

    name = "whisper"

    def __init__(self, model_size: str = "large-v3", language: str = "zh",
                 use_vocabulary: bool = True):
        self.model_size = model_size
        self.language = language
        self.use_vocabulary = use_vocabulary

    def transcribe_file(self, audio_file: str, **kwargs) -> STTResult:
        from scripts.models.model_whisper import transcribe_with_whisper
        out = transcribe_with_whisper(
            audio_file,
            model_size=kwargs.get("model_size", self.model_size),
            use_vocabulary=kwargs.get("use_vocabulary", self.use_vocabulary),
            language=kwargs.get("language", self.language),
            event_type=kwargs.get("event_type"),
            return_segments=True,  # 取 dict 形式，攤平成 STTResult
        )
        if isinstance(out, dict):
            return STTResult(
                transcript=out.get("transcript", ""),
                segments=out.get("segments"),
            )
        # 理論上 return_segments=True 不會走到這，保險處理純文字回傳
        return STTResult(transcript=str(out))


# name → 建構函式。lazy import 避免載入未使用引擎的重相依（torch / SDK）。
def create_engine(name: str, **opts: Any) -> STTEngine:
    """依 name 建立 STT 引擎實例。

    支援 name：
      google / chirp3       → GoogleSTTModel
      scribe                → ScribeSTTModel
      sensevoice            → SenseVoiceModel
      sensevoice_ft         → SenseVoiceFTModel
      gemini                → GeminiModel（model 由 opts 指定，預設 gemini-2.5-flash）
      whisper               → WhisperModel
    opts 透傳給對應建構函式；未提供者用各引擎預設。
    """
    key = name.lower()

    if key in ("google", "chirp3"):
        from scripts.models.model_google_stt import GoogleSTTModel
        return GoogleSTTModel(**opts)

    if key == "scribe":
        from scripts.models.model_scribe import ScribeSTTModel
        return ScribeSTTModel(**opts)

    if key == "sensevoice":
        from scripts.models.model_sensevoice import SenseVoiceModel
        return SenseVoiceModel(**opts)

    if key == "sensevoice_ft":
        from scripts.models.model_sensevoice_ft import SenseVoiceFTModel
        return SenseVoiceFTModel(**opts)

    if key == "gemini":
        from scripts.models.model_gemini import GeminiModel
        return GeminiModel(**opts)

    if key == "whisper":
        return WhisperModel(**opts)

    raise ValueError(f"Unknown engine name: {name!r}")
