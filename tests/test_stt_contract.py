"""Tests for STT 引擎契約（scripts/models/base.py + factory.py）。

第三波（P2）：非破壞契約。涵蓋
- STTResult Mapping 相容（取代 dict 回傳的關鍵）。
- STTEngine runtime_checkable Protocol 行為。
- 既有引擎類別結構上符合契約（不實例化重模型）。
- create_engine 路由與 opts 透傳（heavy 引擎以 patch 驗證，不真初始化）。
- WhisperModel.transcribe_file 回傳 STTResult。
"""

from __future__ import annotations

import sys
import types
from unittest.mock import Mock

import pytest

from scripts.models.base import STTResult, STTEngine
from scripts.models.factory import create_engine, WhisperModel


def _inject_fake_engine(monkeypatch, dotted: str, attr: str) -> Mock:
    """注入假的引擎子模組到 sys.modules，讓 create_engine 的 lazy import
    取到假類別 —— 使工廠路由測試不依賴未安裝的引擎 SDK，且真正驗證路由。"""
    mod = types.ModuleType(dotted)
    cls = Mock(name=attr)
    setattr(mod, attr, cls)
    monkeypatch.setitem(sys.modules, dotted, mod)
    return cls


# ─────────────────────────────────────────────────────────────────────────────
# STTResult Mapping 相容
# ─────────────────────────────────────────────────────────────────────────────

class TestSTTResultMapping:
    def test_attr_and_item_agree(self):
        r = STTResult(transcript="hi", confidence=0.9)
        assert r["transcript"] == r.transcript == "hi"
        assert r["confidence"] == r.confidence == 0.9

    def test_get_default(self):
        r = STTResult(transcript="hi")
        assert r.get("transcript") == "hi"
        assert r.get("nonexistent") is None
        assert r.get("nonexistent", "x") == "x"

    def test_contains_and_keys(self):
        r = STTResult(transcript="hi")
        assert "transcript" in r
        assert "transcript" in r.keys()

    def test_extra_flattened(self):
        """引擎特有欄位（emotion_label 等）攤平後，dict 消費端可直接讀。"""
        r = STTResult(transcript="hi", extra={"emotion_label": "😐 中性"})
        assert r.get("emotion_label") == "😐 中性"
        assert r["emotion_label"] == "😐 中性"
        assert "emotion_label" in r

    def test_from_dict_round_trip(self):
        d = {"transcript": "hi", "confidence": 0.8, "emotion": "NEUTRAL",
             "has_diarization": True}
        r = STTResult.from_dict(d)
        assert r.transcript == "hi"
        assert r.confidence == 0.8
        # 非 canonical 的 key 收進 extra
        assert r.extra == {"emotion": "NEUTRAL", "has_diarization": True}
        # to_dict 還原（canonical None 欄位也會在，但原 key 值不丟）
        back = r.to_dict()
        for k, v in d.items():
            assert back[k] == v

    def test_extra_does_not_override_canonical(self):
        r = STTResult(transcript="canonical", extra={"transcript": "shadow"})
        assert r["transcript"] == "canonical"


# ─────────────────────────────────────────────────────────────────────────────
# STTEngine Protocol
# ─────────────────────────────────────────────────────────────────────────────

class TestSTTEngineProtocol:
    def test_runtime_checkable_positive(self):
        class Good:
            def transcribe_file(self, audio_file, **kwargs):
                return {}
        assert isinstance(Good(), STTEngine)

    def test_runtime_checkable_negative(self):
        class Bad:
            def something_else(self):
                return None
        assert not isinstance(Bad(), STTEngine)

    @pytest.mark.parametrize("module_path, cls_name", [
        ("scripts.models.model_google_stt", "GoogleSTTModel"),
        ("scripts.models.model_scribe", "ScribeSTTModel"),
        ("scripts.models.model_sensevoice", "SenseVoiceModel"),
        ("scripts.models.model_gemini", "GeminiModel"),
    ])
    def test_existing_engines_have_transcribe_file(self, module_path, cls_name):
        """既有引擎類別結構上符合契約（不實例化重模型）。

        需真實引擎模組 —— 缺對應 SDK 的環境會 skip（同既有 db_manager skip 慣例）。
        """
        mod = pytest.importorskip(module_path)
        cls = getattr(mod, cls_name)
        assert callable(getattr(cls, "transcribe_file", None))

    def test_whisper_model_conforms(self):
        assert isinstance(WhisperModel(), STTEngine)


# ─────────────────────────────────────────────────────────────────────────────
# create_engine 工廠
# ─────────────────────────────────────────────────────────────────────────────

class TestFactory:
    def test_unknown_name_raises(self):
        with pytest.raises(ValueError):
            create_engine("nope")

    def test_whisper_route(self):
        eng = create_engine("whisper", model_size="medium", language="zh")
        assert isinstance(eng, WhisperModel)
        assert eng.model_size == "medium"

    def test_scribe_route_passes_opts(self, monkeypatch):
        cls = _inject_fake_engine(monkeypatch, "scripts.models.model_scribe", "ScribeSTTModel")
        create_engine("scribe", language_code="zh", diarize=False)
        cls.assert_called_once_with(language_code="zh", diarize=False)

    def test_gemini_route_passes_opts(self, monkeypatch):
        cls = _inject_fake_engine(monkeypatch, "scripts.models.model_gemini", "GeminiModel")
        create_engine("gemini", api_key="k", model="gemini-2.5-flash")
        cls.assert_called_once_with(api_key="k", model="gemini-2.5-flash")

    def test_google_alias(self, monkeypatch):
        cls = _inject_fake_engine(monkeypatch, "scripts.models.model_google_stt", "GoogleSTTModel")
        create_engine("chirp3", project_id="p")
        cls.assert_called_once_with(project_id="p")


# ─────────────────────────────────────────────────────────────────────────────
# WhisperModel.transcribe_file
# ─────────────────────────────────────────────────────────────────────────────

class TestWhisperModel:
    def test_returns_sttresult(self, monkeypatch):
        fake = {"transcript": "你好", "segments": [{"start": 0, "end": 1, "text": "你好"}]}
        mod = types.ModuleType("scripts.models.model_whisper")
        mod.transcribe_with_whisper = Mock(return_value=fake)
        monkeypatch.setitem(sys.modules, "scripts.models.model_whisper", mod)

        r = WhisperModel().transcribe_file("a.wav")
        assert isinstance(r, STTResult)
        assert r.transcript == "你好"
        assert r.segments == fake["segments"]
        # 取 dict 形式（return_segments=True）
        _, kwargs = mod.transcribe_with_whisper.call_args
        assert kwargs.get("return_segments") is True
