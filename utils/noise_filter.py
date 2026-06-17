#!/usr/bin/env python3
"""
DeepFilterNet 背景噪音過濾模組
使用 deepfilternet 0.5.x 對音訊進行即時降噪處理。

相容性說明：
    deepfilternet 0.5.x 的 df/io.py 依賴 torchaudio.backend.common.AudioMetaData，
    此類別在 torchaudio 2.x 已被移除。本模組在匯入前自動注入相容 shim。
"""

import logging
import sys
import types
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── torchaudio 相容 shim（需在 import df 之前執行）──────────────────────────────
def _inject_torchaudio_shim():
    """
    為 torchaudio 2.x 注入 backend.common.AudioMetaData 相容層。
    deepfilternet 0.5.x 的 df/io.py 需要此類別，但 torchaudio 2.x 已移除它。
    """
    if "torchaudio.backend.common" in sys.modules:
        return  # 已存在，不重複注入

    class AudioMetaData:
        """torchaudio.backend.common.AudioMetaData 相容替代類別。"""
        def __init__(self, sample_rate: int, num_frames: int, num_channels: int,
                     bits_per_sample: int, encoding: str):
            self.sample_rate = sample_rate
            self.num_frames = num_frames
            self.num_channels = num_channels
            self.bits_per_sample = bits_per_sample
            self.encoding = encoding

        def __repr__(self):
            return (
                f"AudioMetaData(sample_rate={self.sample_rate}, "
                f"num_frames={self.num_frames}, "
                f"num_channels={self.num_channels})"
            )

    # 確保 torchaudio.backend 存在（可能已有其他內容）
    if "torchaudio.backend" not in sys.modules:
        backend_mod = types.ModuleType("torchaudio.backend")
        sys.modules["torchaudio.backend"] = backend_mod

    common_mod = types.ModuleType("torchaudio.backend.common")
    common_mod.AudioMetaData = AudioMetaData
    sys.modules["torchaudio.backend.common"] = common_mod

    # 同時掛到 torchaudio.backend 屬性上（避免 from torchaudio import backend 後存取失敗）
    backend = sys.modules["torchaudio.backend"]
    backend.common = common_mod


# 模型單例
_df_state = None    # df.enhance.init_df() 返回的 (model, df_state, _)
_df_model = None
_df_lock = None
_df_available = None  # None = 未嘗試；True/False = 已知狀態


def _get_lock():
    global _df_lock
    if _df_lock is None:
        import threading
        _df_lock = threading.Lock()
    return _df_lock


def _load_df_model() -> bool:
    """
    載入 DeepFilterNet 模型（單例，執行緒安全）。

    Returns:
        True = 成功；False = 不可用
    """
    global _df_state, _df_model, _df_available

    if _df_available is not None:
        return _df_available

    with _get_lock():
        if _df_available is not None:
            return _df_available

        try:
            # 注入相容 shim
            _inject_torchaudio_shim()

            from df.enhance import init_df
            _df_model, _df_state, _ = init_df()
            _df_available = True
            logger.info("✅ DeepFilterNet 模型載入完成")

        except ImportError as e:
            # 套件未安裝 → 不永久快取，下次再試（安裝後不需重啟）
            _df_available = None
            logger.warning(f"⚠️  DeepFilterNet 未安裝（{e}），可執行 pip install deepfilternet 後重試")

        except Exception as e:
            # 套件存在但模型載入失敗 → 永久快取 False（避免反覆嘗試耗時）
            _df_available = False
            logger.warning(
                f"⚠️  DeepFilterNet 模型載入失敗，降噪功能將被停用：{e}"
            )

    return _df_available


def is_available() -> bool:
    """回傳 DeepFilterNet 是否可用。"""
    return _load_df_model()


def denoise_audio(
    audio_np: np.ndarray,
    sample_rate: int = 16000,
) -> np.ndarray:
    """
    對輸入音訊進行 DeepFilterNet 降噪處理。

    Args:
        audio_np:    float32 ndarray，值域 [-1.0, 1.0]，shape [N] 或 [C, N]
        sample_rate: 採樣率（Hz）；DeepFilterNet 預設使用 48kHz，
                     若與模型採樣率不符會自動重採樣

    Returns:
        降噪後的 float32 ndarray，shape 與輸入相同（[N] 或 [C, N]）。
        若模型不可用，原樣返回輸入（不中斷服務）。
    """
    if not _load_df_model():
        return audio_np

    try:
        import torch
        import torchaudio
        from df.enhance import enhance

        original_shape = audio_np.shape
        is_1d = (audio_np.ndim == 1)

        # 轉為 [C, N] tensor（DeepFilterNet 要求 2D）
        if is_1d:
            tensor = torch.from_numpy(audio_np).unsqueeze(0)  # [1, N]
        else:
            tensor = torch.from_numpy(audio_np)

        # DeepFilterNet 模型採樣率
        model_sr = _df_state.sr()

        # 若採樣率不符，先重採樣到模型採樣率
        if sample_rate != model_sr:
            tensor = torchaudio.functional.resample(tensor, sample_rate, model_sr)

        # 降噪
        enhanced = enhance(_df_model, _df_state, tensor)  # returns [C, N] tensor

        # 若採樣率不符，重採樣回原始採樣率
        if sample_rate != model_sr:
            enhanced = torchaudio.functional.resample(enhanced, model_sr, sample_rate)

        result = enhanced.numpy()

        # 還原原始 shape
        if is_1d:
            result = result.squeeze(0)

        return result.astype(np.float32)

    except Exception as e:
        logger.warning(f"降噪處理失敗，返回原始音訊：{e}")
        return audio_np


def denoise_pcm_bytes(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
) -> bytes:
    """
    對 PCM 16-bit bytes 進行降噪，返回同格式的 bytes。

    方便直接嵌入現有以 bytes 傳遞音訊的流程。

    Args:
        pcm_bytes:   PCM 16-bit little-endian 原始音訊資料
        sample_rate: 採樣率（Hz）

    Returns:
        降噪後的 PCM 16-bit bytes，長度可能略有不同（重採樣邊界）
    """
    if not pcm_bytes:
        return pcm_bytes

    if not _load_df_model():
        return pcm_bytes

    try:
        # int16 → float32
        audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0

        # 降噪
        denoised = denoise_audio(audio_float, sample_rate=sample_rate)

        # float32 → int16 → bytes（clip 防止溢位）
        denoised_clipped = np.clip(denoised, -1.0, 1.0)
        output_int16 = (denoised_clipped * 32767).astype(np.int16)
        return output_int16.tobytes()

    except Exception as e:
        logger.warning(f"denoise_pcm_bytes 失敗，返回原始資料：{e}")
        return pcm_bytes


def denoise_wav_file(
    input_wav: str,
    output_wav: Optional[str] = None,
    sample_rate: int = 16000,
) -> Tuple[str, bool]:
    """
    對 WAV 檔案進行降噪處理，回寫到相同或指定路徑。

    Args:
        input_wav:  輸入 WAV 檔案路徑
        output_wav: 輸出 WAV 檔案路徑；若為 None，則覆寫原始檔案
        sample_rate: 期望採樣率（需與 WAV 實際相符）

    Returns:
        (output_path, success) — success=False 時 output_path = input_wav（原始未修改）
    """
    if output_wav is None:
        output_wav = input_wav

    if not _load_df_model():
        return input_wav, False

    try:
        import torchaudio
        from df.enhance import enhance

        waveform, sr = torchaudio.load(input_wav)  # [C, N], float32

        # 若採樣率不符，重採樣到模型採樣率
        model_sr = _df_state.sr()
        if sr != model_sr:
            waveform = torchaudio.functional.resample(waveform, sr, model_sr)

        enhanced = enhance(_df_model, _df_state, waveform)  # [C, N]

        # 重採樣回原始採樣率
        if sr != model_sr:
            enhanced = torchaudio.functional.resample(enhanced, model_sr, sr)

        torchaudio.save(output_wav, enhanced, sr)
        return output_wav, True

    except Exception as e:
        logger.warning(f"denoise_wav_file 失敗（{input_wav}）：{e}")
        return input_wav, False
