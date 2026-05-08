"""Wav 檔 → 秒數純函數（用 stdlib wave 模組，零新依賴）。

只支援 PCM wav 檔。其他格式（mp3、flac 等）若未來需要，
改用 librosa 或 soundfile（已在 requirements.txt 裡）。
"""

from __future__ import annotations

import wave
from pathlib import Path


class AudioDurationError(ValueError):
    """讀 wav 檔失敗或格式不對。"""


def audio_seconds(wav_path: Path | str) -> float:
    """讀 wav header 算秒數。誤差 < 1 frame（幾乎等同精準）。

    Args:
        wav_path: wav 檔路徑

    Returns:
        音訊秒數（float）

    Raises:
        AudioDurationError: 檔不存在或不是合法 PCM wav
    """
    p = Path(wav_path)
    if not p.exists():
        raise AudioDurationError(f"wav file not found: {p}")
    try:
        with wave.open(str(p), "rb") as w:
            n_frames = w.getnframes()
            framerate = w.getframerate()
            if framerate <= 0:
                raise AudioDurationError(f"invalid framerate {framerate} in {p}")
            return n_frames / framerate
    except wave.Error as e:
        raise AudioDurationError(f"not a valid PCM wav: {p} ({e})") from e
