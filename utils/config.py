#!/usr/bin/env python3
"""
配置管理模組
集中管理系統配置參數
"""

import os
from pathlib import Path
from typing import Dict, Optional
import torch


class Config:
    """系統配置類別"""
    
    def __init__(self):
        """初始化配置"""
        # 專案根目錄
        self.PROJECT_ROOT = Path(__file__).parent.parent
                
        # 環境變數
        self.GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        
        # 裝置設定 (自動偵測)
        self.DEVICE = self._detect_device()
        
        # Google STT 設定
        self.GOOGLE_STT_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "dazzling-seat-315406")
        self.GOOGLE_STT_MODEL = "chirp_3"  # 或 "latest_long"
        self.GOOGLE_STT_LANGUAGE = "cmn-Hant-TW"  # 台灣繁體中文
        
        # VAD 設定
        self.VAD_TYPE = "webrtc"  # "webrtc" 或 "silero"
        self.VAD_AGGRESSIVENESS = 3  # WebRTC 靈敏度 0-3
        
        # 音訊設定
        self.SAMPLE_RATE = 16000  # 採樣率 (Hz)
        self.CHUNK_DURATION = 10   # 切片長度 (秒)
        
        # 路徑設定
        self.EXPERIMENTS_DIR = self.PROJECT_ROOT / "experiments"
        self.UTILS_DIR = self.PROJECT_ROOT / "utils"
        self.SCRIPTS_DIR = self.PROJECT_ROOT / "scripts"
        self.LOGS_DIR = self.PROJECT_ROOT / "logs"
        
        # 詞彙表設定
        self.MASTER_VOCAB_PATH = self.UTILS_DIR / "master_vocabulary.csv"
        
        # 建立必要目錄
        self._create_directories()
    
    def _detect_device(self) -> str:
        """
        自動偵測可用的運算裝置
        
        Returns:
            "cuda" (NVIDIA GPU) / "mps" (Apple M 系列) / "cpu"
        """
        if torch.cuda.is_available():
            return "cuda"
        elif torch.backends.mps.is_available():
            return "mps"
        else:
            return "cpu"
    
    def _create_directories(self):
        """建立必要的目錄結構"""
        dirs_to_create = [
            self.EXPERIMENTS_DIR,
            self.LOGS_DIR,
            self.SCRIPTS_DIR / "models",
        ]
        
        for directory in dirs_to_create:
            directory.mkdir(parents=True, exist_ok=True)
    
    def get_test_case_path(self, test_case_name: str) -> Path:
        """
        獲取測試案例的路徑
        
        Args:
            test_case_name: 測試案例名稱 (例如 "Test_01_TMRT")
        
        Returns:
            測試案例的完整路徑
        """
        return self.EXPERIMENTS_DIR / test_case_name
    
    def to_dict(self) -> Dict:
        """將配置轉換為字典"""
        return {
            "project_root": str(self.PROJECT_ROOT),
            "device": self.DEVICE,
            "google_stt_model": self.GOOGLE_STT_MODEL,
            "vad_type": self.VAD_TYPE,
            "sample_rate": self.SAMPLE_RATE,
        }


# 全域配置實例
_config_instance: Optional[Config] = None


def get_config() -> Config:
    """
    獲取全域配置實例 (單例模式)
    
    Returns:
        Config 實例
    """
    global _config_instance
    
    if _config_instance is None:
        _config_instance = Config()
        print(f"🔧 配置讀取完成，使用裝置: {_config_instance.DEVICE}")
    
    return _config_instance


def test_config():
    """測試配置模組"""
    print("測試配置模組...")
    
    config = get_config()
    
    print(f"\n專案根目錄: {config.PROJECT_ROOT}")
    print(f"運算裝置: {config.DEVICE}")
    print(f"Google STT 模型: {config.GOOGLE_STT_MODEL}")
    print(f"VAD 類型: {config.VAD_TYPE}")
    print(f"採樣率: {config.SAMPLE_RATE} Hz")
    
    print("\n環境變數檢查:")
    if config.GOOGLE_APPLICATION_CREDENTIALS:
        print(f"  ✅ GOOGLE_APPLICATION_CREDENTIALS 已設定")
    else:
        print(f"  ⚠️  GOOGLE_APPLICATION_CREDENTIALS 未設定")
    
    if config.GEMINI_API_KEY:
        print(f"  ✅ GEMINI_API_KEY 已設定")
    else:
        print(f"  ⚠️  GEMINI_API_KEY 未設定")
    
    print("\n✅ 配置模組測試完成")


if __name__ == "__main__":
    test_config()
