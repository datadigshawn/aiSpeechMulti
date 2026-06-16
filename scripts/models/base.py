"""STT 引擎層契約：STTResult + STTEngine / StreamingSTTEngine Protocol。

2026-06-16 第三波（P2）。目標是給引擎層一個共同契約，但**非破壞性**：
- 現有引擎（GoogleSTTModel / ScribeSTTModel / SenseVoiceModel / GeminiModel）
  本來就有 transcribe_file()，結構上即符合 STTEngine Protocol，不必改。
- STTResult 為「目標回傳型別」，本波由工廠產物（WhisperModel）與新程式碼採用；
  既有引擎續回 dict。STTResult 實作 Mapping 相容，未來可逐步無痛取代 dict 回傳
  —— 消費端的 result.get("transcript") / result["transcript"] 仍可運作。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Optional, Protocol, runtime_checkable


# 規範欄位：to_dict / from_dict 以此為準，其餘併入 extra。
_CANONICAL_FIELDS = (
    "transcript",
    "confidence",
    "segments",
    "words",
    "audio_seconds",
    "error",
    "raw",
)


@dataclass
class STTResult:
    """統一的 STT 回傳型別。

    canonical 欄位涵蓋跨引擎共通資訊；引擎特有欄位（如 SenseVoice 的
    emotion / events、Google 的 has_diarization / transcript_raw）放入 extra。

    Mapping 相容：實作 get / __getitem__ / __contains__ / keys / items，
    讓 STTResult 能取代既有 dict 回傳而不破壞 result.get(...) 消費端。
    """

    transcript: str = ""
    confidence: Optional[float] = None
    segments: Optional[list] = None
    words: Optional[list] = None
    audio_seconds: Optional[float] = None
    error: Optional[str] = None
    raw: Any = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """攤平成 dict：canonical 欄位 + extra（extra 不覆寫 canonical）。"""
        d = {f: getattr(self, f) for f in _CANONICAL_FIELDS}
        for k, v in self.extra.items():
            d.setdefault(k, v)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "STTResult":
        """由引擎回傳的 dict 建構；非 canonical 的 key 收進 extra。"""
        known = {k: d[k] for k in _CANONICAL_FIELDS if k in d}
        extra = {k: v for k, v in d.items() if k not in _CANONICAL_FIELDS}
        return cls(**known, extra=extra)

    # ── Mapping 相容（讓 dict 消費端無痛沿用）─────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __contains__(self, key: object) -> bool:
        return key in self.to_dict()

    def keys(self):
        return self.to_dict().keys()

    def items(self):
        return self.to_dict().items()

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())


@runtime_checkable
class STTEngine(Protocol):
    """批次辨識引擎契約。

    只要求 transcribe_file —— 這是 GoogleSTTModel / ScribeSTTModel /
    SenseVoiceModel / GeminiModel 的共通方法，故四者結構上即符合，不必改。
    回傳目前仍為 dict（本波不遷移），未來逐步改回 STTResult。
    """

    def transcribe_file(self, audio_file: str, **kwargs) -> Any:
        ...


@runtime_checkable
class StreamingSTTEngine(Protocol):
    """串流辨識引擎契約（canonical 形狀，採 Google stream_recognize 介面）。

    注意：目前 ScribeRealtimeStream 走 connect/send_audio/receive 的不同介面，
    尚未統一到此 Protocol —— streaming 介面的實際遷移留待後波，本波僅定義目標契約。
    """

    async def stream_recognize(self, *args, **kwargs) -> Any:
        ...
