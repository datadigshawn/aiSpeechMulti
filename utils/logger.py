"""
統一日誌系統模組
提供分級輸出、檔案輪轉、格式化等功能
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
import sys


class ColoredFormatter(logging.Formatter):
    """帶顏色的終端輸出格式化器"""
    
    # ANSI 顏色碼
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 綠色
        'WARNING': '\033[33m',    # 黃色
        'ERROR': '\033[31m',      # 紅色
        'CRITICAL': '\033[35m'    # 紫色
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # 為日誌級別添加顏色
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.RESET}"
        return super().format(record)


class AISpeechLogger:
    """aiSpeech 專案統一日誌管理器"""
    
    def __init__(
        self, 
        name: str,
        log_dir: str = "logs",
        console_level: int = logging.INFO,
        file_level: int = logging.DEBUG,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5
    ):
        """
        初始化日誌器
        
        Args:
            name: 日誌器名稱（通常使用模組名稱）
            log_dir: 日誌檔案目錄
            console_level: 終端輸出級別
            file_level: 檔案輸出級別
            max_bytes: 單一日誌檔案最大大小
            backup_count: 保留的備份檔案數量
        """
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)  # 設定最低級別
        
        # 避免重複添加 handler
        if self.logger.handlers:
            return
        
        # 建立日誌目錄
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # 1. 終端輸出 Handler（帶顏色）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_formatter = ColoredFormatter(
            fmt='%(levelname)-8s | %(name)s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # 2. 檔案輸出 Handler（輪轉）—— 檔名含啟動日期時間（精確到秒）
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = log_path / f"{name}_{_ts}.log"
        file_handler = RotatingFileHandler(
            filename=log_filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(file_level)
        file_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

        # 3. 錯誤專用 Handler（記錄所有 ERROR 及以上級別）
        error_filename = log_path / f"{name}_{_ts}_errors.log"
        error_handler = RotatingFileHandler(
            filename=error_filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        self.logger.addHandler(error_handler)
    
    def debug(self, msg, *args, **kwargs):
        """除錯級別日誌"""
        self.logger.debug(msg, *args, **kwargs)
    
    def info(self, msg, *args, **kwargs):
        """資訊級別日誌"""
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        """警告級別日誌"""
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg, *args, **kwargs):
        """錯誤級別日誌"""
        self.logger.error(msg, *args, **kwargs)
    
    def critical(self, msg, *args, **kwargs):
        """嚴重錯誤級別日誌"""
        self.logger.critical(msg, *args, **kwargs)
    
    def exception(self, msg, *args, **kwargs):
        """記錄例外資訊（自動包含堆疊追蹤）"""
        self.logger.exception(msg, *args, **kwargs)


def get_logger(name: str = None, **kwargs) -> AISpeechLogger:
    """
    獲取日誌器的便捷函數
    
    Args:
        name: 日誌器名稱，如果為 None 則使用呼叫者的模組名稱
        **kwargs: 傳遞給 AISpeechLogger 的其他參數
    
    Returns:
        AISpeechLogger 實例
    
    Example:
        >>> from utils.logger import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("程式開始執行")
    """
    if name is None:
        # 自動取得呼叫者的模組名稱
        import inspect
        frame = inspect.currentframe().f_back
        name = frame.f_globals.get('__name__', 'unknown')
    
    return AISpeechLogger(name, **kwargs)


# 預定義的日誌器類型
def get_batch_logger():
    """取得批次處理專用日誌器"""
    return get_logger('batch_processing', log_dir='logs/batch')


def get_realtime_logger():
    """取得即時辨識專用日誌器"""
    return get_logger('realtime_processing', log_dir='logs/realtime')


def get_model_logger(model_name: str):
    """取得模型專用日誌器"""
    return get_logger(f'model_{model_name}', log_dir='logs/models')


def get_evaluation_logger():
    """取得評測專用日誌器"""
    return get_logger('evaluation', log_dir='logs/evaluation')


if __name__ == "__main__":
    # 測試日誌系統
    logger = get_logger('test_logger')
    
    logger.debug("這是除錯訊息")
    logger.info("這是資訊訊息")
    logger.warning("這是警告訊息")
    logger.error("這是錯誤訊息")
    logger.critical("這是嚴重錯誤訊息")
    
    # 測試例外記錄
    try:
        1 / 0
    except Exception as e:
        logger.exception("發生除以零的錯誤")
    
    print("\n日誌系統測試完成！請檢查 logs/ 目錄")