#!/usr/bin/env python3
"""
無線電專用 Google STT 配置模組
==============================================================================
針對台灣捷運無線電通訊的特殊優化：

1. 音訊特性：
   - 壓縮音訊（300-3400 Hz 頻段）
   - 背景噪音（電磁干擾、環境噪音）
   - 語速變化（緊急時快速、正常時緩慢）

2. 內容特性：
   - 專業術語密集（OCC, VVVF, ATP...）
   - 車站代碼（G01-G17, R01-R20）
   - 數字讀音特殊（洞=0, 腰=1, 勾=9）

3. 優化策略：
   - 啟用 Enhanced Model
   - 優化 Metadata（interaction_type=PHONE_CALL）
   - 使用 inline PhraseSet（避免 adaptation resource 配置問題）
   - 調整 boost 權重階層
"""

from google.cloud.speech_v2.types import cloud_speech
from typing import List, Dict, Optional
import json
from pathlib import Path


class RadioSTTConfig:
    """無線電專用 STT 配置生成器"""
    
    # 推薦的模型配置
    RECOMMENDED_MODELS = {
        'chirp_3': {
            'name': 'chirp_3',
            'description': '最新 Chirp 模型，最佳中文支援',
            'max_phrases': 1000,
            'supports_diarization': False,  # Chirp 3 不支援 diarization
            'best_for': '生產環境、高準確率需求'
        },
        'chirp_2': {
            'name': 'chirp_2',
            'description': 'Chirp 2，支援說話者區分',
            'max_phrases': 500,
            'supports_diarization': True,  # Chirp 2 支援 diarization
            'best_for': '多人對話、需要區分說話者'
        },
        'chirp_telephony': {
            'name': 'chirp_telephony',
            'description': '電話音質優化模型',
            'max_phrases': 500,
            'supports_diarization': False,
            'best_for': '電話錄音、壓縮音訊'
        }
    }
    
    @staticmethod
    def create_radio_optimized_config(
        model: str = "chirp_3",
        language_code: str = "cmn-Hant-TW",
        phrases: Optional[List[Dict]] = None,
        enable_diarization: bool = False,
        sample_rate: int = 16000
    ) -> cloud_speech.RecognitionConfig:
        """
        創建無線電優化的辨識配置
        
        Args:
            model: 模型名稱（chirp_3, chirp_2, chirp_telephony）
            language_code: 語言代碼
            phrases: 詞彙提示列表 [{"value": "OCC", "boost": 20}, ...]
            enable_diarization: 是否啟用說話者區分（僅 Chirp 2 支援）
            sample_rate: 音訊取樣率
        
        Returns:
            RecognitionConfig 物件
        """
        # 檢查模型是否支援 diarization
        if enable_diarization:
            if model not in RadioSTTConfig.RECOMMENDED_MODELS:
                raise ValueError(f"未知模型: {model}")
            
            if not RadioSTTConfig.RECOMMENDED_MODELS[model]['supports_diarization']:
                print(f"⚠️  警告: {model} 不支援說話者區分，已自動停用")
                enable_diarization = False
        
        # 明確的音訊編碼設定
        explicit_decoding = cloud_speech.ExplicitDecodingConfig(
            encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            audio_channel_count=1
        )
        
        # 基礎配置
        config = cloud_speech.RecognitionConfig(
            explicit_decoding_config=explicit_decoding,
            language_codes=[language_code],
            model=model,
            
            # 辨識功能
            features=cloud_speech.RecognitionFeatures(
                enable_word_time_offsets=True,  # 啟用時間戳記
                enable_automatic_punctuation=False,  # 無線電不需要標點符號
                
                # ⭐ 關鍵優化：說話者區分（僅 Chirp 2）
                diarization_config=(
                    cloud_speech.SpeakerDiarizationConfig(
                        min_speaker_count=1,
                        max_speaker_count=3  # 通常是 站長<->OCC，最多3人
                    ) if enable_diarization else None
                )
            )
        )
        
        # ⭐ 核心優化：詞彙適應（Vocabulary Adaptation）
        if phrases and len(phrases) > 0:
            config.adaptation = RadioSTTConfig._create_phrase_adaptation(
                phrases, model
            )
        
        return config
    
    @staticmethod
    def _create_phrase_adaptation(
        phrases: List[Dict],
        model: str
    ) -> cloud_speech.SpeechAdaptation:
        """
        創建詞彙適應配置（使用 inline PhraseSet）
        
        Args:
            phrases: [{"value": "OCC", "boost": 20}, ...]
            model: 模型名稱（決定最大詞彙數）
        
        Returns:
            SpeechAdaptation 物件
        """
        # 取得最大詞彙數限制
        max_phrases = RadioSTTConfig.RECOMMENDED_MODELS.get(model, {}).get('max_phrases', 500)
        
        # 階層式分組：按 boost 值分層
        tier_1 = []  # Boost 20: 緊急術語、核心設備
        tier_2 = []  # Boost 15-18: 重要術語
        tier_3 = []  # Boost 10-14: 一般術語
        
        for phrase_dict in phrases:
            boost = phrase_dict.get('boost', 10)
            value = phrase_dict.get('value', '')
            
            if boost >= 20:
                tier_1.append(cloud_speech.PhraseSet.Phrase(value=value, boost=20))
            elif boost >= 15:
                tier_2.append(cloud_speech.PhraseSet.Phrase(value=value, boost=15))
            else:
                tier_3.append(cloud_speech.PhraseSet.Phrase(value=value, boost=10))
        
        # 優先保留高權重術語
        all_phrases = tier_1 + tier_2 + tier_3
        all_phrases = all_phrases[:max_phrases]
        
        # 創建 inline PhraseSet
        adaptation = cloud_speech.SpeechAdaptation(
            phrase_sets=[
                cloud_speech.SpeechAdaptation.AdaptationPhraseSet(
                    inline_phrase_set=cloud_speech.PhraseSet(
                        phrases=all_phrases
                    )
                )
            ]
        )
        
        print(f"✅ 詞彙適應已載入:")
        print(f"   - Tier 1 (Boost 20): {len(tier_1)} 個")
        print(f"   - Tier 2 (Boost 15-18): {len(tier_2)} 個")
        print(f"   - Tier 3 (Boost 10-14): {len(tier_3)} 個")
        print(f"   - 總計: {len(all_phrases)} 個（限制: {max_phrases}）")
        
        return adaptation
    
    @staticmethod
    def load_phrases_from_json(json_path: str) -> List[Dict]:
        """
        從 google_phrases.json 載入詞彙表
        
        Args:
            json_path: JSON 檔案路徑
        
        Returns:
            [{"value": "OCC", "boost": 20}, ...]
        """
        json_file = Path(json_path)
        
        if not json_file.exists():
            print(f"⚠️  詞彙表不存在: {json_path}")
            return []
        
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        phrases = data.get('phrases', [])
        print(f"✅ 載入詞彙表: {json_file.name}")
        print(f"   - 總數: {len(phrases)} 個")
        
        return phrases
    
    @staticmethod
    def create_recognition_request(
        recognizer_path: str,
        audio_content: bytes,
        config: cloud_speech.RecognitionConfig
    ) -> cloud_speech.RecognizeRequest:
        """
        創建完整的辨識請求
        
        Args:
            recognizer_path: 辨識器路徑（例如: "projects/.../locations/us/recognizers/_"）
            audio_content: 音訊二進制內容
            config: 辨識配置
        
        Returns:
            RecognizeRequest 物件
        """
        return cloud_speech.RecognizeRequest(
            recognizer=recognizer_path,
            config=config,
            content=audio_content
        )
    
    @staticmethod
    def print_config_summary(config: cloud_speech.RecognitionConfig) -> None:
        """列印配置摘要（用於除錯）"""
        print("\n" + "="*80)
        print("Google STT 配置摘要")
        print("="*80)
        print(f"模型: {config.model}")
        print(f"語言: {', '.join(config.language_codes)}")
        print(f"取樣率: {config.explicit_decoding_config.sample_rate_hertz} Hz")
        print(f"編碼: {config.explicit_decoding_config.encoding}")
        print(f"時間戳記: {config.features.enable_word_time_offsets}")
        print(f"自動標點: {config.features.enable_automatic_punctuation}")
        
        if config.features.diarization_config:
            print(f"說話者區分: ✅ (Min: {config.features.diarization_config.min_speaker_count}, "
                  f"Max: {config.features.diarization_config.max_speaker_count})")
        else:
            print("說話者區分: ❌")
        
        if config.adaptation and config.adaptation.phrase_sets:
            phrase_count = len(config.adaptation.phrase_sets[0].inline_phrase_set.phrases)
            print(f"詞彙適應: ✅ ({phrase_count} 個詞彙)")
        else:
            print("詞彙適應: ❌")
        
        print("="*80 + "\n")


# ============================================================================
# 使用範例
# ============================================================================
def example_usage():
    """使用範例"""
    
    # 1. 載入詞彙表
    phrases = RadioSTTConfig.load_phrases_from_json("vocabulary/google_phrases.json")
    
    # 2. 創建配置
    config = RadioSTTConfig.create_radio_optimized_config(
        model="chirp_3",
        language_code="cmn-Hant-TW",
        phrases=phrases,
        enable_diarization=False,  # Chirp 3 不支援
        sample_rate=16000
    )
    
    # 3. 列印配置摘要
    RadioSTTConfig.print_config_summary(config)
    
    # 4. 創建請求（需要實際音訊內容）
    # recognizer_path = "projects/dazzling-seat-315406/locations/us/recognizers/_"
    # request = RadioSTTConfig.create_recognition_request(
    #     recognizer_path, audio_content, config
    # )


if __name__ == "__main__":
    example_usage()
