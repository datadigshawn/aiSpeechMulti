#!/usr/bin/env python3
"""
音訊切分模組
將長音檔切分為固定長度的短片段，便於批次處理
"""

import sys
from pathlib import Path

# 添加專案路徑
sys.path.append(str(Path(__file__).parent.parent))

from pydub import AudioSegment
from pydub.silence import detect_nonsilent
from typing import List

from utils.logger import get_logger
from utils.config import get_config


class AudioSplitter:
    """音訊切分器"""
    
    def __init__(
        self,
        chunk_duration_sec: int = 10,
        use_vad: bool = False
    ):
        """
        初始化音訊切分器
        
        Args:
            chunk_duration_sec: 切片長度 (秒)
            use_vad: 是否使用 VAD 進行智能切分
        """
        self.logger = get_logger(self.__class__.__name__)
        self.config = get_config()
        self.chunk_duration_sec = chunk_duration_sec
        self.use_vad = use_vad
        
        self.logger.info(f"AudioSplitter 初始化完成 (切片長度: {chunk_duration_sec}秒)")
    
    def split_audio(
        self,
        input_path: Path,
        output_dir: Path,
        prefix: str = "chunk"
    ) -> List[Path]:
        """
        切分音訊檔案
        
        Args:
            input_path: 輸入音訊檔案路徑
            output_dir: 輸出目錄
            prefix: 輸出檔案前綴
        
        Returns:
            切分後的音訊檔案路徑列表
        """
        self.logger.info(f"開始切分音訊: {input_path.name}")
        
        # 建立輸出目錄
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 載入音訊
        audio = AudioSegment.from_file(str(input_path))
        
        # 計算切片參數
        chunk_length_ms = self.chunk_duration_sec * 1000
        total_length_ms = len(audio)
        num_chunks = (total_length_ms + chunk_length_ms - 1) // chunk_length_ms
        
        self.logger.info(f"音訊長度: {total_length_ms/1000:.2f}秒，將切分為 {num_chunks} 個片段")
        
        # 執行切分
        output_paths = []
        for i in range(num_chunks):
            start_ms = i * chunk_length_ms
            end_ms = min((i + 1) * chunk_length_ms, total_length_ms)
            
            chunk = audio[start_ms:end_ms]
            
            # 輸出檔案路徑
            output_filename = f"{prefix}_{i+1:03d}.wav"
            output_path = output_dir / output_filename
            
            # 匯出為 WAV
            chunk.export(
                str(output_path),
                format="wav",
                parameters=["-ar", str(self.config.SAMPLE_RATE)]
            )
            
            output_paths.append(output_path)
        
        self.logger.info(f"✅ 切分完成，共產生 {len(output_paths)} 個檔案")
        return output_paths
    
    def split_by_silence(
        self,
        input_path: Path,
        output_dir: Path,
        min_silence_len: int = 500,
        silence_thresh: int = -40
    ) -> List[Path]:
        """
        基於靜音偵測進行智能切分
        
        Args:
            input_path: 輸入音訊檔案
            output_dir: 輸出目錄
            min_silence_len: 最小靜音長度 (毫秒)
            silence_thresh: 靜音閾值 (dB)
        
        Returns:
            切分後的檔案路徑列表
        """
        self.logger.info(f"基於靜音偵測切分: {input_path.name}")
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 載入音訊
        audio = AudioSegment.from_file(str(input_path))
        
        # 偵測非靜音片段
        nonsilent_ranges = detect_nonsilent(
            audio,
            min_silence_len=min_silence_len,
            silence_thresh=silence_thresh
        )
        
        self.logger.info(f"偵測到 {len(nonsilent_ranges)} 個非靜音片段")
        
        # 匯出每個片段
        output_paths = []
        for i, (start_ms, end_ms) in enumerate(nonsilent_ranges):
            chunk = audio[start_ms:end_ms]
            
            output_filename = f"speech_{i+1:03d}.wav"
            output_path = output_dir / output_filename
            
            chunk.export(
                str(output_path),
                format="wav",
                parameters=["-ar", str(self.config.SAMPLE_RATE)]
            )
            
            output_paths.append(output_path)
        
        self.logger.info(f"✅ 智能切分完成，共產生 {len(output_paths)} 個檔案")
        return output_paths


def main():
    """主函數 - 命令列介面"""
    import argparse
    
    parser = argparse.ArgumentParser(description="音訊切分工具")
    parser.add_argument("input", type=Path, help="輸入音訊檔案")
    parser.add_argument("output", type=Path, help="輸出目錄")
    parser.add_argument("--duration", type=int, default=10, help="切片長度 (秒)")
    parser.add_argument("--vad", action="store_true", help="使用 VAD 智能切分")
    
    args = parser.parse_args()
    
    # 執行切分
    splitter = AudioSplitter(chunk_duration_sec=args.duration, use_vad=args.vad)
    
    if args.vad:
        output_paths = splitter.split_by_silence(args.input, args.output)
    else:
        output_paths = splitter.split_audio(args.input, args.output)
    
    print(f"\n✅ 完成！產生了 {len(output_paths)} 個音訊檔案")
    print(f"📁 輸出位置: {args.output}")


if __name__ == "__main__":
    main()
