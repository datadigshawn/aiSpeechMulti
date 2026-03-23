"""
全局時間戳管理器 (Timestamp Manager)
核心功能：
1. 建立全局時間基準 (session_metadata.json)
2. 計算切片時間戳 (chunks_timeline.json)
3. 對齊辨識結果時間戳
4. 支援時間範圍查詢
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import wave

from utils.logger import get_logger

logger = get_logger(__name__)


class TimestampManager:
    """時間戳管理器"""
    
    def __init__(self, project_root: str = "."):
        """
        初始化時間戳管理器
        
        Args:
            project_root: 專案根目錄
        """
        self.project_root = Path(project_root)
        logger.info(f"時間戳管理器初始化完成，專案根目錄: {self.project_root}")
    
    def create_session_metadata(
        self,
        audio_file: str,
        test_case: str,
        mode: str = "batch",
        session_id: Optional[str] = None,
        output_dir: Optional[str] = None
    ) -> Dict:
        """
        建立 Session 全局時間基準
        
        Args:
            audio_file: 原始音檔路徑
            test_case: 測試案名稱 (如 "Test_01_TMRT")
            mode: 處理模式 ("batch" 或 "realtime")
            session_id: 自訂 Session ID（可選）
            output_dir: 輸出目錄（可選，預設為音檔所在目錄）
        
        Returns:
            Session metadata 字典
        """
        audio_path = Path(audio_file)
        
        if not audio_path.exists():
            raise FileNotFoundError(f"音檔不存在: {audio_file}")
        
        # 生成 Session ID
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        # 從檔名推測錄音開始時間（格式：radio_20251201_140000.wav）
        try:
            filename = audio_path.stem
            parts = filename.split('_')
            if len(parts) >= 3:
                date_str = parts[1]  # 20251201
                time_str = parts[2]  # 140000
                year = int(date_str[:4])
                month = int(date_str[4:6])
                day = int(date_str[6:8])
                hour = int(time_str[:2])
                minute = int(time_str[2:4])
                second = int(time_str[4:6])
                session_start = datetime(year, month, day, hour, minute, second)
            else:
                # 如果檔名格式不符，使用檔案修改時間
                session_start = datetime.fromtimestamp(audio_path.stat().st_mtime)
        except Exception as e:
            logger.warning(f"無法從檔名解析時間: {e}，使用檔案修改時間")
            session_start = datetime.fromtimestamp(audio_path.stat().st_mtime)
        
        # 讀取音檔屬性
        try:
            with wave.open(str(audio_path), 'rb') as wf:
                sample_rate = wf.getframerate()
                num_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                num_frames = wf.getnframes()
                duration_seconds = num_frames / sample_rate
        except Exception as e:
            logger.error(f"讀取音檔屬性失敗: {e}")
            raise
        
        # 建立 metadata
        metadata = {
            "session_id": session_id,
            "test_case": test_case,
            "original_file": str(audio_path.name),
            "original_file_path": str(audio_path.absolute()),
            "session_start_time": session_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "session_start_unix": session_start.timestamp(),
            "processing_mode": mode,
            "audio_properties": {
                "sample_rate": sample_rate,
                "num_channels": num_channels,
                "sample_width": sample_width,
                "duration_seconds": round(duration_seconds, 3),
                "total_frames": num_frames
            },
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 儲存到檔案
        if output_dir is None:
            output_dir = audio_path.parent
        else:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        
        metadata_file = output_dir / "session_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Session metadata 已建立: {metadata_file}")
        logger.info(f"  Session ID: {session_id}")
        logger.info(f"  開始時間: {metadata['session_start_time']}")
        logger.info(f"  音訊長度: {duration_seconds:.2f} 秒")
        
        return metadata
    
    def create_chunks_timeline(
        self,
        chunks_info: List[Dict],
        session_metadata: Dict,
        output_dir: str
    ) -> Dict:
        """
        建立切片時間戳索引
        
        Args:
            chunks_info: 切片資訊列表，每個元素包含:
                {
                    "chunk_id": "001",
                    "offset_ms": 0,
                    "duration_ms": 8500,
                    "is_speech": true,
                    "audio_file": "chunk_001.wav"
                }
            session_metadata: Session 全局時間基準
            output_dir: 輸出目錄
        
        Returns:
            Timeline 字典
        """
        session_start = datetime.fromtimestamp(session_metadata["session_start_unix"])
        
        timeline = {
            "session_id": session_metadata["session_id"],
            "reference_time": session_metadata["session_start_time"],
            "chunks": []
        }
        
        for chunk in chunks_info:
            offset_ms = chunk["offset_ms"]
            duration_ms = chunk["duration_ms"]
            
            # 計算絕對時間
            absolute_start = session_start + timedelta(milliseconds=offset_ms)
            absolute_end = absolute_start + timedelta(milliseconds=duration_ms)
            
            chunk_entry = {
                "chunk_id": chunk["chunk_id"],
                "offset_ms": offset_ms,
                "duration_ms": duration_ms,
                "is_speech": chunk.get("is_speech", True),
                "audio_file": chunk.get("audio_file"),
                "absolute_start": absolute_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "absolute_end": absolute_end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            }
            
            timeline["chunks"].append(chunk_entry)
        
        # 儲存到檔案
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timeline_file = output_path / "chunks_timeline.json"
        with open(timeline_file, 'w', encoding='utf-8') as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Chunks timeline 已建立: {timeline_file}")
        logger.info(f"  總切片數: {len(timeline['chunks'])}")
        logger.info(f"  語音段數: {sum(1 for c in timeline['chunks'] if c['is_speech'])}")
        
        return timeline
    
    def align_stt_results_with_timeline(
        self,
        stt_results: Dict[str, Dict],
        chunks_timeline: Dict,
        model_name: str = "stt"
    ) -> Dict:
        """
        將辨識結果與時間軸對齊
        
        Args:
            stt_results: 辨識結果字典
                {
                    "chunk_001": {
                        "transcript": "請確認R13站狀況",
                        "words": [
                            {"word": "請", "start_ms": 0, "end_ms": 150},
                            ...
                        ],
                        "confidence": 0.95
                    }
                }
            chunks_timeline: 切片時間軸
            model_name: 模型名稱（用於輸出檔名）
        
        Returns:
            含完整時間戳的結果字典
        """
        session_id = chunks_timeline["session_id"]
        session_start = datetime.strptime(
            chunks_timeline["reference_time"], 
            "%Y-%m-%d %H:%M:%S.%f"
        )
        
        # 建立 chunk_id 到時間資訊的映射
        chunk_map = {
            chunk["chunk_id"]: chunk 
            for chunk in chunks_timeline["chunks"]
        }
        
        aligned_results = {
            "session_id": session_id,
            "model": model_name,
            "aligned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "events": []
        }
        
        for chunk_id, result in stt_results.items():
            if chunk_id not in chunk_map:
                logger.warning(f"找不到 {chunk_id} 的時間資訊，跳過")
                continue
            
            chunk_info = chunk_map[chunk_id]
            chunk_start = datetime.strptime(
                chunk_info["absolute_start"], 
                "%Y-%m-%d %H:%M:%S.%f"
            )
            
            event = {
                "chunk_id": chunk_id,
                "absolute_start": chunk_info["absolute_start"],
                "absolute_end": chunk_info["absolute_end"],
                "transcript": result.get("transcript", ""),
                "confidence": result.get("confidence")
            }
            
            # 如果有字級時間戳，轉換為絕對時間
            if "words" in result:
                event["words"] = []
                for word_info in result["words"]:
                    word_start_ms = word_info.get("start_ms", 0)
                    word_end_ms = word_info.get("end_ms", 0)
                    
                    word_abs_start = chunk_start + timedelta(milliseconds=word_start_ms)
                    word_abs_end = chunk_start + timedelta(milliseconds=word_end_ms)
                    
                    event["words"].append({
                        "word": word_info["word"],
                        "absolute_start": word_abs_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "absolute_end": word_abs_end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "start_offset_ms": word_start_ms,
                        "end_offset_ms": word_end_ms
                    })
            
            aligned_results["events"].append(event)
        
        # 按時間排序
        aligned_results["events"].sort(key=lambda x: x["absolute_start"])
        
        logger.info(f"已對齊 {len(aligned_results['events'])} 個辨識結果")
        
        return aligned_results
    
    def query_by_time_range(
        self,
        aligned_results: Dict,
        start_time: str,
        end_time: str
    ) -> List[Dict]:
        """
        根據時間範圍查詢辨識結果
        
        Args:
            aligned_results: 對齊後的辨識結果
            start_time: 開始時間 (格式: "2025-12-01 14:00:00")
            end_time: 結束時間
        
        Returns:
            符合條件的事件列表
        """
        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
        
        results = []
        for event in aligned_results["events"]:
            event_start = datetime.strptime(
                event["absolute_start"].split('.')[0],
                "%Y-%m-%d %H:%M:%S"
            )
            
            if start_dt <= event_start <= end_dt:
                results.append(event)
        
        logger.info(f"查詢時間範圍 {start_time} ~ {end_time}: 找到 {len(results)} 筆結果")
        
        return results
    
    def load_session_metadata(self, metadata_file: str) -> Dict:
        """載入 Session metadata"""
        with open(metadata_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def load_chunks_timeline(self, timeline_file: str) -> Dict:
        """載入 Chunks timeline"""
        with open(timeline_file, 'r', encoding='utf-8') as f:
            return json.load(f)


if __name__ == "__main__":
    # 測試時間戳管理器
    manager = TimestampManager()
    
    # 測試建立 session metadata（假設檔案存在）
    test_audio = "experiments/Test_01_TMRT/batch_processing/source_audio/radio_20251201_140000.wav"
    
    if Path(test_audio).exists():
        metadata = manager.create_session_metadata(
            audio_file=test_audio,
            test_case="Test_01_TMRT",
            mode="batch"
        )
        print(f"\nSession Metadata:")
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
    else:
        print(f"測試檔案不存在: {test_audio}")
        print("請先放置測試音檔再執行測試")