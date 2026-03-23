#!/usr/bin/env python3
"""
Google STT 配置管理器
版本: 1.0
用於管理不同模型的區域和端點配置
核心問題
1. Google Cloud 認證配置
2. 音訊格式自動轉換
3. Recognizer 路徑格式
4. 區域端點設定
5. 詞彙表整合
6. 配置管理器相依性

需要功能
- Chirp 3、Chirp Telephony 等模型配置
- 區域端點自動選擇
- 回退區域機制
- 功能支援檢查（串流、講者識別等
"""

import json
from pathlib import Path
from typing import Tuple, Optional

try:
    from .logger import get_logger
except ImportError:
    import logging
    def get_logger(name):
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)


class GoogleSTTConfigManager:
    """
    Google STT 配置管理器
    處理模型、區域、端點的最佳配置選擇
    """
    
    DEFAULT_CONFIG = {
        "models": {
            "chirp_3": {
                "name": "chirp_3",
                "display_name": "Chirp 3 (最新通用大模型)",
                "primary_region": "us",
                "fallback_regions": ["asia-northeast1", "northamerica-northeast1", "eu"],
                "supports_streaming": True,
                "supports_diarization": True,
                "max_phrases": 1000,
                "recommended_for": ["無線電通訊", "雜訊環境", "多語言混合"]
            },
            "chirp_telephony": {
                "name": "chirp_telephony",
                "display_name": "Chirp Telephony (電話/無線電優化)",
                "primary_region": "us",
                "fallback_regions": ["eu"],
                "supports_streaming": True,
                "supports_diarization": False,
                "max_phrases": 500,
                "recommended_for": ["8kHz低取樣率", "電話品質音訊", "無線電"]
            },
            "chirp_2": {
                "name": "chirp_2",
                "display_name": "Chirp 2",
                "primary_region": "asia-southeast1",
                "fallback_regions": ["asia-northeast1", "us-central1", "europe-west4"],
                "supports_streaming": True,
                "supports_diarization": False,
                "max_phrases": 500,
                "recommended_for": ["一般用途", "批次處理"]
            },
            "chirp": {
                "name": "chirp",
                "display_name": "Chirp (第一代)",
                "primary_region": "us",
                "fallback_regions": [],
                "supports_streaming": False,
                "supports_diarization": False,
                "max_phrases": 500,
                "recommended_for": ["批次處理", "歷史檔案"]
            },
            "long": {
                "name": "long",
                "display_name": "Long (長音檔優化)",
                "primary_region": "us",
                "fallback_regions": ["global", "eu", "europe-west4"],
                "supports_streaming": True,
                "supports_diarization": True,
                "max_phrases": 500,
                "recommended_for": ["會議錄音", "演講", "長時間錄音"]
            },
            "short": {
                "name": "short",
                "display_name": "Short (短語音優化)",
                "primary_region": "us",
                "fallback_regions": ["eu", "global"],
                "supports_streaming": True,
                "supports_diarization": False,
                "max_phrases": 500,
                "recommended_for": ["語音指令", "簡短對話", "低延遲需求"]
            },
            "telephony": {
                "supports_streaming": True,  # ← 新增
                "recommended_for": ["電話語音", "低取樣率", "8kHz音訊"],  # ← 新增
                "name": "telephony",
                "display_name": "telephony",
                "primary_region": "asia-southeast1",
                "fallback_regions": ["us", "eu", "asia-southeast1"],
                "supported_languages": ["cmn-Hant-TW", "en-US", "ja-JP", "ko-KR"],
                "max_audio_length": 60,
                "supports_diarization": True,
                "supports_word_time_offsets": True,
                "supports_automatic_punctuation": True,
                "max_phrases": 500
            }

        },
        "regions": {
            "us": {
                "name": "us",
                "display_name": "美國 (多區域)",
                "endpoint": "us-speech.googleapis.com",
                "latency": "低",
                "recommended": True
            },
            "eu": {
                "name": "eu",
                "display_name": "歐洲 (多區域)",
                "endpoint": "eu-speech.googleapis.com",
                "latency": "中等",
                "recommended": True
            },
            "asia-southeast1": {
                "name": "asia-southeast1",
                "display_name": "亞洲東南部 (新加坡)",
                "endpoint": "asia-southeast1-speech.googleapis.com",
                "latency": "低 (亞洲用戶)",
                "recommended": True
            },
            "asia-northeast1": {
                "name": "asia-northeast1",
                "display_name": "亞洲東北部 (東京)",
                "endpoint": "asia-northeast1-speech.googleapis.com",
                "latency": "低 (亞洲用戶)",
                "recommended": True
            },
            "us-central1": {
                "name": "us-central1",
                "display_name": "美國中部",
                "endpoint": "us-central1-speech.googleapis.com",
                "latency": "低",
                "recommended": False
            },
            "northamerica-northeast1": {
                "name": "northamerica-northeast1",
                "display_name": "美國東北部 (波士頓)",
                "endpoint": "northamerica-northeast1-speech.googleapis.com",
                "latency": "低",
                "recommended": False
            },
            "europe-west4": {
                "name": "europe-west4",
                "display_name": "歐洲西部 (荷蘭)",
                "endpoint": "europe-west4-speech.googleapis.com",
                "latency": "中等",
                "recommended": False
            }
        }
    }
    
    def __init__(self, project_id: str, config_file: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            project_id: Google Cloud 專案 ID
            config_file: 自訂配置檔案路徑（可選）
        """
        self.project_id = project_id
        self.logger = get_logger(self.__class__.__name__)
        
        # 載入配置
        if config_file and Path(config_file).exists():
            self.config = self._load_config(config_file)
            self.logger.info(f"載入自訂配置: {config_file}")
        else:
            self.config = self.DEFAULT_CONFIG
            self.logger.info("使用預設配置")
    
    def _load_config(self, config_file: str) -> dict:
        """載入配置檔案"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"載入配置失敗，使用預設值: {e}")
            return self.DEFAULT_CONFIG
    
    def get_optimal_config(
        self,
        model: str = "chirp_3",
        preferred_region: Optional[str] = None
    ) -> Tuple[str, str, str]:
        """
        取得最佳配置
        
        Args:
            model: 模型名稱
            preferred_region: 偏好區域（可選）
        
        Returns:
            Tuple[str, str, str]: (模型名稱, 區域, API端點)
        """
        # 取得模型配置
        model_config = self.config['models'].get(model)
        if not model_config:
            self.logger.warning(f"未知模型 '{model}', 使用 chirp_3")
            model = "chirp_3"
            model_config = self.config['models']['chirp_3']
        
        # 決定區域
        if preferred_region:
            region = preferred_region
            self.logger.info(f"使用指定區域: {region}")
        else:
            region = model_config['primary_region']
            self.logger.info(f"使用主要區域: {region}")
        
        # 建立端點
        region_config = self.config['regions'].get(region)
        if region_config:
            api_endpoint = region_config['endpoint']
        else:
            api_endpoint = f"{region}-speech.googleapis.com"
        
        self.logger.info(f"✅ 配置完成: 模型={model}, 區域={region}, 端點={api_endpoint}")
        
        return model, region, api_endpoint
    
    def get_model_info(self, model: str) -> dict:
        """
        取得模型詳細資訊
        
        Args:
            model: 模型名稱
        
        Returns:
            dict: 模型資訊
        """
        return self.config['models'].get(model, {})
    
    def get_region_info(self, region: str) -> dict:
        """
        取得區域詳細資訊
        
        Args:
            region: 區域名稱
        
        Returns:
            dict: 區域資訊
        """
        return self.config['regions'].get(region, {})
    
    def list_available_models(self) -> list:
        """
        列出所有可用模型
        
        Returns:
            list: 模型名稱列表
        """
        return list(self.config['models'].keys())
    
    def list_available_regions(self) -> list:
        """
        列出所有可用區域
        
        Returns:
            list: 區域名稱列表
        """
        return list(self.config['regions'].keys())
    
    def get_fallback_regions(self, model: str) -> list:
        """
        取得模型的備用區域列表
        
        Args:
            model: 模型名稱
        
        Returns:
            list: 備用區域列表
        """
        model_config = self.config['models'].get(model, {})
        return model_config.get('fallback_regions', [])
    
    def supports_feature(self, model: str, feature: str) -> bool:
        """
        檢查模型是否支援特定功能
        
        Args:
            model: 模型名稱
            feature: 功能名稱 (streaming, diarization)
        
        Returns:
            bool: 是否支援
        """
        model_config = self.config['models'].get(model, {})
        feature_key = f"supports_{feature}"
        return model_config.get(feature_key, False)
    
    def get_max_phrases(self, model: str) -> int:
        """
        取得模型支援的最大詞彙數量
        
        Args:
            model: 模型名稱
        
        Returns:
            int: 最大詞彙數量
        """
        model_config = self.config['models'].get(model, {})
        return model_config.get('max_phrases', 500)
    
    def print_summary(self):
        """列印配置摘要"""
        print("\n" + "=" * 80)
        print("Google STT 配置管理器")
        print("=" * 80)
        print(f"專案 ID: {self.project_id}")
        
        print("\n可用模型:")
        for model_name in self.list_available_models():
            info = self.get_model_info(model_name)
            print(f"\n  {model_name}:")
            print(f"    名稱: {info.get('display_name', 'N/A')}")
            print(f"    主要區域: {info.get('primary_region', 'N/A')}")
            print(f"    支援串流: {'✅' if info.get('supports_streaming') else '❌'}")
            print(f"    支援講者識別: {'✅' if info.get('supports_diarization') else '❌'}")
            print(f"    最大詞彙數: {info.get('max_phrases', 'N/A')}")
            if info.get('recommended_for'):
                print(f"    建議用於: {', '.join(info.get('recommended_for', []))}")
        
        print("\n可用區域:")
        for region_name in self.list_available_regions():
            info = self.get_region_info(region_name)
            recommended = "✅ 推薦" if info.get('recommended') else ""
            print(f"  - {region_name}: {info.get('display_name', 'N/A')} {recommended}")
        
        print("\n" + "=" * 80)


def main():
    """測試配置管理器"""
    print("測試 Google STT 配置管理器")
    
    # 建立配置管理器
    manager = GoogleSTTConfigManager("dazzling-seat-315406")
    
    # 列印摘要
    manager.print_summary()
    
    # 測試取得最佳配置
    print("\n測試配置取得:")
    print("-" * 80)
    
    test_cases = [
        ("chirp_3", None),
        ("chirp_3", "us"),
        ("chirp_telephony", "asia-southeast1"),
        ("latest_long", "eu")
    ]
    
    for model, region in test_cases:
        print(f"\n測試: model={model}, preferred_region={region}")
        result_model, result_region, result_endpoint = manager.get_optimal_config(
            model=model,
            preferred_region=region
        )
        print(f"結果:")
        print(f"  模型: {result_model}")
        print(f"  區域: {result_region}")
        print(f"  端點: {result_endpoint}")
        
        # 檢查功能支援
        supports_streaming = manager.supports_feature(model, "streaming")
        supports_diarization = manager.supports_feature(model, "diarization")
        max_phrases = manager.get_max_phrases(model)
        
        print(f"  支援串流: {'✅' if supports_streaming else '❌'}")
        print(f"  支援講者識別: {'✅' if supports_diarization else '❌'}")
        print(f"  最大詞彙數: {max_phrases}")


if __name__ == "__main__":
    main()