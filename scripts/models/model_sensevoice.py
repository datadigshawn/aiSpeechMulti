"""
SenseVoiceSmall 語音辨識模組
引擎：FunASR SenseVoiceSmall（阿里達摩院）
特性：非自回歸架構、中文辨識優異、含情緒辨識與事件偵測、RTF ≈ 0.1x
適用：臺中捷運 OCC 機密通聯內容辨識（離線模式）

安裝：
    pip install funasr>=1.1.0 modelscope onnxruntime

使用：
    from scripts.models.model_sensevoice import SenseVoiceModel
    model = SenseVoiceModel()
    result = model.transcribe_file("audio.wav")
    print(result["transcript"], result["emotion_label"])
"""

import re
import csv
import os
from pathlib import Path
from typing import Optional
from collections import Counter


# ── 情緒標籤定義 ───────────────────────────────────────────────────────────────
EMOTION_MAP = {
    "<|HAPPY|>":     "😊 開心",
    "<|SAD|>":       "😢 悲傷",
    "<|ANGRY|>":     "😠 憤怒",
    "<|NEUTRAL|>":   "😐 中性",
    "<|FEARFUL|>":   "😨 恐懼",
    "<|DISGUSTED|>": "🤢 厭惡",
    "<|SURPRISED|>": "😲 驚訝",
}

# ── 音訊事件標籤定義 ───────────────────────────────────────────────────────────
EVENT_MAP = {
    "<|BGM|>":       "🎵 背景音樂",
    "<|Speech|>":    "🗣️ 語音",
    "<|Applause|>":  "👏 掌聲",
    "<|Laughter|>":  "😄 笑聲",
    "<|Cry|>":       "😭 哭聲",
    "<|Sneeze|>":    "🤧 噴嚏",
    "<|Breathe|>":   "💨 呼吸",
    "<|Cough|>":     "😷 咳嗽",
}

# ── 鐵道專有詞彙（熱詞） ───────────────────────────────────────────────────────
RAILWAY_HOTWORDS = (
    "臺中捷運 行控中心 北屯總站 高鐵臺中站 市政府站 "
    "文心森林公園站 大慶站 豐樂公園站 松竹站 四維國小站 文心中清站 "
    "CBTC ZC CLC CBI ATP ATO ATS "
    "轉轍器 道岔 號誌機 閉塞區間 聯鎖 "
    "月台門 緊急停車按鈕 列車自動防護 列車自動運轉 "
    "OCC 調度員 站務員 司機員 "
    "正線 副正線 橫渡線 袋型軌 駐車軌 "
    "第三軌 牽引電力 APS SCADA "
    "收班 發班 夜間作業 試車 清車 巡軌"
)


def _load_hotwords_from_csv(csv_path: Path) -> str:
    """從 master_vocabulary.csv 補充熱詞"""
    if not csv_path or not csv_path.exists():
        return ""
    try:
        terms = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                term = (row.get("term") or "").strip()
                if term:
                    terms.append(term)
        return " ".join(terms)
    except Exception:
        return ""


def parse_sensevoice_tags(raw_text: str) -> dict:
    """
    解析 SenseVoiceSmall 輸出中的情緒/事件標籤

    Returns:
        {
          "text":          "純文字（移除所有標籤後）",
          "emotion":       "NEUTRAL",      # 情緒原始代碼（可能為 None）
          "emotion_label": "😐 中性",      # 情緒顯示標籤（可能為 None）
          "events":        ["🗣️ 語音"],    # 偵測到的事件標籤列表
        }
    """
    text = raw_text
    emotion_raw = None
    emotion_label = None
    events = []

    for tag, label in EMOTION_MAP.items():
        if tag in text:
            emotion_raw = tag.strip("<>|")
            emotion_label = label
            text = text.replace(tag, "")

    for tag, label in EVENT_MAP.items():
        if tag in text:
            events.append(label)
            text = text.replace(tag, "")

    # 清理剩餘未識別的 <|...|> 標籤
    text = re.sub(r"<\|[^|]*\|>", "", text).strip()

    return {
        "text":          text,
        "emotion":       emotion_raw,
        "emotion_label": emotion_label,
        "events":        events,
    }


class SenseVoiceModel:
    """
    SenseVoiceSmall 語音辨識模型封裝

    統一介面：transcribe_file(audio_path) → dict
    輸出格式與 GoogleSTTModel / GeminiModel 相容（均含 transcript、confidence 欄位）
    額外提供：emotion、emotion_label、events、segments
    """

    def __init__(
        self,
        model_name: str = "iic/SenseVoiceSmall",
        language: str = "zh",
        device: str = "cpu",
        vocabulary_csv: Optional[str] = None,
        use_vad: bool = True,
    ):
        """
        Args:
            model_name:      FunASR 模型名稱（預設 iic/SenseVoiceSmall）
            language:        辨識語言（zh/en/ja/yue/ko/auto）
            device:          推論裝置（cpu / cuda）
            vocabulary_csv:  master_vocabulary.csv 路徑，用於補充熱詞
            use_vad:         是否啟用 FunASR 內建 VAD（即時模式可關閉，避免下載 fsmn-vad）
        """
        self.model_name     = model_name
        self.language       = language
        self.device         = device
        self.use_vad        = use_vad
        self._model         = None

        vocab_path = Path(vocabulary_csv) if vocabulary_csv else None
        self._extra_hotwords = _load_hotwords_from_csv(vocab_path)

    def _ensure_loaded(self):
        """懶載入模型（首次呼叫時才佔用記憶體）"""
        if self._model is not None:
            return
        try:
            from funasr import AutoModel

            # 優先使用 HuggingFace 來源（ModelScope .cn 端點不穩定）
            # model_name 映射：iic/SenseVoiceSmall → FunAudioLLM/SenseVoiceSmall
            hf_name = self.model_name.replace("iic/", "FunAudioLLM/")

            # VAD 配置：即時模式（3 秒 chunk）不需要內建 VAD，避免下載 fsmn-vad
            vad_kwargs = {}
            if self.use_vad:
                vad_kwargs["vad_model"] = "fsmn-vad"
                vad_kwargs["vad_kwargs"] = {"max_single_segment_time": 30000}

            # FunASR >= 1.3 內建 SenseVoiceSmall，不需要 trust_remote_code
            # 使用 HuggingFace 來源下載權重（ModelScope .cn 端點不穩定）
            try:
                self._model = AutoModel(
                    model=hf_name,
                    hub="hf",
                    trust_remote_code=False,
                    device=self.device,
                    disable_update=True,
                    **vad_kwargs,
                )
            except Exception as hf_err:
                # HuggingFace 失敗時回退 ModelScope
                import logging
                logging.getLogger(__name__).warning(
                    f"HuggingFace 載入失敗（{hf_err}），回退 ModelScope..."
                )
                self._model = AutoModel(
                    model=self.model_name,
                    trust_remote_code=False,
                    device=self.device,
                    disable_update=True,
                    **vad_kwargs,
                )

        except ImportError:
            raise ImportError(
                "找不到 funasr 套件，請安裝：\n"
                "  pip install funasr>=1.1.0 modelscope onnxruntime"
            )

    def transcribe_file(
        self,
        audio_path: str,
        language: Optional[str] = None,
        extra_hotwords: str = "",
        **kwargs,
    ) -> dict:
        """
        辨識單一音檔

        Args:
            audio_path:      音檔路徑（支援 wav/mp3/m4a/flac/ogg）
            language:        語言代碼；None 時使用初始化設定
            extra_hotwords:  額外熱詞（空格或頓號分隔）

        Returns:
            {
                "transcript":     "辨識文字（已合併所有片段）",
                "confidence":     0.95,
                "emotion":        "NEUTRAL",      # 整體主要情緒代碼（可能為 None）
                "emotion_label":  "😐 中性",      # 整體主要情緒標籤（可能為 None）
                "events":         ["🗣️ 語音"],    # 所有偵測到的事件（去重）
                "no_speech_prob": 0.0,
                "segments":       [              # 逐段詳細結果
                    {
                        "start":         0.0,
                        "end":           3.5,
                        "text":          "文字",
                        "no_speech_prob": 0.0,
                        "emotion":       "NEUTRAL",
                        "emotion_label": "😐 中性",
                        "events":        ["🗣️ 語音"],
                    },
                    ...
                ],
            }
        """
        self._ensure_loaded()

        lang = language or self.language
        lang_map = {
            "zh": "zh", "en": "en", "ja": "ja",
            "yue": "yue", "ko": "ko", "auto": "auto",
        }
        sv_lang = lang_map.get(lang, "auto")

        # 合併熱詞
        hw_parts = [RAILWAY_HOTWORDS]
        if self._extra_hotwords:
            hw_parts.append(self._extra_hotwords)
        if extra_hotwords:
            hw_parts.append(extra_hotwords.replace("、", " "))
        hotwords = " ".join(hw_parts)

        raw_results = self._model.generate(
            input=audio_path,
            cache={},
            language=sv_lang,
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
            hotword=hotwords,
        )

        segments    = []
        all_texts   = []
        all_emotions = []
        all_events  = []

        if raw_results:
            for item in raw_results:
                raw_text = item.get("text", "")
                parsed   = parse_sensevoice_tags(raw_text)

                if not parsed["text"]:
                    continue

                timestamp = item.get("timestamp", [])
                if timestamp and len(timestamp) >= 1:
                    start = (
                        timestamp[0][0] / 1000.0
                        if isinstance(timestamp[0], (list, tuple))
                        else 0.0
                    )
                    end = (
                        timestamp[-1][-1] / 1000.0
                        if isinstance(timestamp[-1], (list, tuple))
                        else 0.0
                    )
                else:
                    start = end = 0.0

                segments.append({
                    "start":          round(start, 2),
                    "end":            round(end, 2),
                    "text":           parsed["text"],
                    "no_speech_prob": 0.0,
                    "emotion":        parsed["emotion"],
                    "emotion_label":  parsed["emotion_label"],
                    "events":         parsed["events"],
                })
                all_texts.append(parsed["text"])
                if parsed["emotion"]:
                    all_emotions.append(parsed["emotion"])
                all_events.extend(parsed["events"])

        transcript = " ".join(all_texts)

        # 整體情緒：選最常見者
        dominant_emotion = None
        dominant_emotion_label = None
        if all_emotions:
            dominant_raw = Counter(all_emotions).most_common(1)[0][0]
            dominant_emotion = dominant_raw
            tag_key = f"<|{dominant_raw}|>"
            dominant_emotion_label = EMOTION_MAP.get(tag_key)

        return {
            "transcript":     transcript,
            "confidence":     0.95,
            "emotion":        dominant_emotion,
            "emotion_label":  dominant_emotion_label,
            "events":         list(dict.fromkeys(all_events)),  # 去重保序
            "no_speech_prob": 0.0,
            "segments":       segments,
        }
