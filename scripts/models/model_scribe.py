#!/usr/bin/env python3
"""
ElevenLabs Scribe 語音辨識模型包裝器
版本: 1.0 (2026-03-20)

介面與 GoogleSTTModel.transcribe_file() 完全相容：
    transcribe_file(audio_file) → {"transcript": str, "confidence": float}

API 文件：https://elevenlabs.io/docs/api-reference/speech-to-text

使用方式：
    from scripts.models.model_scribe import ScribeSTTModel
    model = ScribeSTTModel()
    result = model.transcribe_file("audio.wav")
    print(result["transcript"])

環境變數：
    ELEVENLABS_API_KEY=sk_...   （必填，寫在 .env）
"""

import os
from pathlib import Path

import httpx


class ScribeSTTModel:
    """
    ElevenLabs Scribe v1 語音辨識模型包裝器。

    與 GoogleSTTModel 相同介面，可直接替換使用：
        result = model.transcribe_file(wav_path)
        transcript = result["transcript"]
        confidence = result["confidence"]

    Scribe 支援格式：WAV / MP3 / M4A / FLAC / OGG / WEBM
    Scribe 語言：自動偵測，或指定 language_code 提示（如 "zh"）
    """

    API_URL  = "https://api.elevenlabs.io/v1/speech-to-text"
    MODEL_ID = "scribe_v1"

    def __init__(
        self,
        language_code: str  = "zh",    # "zh" 提示偏中文；留空("")讓 Scribe 全自動偵測
        diarize:       bool = False,    # True = 啟用講者辨識（結果含 speaker_id）
        timeout:       float = 60.0,   # HTTP 請求逾時秒數
    ):
        self.api_key      = os.getenv("ELEVENLABS_API_KEY", "").strip()
        self.language_code = language_code
        self.diarize      = diarize
        self.timeout      = timeout

        if not self.api_key:
            raise ValueError(
                "ELEVENLABS_API_KEY 未設定，請在 .env 加入：\n"
                "ELEVENLABS_API_KEY=sk_..."
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 主要介面
    # ─────────────────────────────────────────────────────────────────────────

    def transcribe_file(self, audio_file) -> dict:
        """
        辨識音檔，回傳格式與 GoogleSTTModel 完全相容。

        Args:
            audio_file: 音檔路徑（str 或 Path），建議使用 16kHz mono WAV

        Returns:
            成功：{"transcript": str, "confidence": float}
            失敗：{"transcript": "", "confidence": 0.0, "error": str}
        """
        audio_path = Path(audio_file)

        try:
            audio_bytes = audio_path.read_bytes()

            # ── multipart/form-data 請求欄位 ──────────────────────────────────
            form_data: dict = {
                "model_id":               self.MODEL_ID,
                "diarize":                "true" if self.diarize else "false",
                "timestamps_granularity": "none",   # 不需要字詞時間戳，加快回應
            }
            if self.language_code:
                form_data["language_code"] = self.language_code

            # ── 送出 HTTP POST ────────────────────────────────────────────────
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    self.API_URL,
                    headers={"xi-api-key": self.api_key},
                    data=form_data,
                    files={"file": (audio_path.name, audio_bytes, "audio/wav")},
                )

            # ── 解析回應 ─────────────────────────────────────────────────────
            if resp.status_code != 200:
                return {
                    "transcript": "",
                    "confidence": 0.0,
                    "error": f"HTTP {resp.status_code}: {resp.text[:300]}",
                }

            data = resp.json()
            return {
                "transcript": (data.get("text") or "").strip(),
                # language_confidence：Scribe 對語言偵測的信心值（0.0–1.0）
                # 注意：與 Google chirp_3 的 word confidence 定義不同，僅供參考
                "confidence": float(data.get("language_confidence") or 0.0),
            }

        except httpx.TimeoutException:
            return {
                "transcript": "",
                "confidence": 0.0,
                "error": f"Scribe API 請求逾時（>{self.timeout}s）",
            }
        except Exception as exc:
            return {
                "transcript": "",
                "confidence": 0.0,
                "error": str(exc),
            }
