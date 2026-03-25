#!/usr/bin/env python3
"""
Silero VAD (Voice Activity Detection) 模組
使用 silero-vad v6.x 套件偵測音訊片段中是否包含語音。
"""

import logging
from typing import List, Optional

import numpy as np
import torch

logger = logging.getLogger(__name__)

# ── 模型單例 ────────────────────────────────────────────────────────────────────
_vad_model = None
_vad_lock = None


def is_available() -> bool:
    """回傳 Silero VAD 是否可用（silero-vad 套件已安裝且可載入）。"""
    try:
        from silero_vad import load_silero_vad  # noqa: F401
        return True
    except Exception:
        return False


def _get_lock():
    """延遲初始化 threading.Lock（避免 import 時副作用）。"""
    global _vad_lock
    if _vad_lock is None:
        import threading
        _vad_lock = threading.Lock()
    return _vad_lock


def _load_model():
    """載入 Silero VAD 模型（單例，執行緒安全）。"""
    global _vad_model
    if _vad_model is not None:
        return _vad_model

    with _get_lock():
        if _vad_model is not None:
            return _vad_model
        try:
            from silero_vad import load_silero_vad
            _vad_model = load_silero_vad()
            _vad_model.eval()
            logger.info("✅ Silero VAD 模型載入完成")
        except Exception as e:
            logger.error(f"❌ Silero VAD 模型載入失敗：{e}")
            _vad_model = None
    return _vad_model


def _bytes_to_float_tensor(
    audio_bytes: bytes,
    sample_rate: int = 16000,
) -> Optional[torch.Tensor]:
    """
    將 PCM 16-bit bytes 轉換為 float32 tensor。

    Args:
        audio_bytes: PCM 16-bit little-endian 原始音訊資料
        sample_rate:  採樣率（Hz），目前僅 8000 / 16000 被 Silero VAD 支援

    Returns:
        shape [N] 的 float32 tensor，或 None（輸入為空時）
    """
    if not audio_bytes:
        return None
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    return torch.from_numpy(audio_np)


def is_speech(
    audio_input,
    sample_rate: int = 16000,
    threshold: float = 0.5,
) -> bool:
    """
    判斷音訊片段是否包含語音。

    Args:
        audio_input: 以下任一格式皆可接受：
                     - bytes（PCM 16-bit little-endian）
                     - np.ndarray（float32 或 int16）
                     - torch.Tensor（float32，shape [N]）
        sample_rate:  採樣率（Hz），需為 8000 或 16000
        threshold:    語音偵測機率門檻（0~1），預設 0.5

    Returns:
        True = 有語音；False = 靜音或偵測失敗
    """
    model = _load_model()
    if model is None:
        return True  # 模型不可用時，預設放行（避免阻斷 STT）

    try:
        # 轉換輸入格式
        if isinstance(audio_input, bytes):
            tensor = _bytes_to_float_tensor(audio_input, sample_rate)
        elif isinstance(audio_input, np.ndarray):
            arr = audio_input
            if arr.dtype == np.int16:
                arr = arr.astype(np.float32) / 32768.0
            tensor = torch.from_numpy(arr.astype(np.float32))
        elif isinstance(audio_input, torch.Tensor):
            tensor = audio_input.float()
        else:
            logger.warning(f"is_speech: 不支援的輸入型別 {type(audio_input)}")
            return True

        if tensor is None or len(tensor) == 0:
            return False

        # Silero VAD 需要至少 256 個樣本（16kHz 下約 16ms）
        if len(tensor) < 256:
            return False

        with torch.no_grad():
            prob = model(tensor, sample_rate).item()

        return prob >= threshold

    except Exception as e:
        logger.warning(f"VAD 偵測例外，預設放行：{e}")
        return True


def filter_speech_chunks(
    audio_chunks: List,
    sample_rate: int = 16000,
    threshold: float = 0.5,
) -> List:
    """
    從音訊片段列表中篩選出含有語音的片段。

    Args:
        audio_chunks: 音訊片段列表，每個元素可為 bytes / np.ndarray / torch.Tensor
        sample_rate:  採樣率（Hz）
        threshold:    語音偵測機率門檻，預設 0.5

    Returns:
        只保留有語音的片段，順序不變
    """
    if not audio_chunks:
        return []

    result = []
    for chunk in audio_chunks:
        if is_speech(chunk, sample_rate=sample_rate, threshold=threshold):
            result.append(chunk)

    kept = len(result)
    total = len(audio_chunks)
    if total > 0:
        logger.debug(f"VAD filter: {kept}/{total} 個片段含語音（threshold={threshold}）")

    return result


def has_speech_in_wav(wav_path: str, threshold: float = 0.5) -> bool:
    """
    判斷 WAV 檔案中是否含有語音（整體判斷）。

    用於批次模式：將整段 WAV 讀入並判斷是否應送去 STT。

    Args:
        wav_path:  WAV 檔案路徑
        threshold: 語音偵測機率門檻，預設 0.5

    Returns:
        True = 有語音；False = 完全靜音
    """
    try:
        import torchaudio
        waveform, sr = torchaudio.load(wav_path)
        # 轉換為單聲道
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        tensor = waveform.squeeze(0)  # shape [N]

        # 若採樣率與目標不符，重採樣
        if sr != sample_rate_target:
            pass  # Silero VAD 支援的採樣率只有 8000/16000，直接使用原本的 sr

        return is_speech(tensor, sample_rate=sr, threshold=threshold)

    except Exception as e:
        logger.warning(f"has_speech_in_wav 讀檔失敗，預設放行：{e}")
        return True


# 允許直接指定採樣率的版本
def has_speech_in_wav_sr(
    wav_path: str,
    sample_rate: int = 16000,
    threshold: float = 0.5,
) -> bool:
    """
    判斷 WAV 檔案中是否含有語音，明確指定採樣率版本。

    Args:
        wav_path:    WAV 檔案路徑
        sample_rate: 期望的採樣率（必須與 WAV 實際相符，或由呼叫端負責重採樣）
        threshold:   語音偵測機率門檻

    Returns:
        True = 有語音；False = 完全靜音
    """
    try:
        import torchaudio
        waveform, sr = torchaudio.load(wav_path)
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        tensor = waveform.squeeze(0)
        return is_speech(tensor, sample_rate=sr, threshold=threshold)
    except Exception as e:
        logger.warning(f"has_speech_in_wav_sr 讀檔失敗，預設放行：{e}")
        return True


def get_speech_ratio(
    audio_input,
    sample_rate: int = 16000,
    window_ms: int = 250,
    threshold: float = 0.5,
) -> float:
    """
    計算音訊中語音所佔的時間比例（0.0~1.0）。

    將音訊切成固定視窗逐段偵測，回傳語音視窗比例。
    適合用於判斷長片段中語音密度。

    Args:
        audio_input: PCM bytes 或 np.ndarray（float32/int16）
        sample_rate: 採樣率（Hz）
        window_ms:   每個判斷視窗的長度（毫秒），預設 250ms
        threshold:   語音偵測機率門檻

    Returns:
        語音佔比（0.0 = 全靜音；1.0 = 全語音）
    """
    if isinstance(audio_input, bytes):
        audio_np = np.frombuffer(audio_input, dtype=np.int16).astype(np.float32) / 32768.0
    elif isinstance(audio_input, np.ndarray):
        audio_np = audio_input.astype(np.float32)
        if audio_np.max() > 1.0 or audio_np.min() < -1.0:
            audio_np = audio_np / 32768.0
    else:
        return 1.0  # 無法判斷時預設全語音

    window_samples = int(sample_rate * window_ms / 1000)
    if len(audio_np) < window_samples:
        return float(is_speech(audio_np, sample_rate=sample_rate, threshold=threshold))

    windows = [
        audio_np[i : i + window_samples]
        for i in range(0, len(audio_np) - window_samples + 1, window_samples)
    ]

    if not windows:
        return 1.0

    speech_count = sum(
        1 for w in windows
        if is_speech(w, sample_rate=sample_rate, threshold=threshold)
    )
    return speech_count / len(windows)
