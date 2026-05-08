"""Tests for utils/audio_duration.py — wav 檔 → 秒數純函數。"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from utils.audio_duration import audio_seconds, AudioDurationError


def _write_silent_wav(path: Path, duration_sec: float, sample_rate: int = 16000) -> None:
    """產生指定秒數的靜音 wav（mono, 16-bit）給 test 用。"""
    n_samples = int(duration_sec * sample_rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_samples)


class TestAudioSeconds:
    def test_one_second_wav(self, tmp_path):
        wav = tmp_path / "1sec.wav"
        _write_silent_wav(wav, 1.0)
        assert abs(audio_seconds(wav) - 1.0) < 0.01

    def test_3_5_seconds_wav(self, tmp_path):
        wav = tmp_path / "3.5sec.wav"
        _write_silent_wav(wav, 3.5)
        assert abs(audio_seconds(wav) - 3.5) < 0.01

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(AudioDurationError, match="not found"):
            audio_seconds(tmp_path / "nonexistent.wav")

    def test_non_wav_file_raises(self, tmp_path):
        f = tmp_path / "fake.wav"
        f.write_bytes(b"not a wav file")
        with pytest.raises(AudioDurationError):
            audio_seconds(f)
