#!/usr/bin/env python3
"""
VAD 預處理腳本 - 修正版
解決 ffmpeg 編碼器問題，使用 soundfile 直接處理

音訊讀檔：soundfile + numpy
依賴性：僅需 Python 庫
VAD容器:沒裝庫自動回退至能量檢測
輸出格式：強制轉為單聲道、16kHz、int16 WAV
報告功能：自動生成 vad_report.json統計報表

"""

import argparse
import sys
from pathlib import Path
from typing import List, Tuple, Dict
import numpy as np
import soundfile as sf
import json
from datetime import datetime
import logging

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 嘗試導入 WebRTC VAD
try:
    import webrtcvad
    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False
    logger.warning("WebRTC VAD 未安裝，將使用基於能量的 VAD")


class VADPreprocessor:
    """VAD 預處理器 - 使用 soundfile"""
    
    def __init__(
        self,
        vad_method: str = "energy",
        vad_threshold: float = 0.5,
        min_speech_duration: float = 0.3,
        min_silence_duration: float = 0.5,
        max_chunk_length: float = 50.0,
        sample_rate: int = 16000
    ):
        """初始化 VAD 預處理器"""
        self.vad_method = vad_method
        self.vad_threshold = vad_threshold
        self.min_speech_duration = min_speech_duration
        self.min_silence_duration = min_silence_duration
        self.max_chunk_length = max_chunk_length
        self.target_sample_rate = sample_rate
        
        # 初始化 WebRTC VAD
        if vad_method == "webrtc":
            if not WEBRTC_AVAILABLE:
                logger.warning("WebRTC VAD 不可用，回退到能量檢測")
                self.vad_method = "energy"
            else:
                aggressiveness = min(3, max(0, int(vad_threshold * 4)))
                self.vad = webrtcvad.Vad(aggressiveness)
                logger.info(f"✅ 使用 WebRTC VAD (aggressiveness={aggressiveness})")
        else:
            logger.info("✅ 使用基於能量的 VAD")
    
    def resample_audio(self, audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """簡單的重採樣（使用線性插值）"""
        if orig_sr == target_sr:
            return audio
        
        # 計算重採樣比例
        ratio = target_sr / orig_sr
        
        # 使用 numpy 的插值
        orig_length = len(audio)
        target_length = int(orig_length * ratio)
        
        # 線性插值
        orig_indices = np.arange(orig_length)
        target_indices = np.linspace(0, orig_length - 1, target_length)
        resampled = np.interp(target_indices, orig_indices, audio)
        
        return resampled.astype(audio.dtype)
    
    def detect_speech_energy(
        self, 
        audio: np.ndarray,
        sample_rate: int
    ) -> List[Tuple[int, int]]:
        """
        使用能量檢測法檢測語音段
        
        Returns:
            List of (start_sample, end_sample) tuples
        """
        # 計算音框能量
        frame_length = int(sample_rate * 0.03)  # 30ms
        hop_length = int(sample_rate * 0.01)    # 10ms
        
        # 計算每幀的 RMS 能量
        energy = []
        for i in range(0, len(audio) - frame_length, hop_length):
            frame = audio[i:i + frame_length]
            rms = np.sqrt(np.mean(frame**2))
            energy.append(rms)
        
        energy = np.array(energy)
        
        # 計算閾值
        # 使用百分位數作為閾值
        percentile = self.vad_threshold * 100
        threshold = np.percentile(energy, percentile)
        
        # 如果閾值太低，使用最大值的比例
        max_energy = np.max(energy)
        min_threshold = max_energy * 0.1  # 至少是最大值的 10%
        threshold = max(threshold, min_threshold)
        
        # 檢測語音段
        is_speech = energy > threshold
        
        # 找到連續的語音段
        segments = []
        start_frame = None
        
        min_speech_frames = int(self.min_speech_duration * sample_rate / hop_length)
        min_silence_frames = int(self.min_silence_duration * sample_rate / hop_length)
        
        silence_counter = 0
        
        for i, speech in enumerate(is_speech):
            if speech:
                if start_frame is None:
                    start_frame = i
                silence_counter = 0
            else:
                if start_frame is not None:
                    silence_counter += 1
                    if silence_counter >= min_silence_frames:
                        # 語音段結束
                        if (i - start_frame) >= min_speech_frames:
                            start_sample = start_frame * hop_length
                            end_sample = (i - silence_counter) * hop_length
                            segments.append((start_sample, end_sample))
                        start_frame = None
                        silence_counter = 0
        
        # 處理最後一段
        if start_frame is not None:
            if (len(is_speech) - start_frame) >= min_speech_frames:
                start_sample = start_frame * hop_length
                end_sample = len(audio)
                segments.append((start_sample, end_sample))
        
        logger.info(f"   檢測到 {len(segments)} 個語音段")
        return segments
    
    def detect_speech_webrtc(
        self,
        audio: np.ndarray,
        sample_rate: int
    ) -> List[Tuple[int, int]]:
        """
        使用 WebRTC VAD 檢測語音段
        
        Returns:
            List of (start_sample, end_sample) tuples
        """
        # WebRTC VAD 要求 16kHz, mono, int16
        if sample_rate != 16000:
            audio = self.resample_audio(audio, sample_rate, 16000)
            sample_rate = 16000
        
        # 轉換為 int16
        if audio.dtype != np.int16:
            audio = (audio * 32767).astype(np.int16)
        
        # WebRTC VAD 使用 10/20/30ms 幀
        frame_duration_ms = 30
        frame_samples = int(sample_rate * frame_duration_ms / 1000)
        
        # 檢測語音幀
        speech_frames = []
        for i in range(0, len(audio), frame_samples):
            frame = audio[i:i + frame_samples]
            if len(frame) < frame_samples:
                # 填充到完整幀
                frame = np.pad(frame, (0, frame_samples - len(frame)), mode='constant')
            
            frame_bytes = frame.tobytes()
            is_speech = self.vad.is_speech(frame_bytes, sample_rate)
            speech_frames.append(is_speech)
        
        # 合併連續語音幀
        segments = []
        start_frame = None
        
        min_speech_frames = int(self.min_speech_duration * 1000 / frame_duration_ms)
        min_silence_frames = int(self.min_silence_duration * 1000 / frame_duration_ms)
        
        silence_counter = 0
        
        for i, is_speech in enumerate(speech_frames):
            if is_speech:
                if start_frame is None:
                    start_frame = i
                silence_counter = 0
            else:
                if start_frame is not None:
                    silence_counter += 1
                    if silence_counter >= min_silence_frames:
                        if (i - start_frame) >= min_speech_frames:
                            start_sample = start_frame * frame_samples
                            end_sample = (i - silence_counter) * frame_samples
                            segments.append((start_sample, end_sample))
                        start_frame = None
                        silence_counter = 0
        
        # 處理最後一段
        if start_frame is not None:
            if (len(speech_frames) - start_frame) >= min_speech_frames:
                start_sample = start_frame * frame_samples
                end_sample = len(audio)
                segments.append((start_sample, end_sample))
        
        logger.info(f"   檢測到 {len(segments)} 個語音段")
        return segments
    
    def split_long_segments(
        self,
        segments: List[Tuple[int, int]],
        sample_rate: int
    ) -> List[Tuple[int, int]]:
        """切分過長的語音段"""
        max_samples = int(self.max_chunk_length * sample_rate)
        split_segments = []
        
        for start, end in segments:
            duration_samples = end - start
            
            if duration_samples <= max_samples:
                split_segments.append((start, end))
            else:
                # 需要切分
                num_chunks = int(np.ceil(duration_samples / max_samples))
                chunk_samples = duration_samples / num_chunks
                
                for i in range(num_chunks):
                    chunk_start = start + int(i * chunk_samples)
                    chunk_end = start + int((i + 1) * chunk_samples)
                    split_segments.append((chunk_start, chunk_end))
                
                logger.info(f"   長音段 ({duration_samples/sample_rate:.1f}s) 切分為 {num_chunks} 段")
        
        return split_segments
    
    def process_audio_file(
        self,
        input_path: Path,
        output_dir: Path
    ) -> Dict:
        """處理單個音訊檔案"""
        logger.info(f"處理: {input_path.name}")
        
        try:
            # 使用 soundfile 載入音訊
            audio, sample_rate = sf.read(input_path)
            
            # 轉換為 mono
            if len(audio.shape) > 1:
                audio = np.mean(audio, axis=1)
            
            original_duration = len(audio) / sample_rate
            
            logger.info(f"   原始長度: {original_duration:.2f}秒")
            logger.info(f"   取樣率: {sample_rate} Hz")
            logger.info(f"   音訊格式: {audio.dtype}")
            
            # 正規化到 [-1, 1]
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0
            elif audio.dtype == np.int32:
                audio = audio.astype(np.float32) / 2147483648.0
            
            # 檢測語音段
            if self.vad_method == "webrtc":
                segments = self.detect_speech_webrtc(audio, sample_rate)
            else:
                segments = self.detect_speech_energy(audio, sample_rate)
            
            if not segments:
                logger.warning(f"   ⚠️  未檢測到語音段")
                return {
                    "filename": input_path.name,
                    "status": "no_speech",
                    "original_duration": original_duration,
                    "chunks": 0
                }
            
            # 切分長音段
            segments = self.split_long_segments(segments, sample_rate)
            
            # 儲存切分後的音檔
            chunks_info = []
            for i, (start_sample, end_sample) in enumerate(segments):
                chunk = audio[start_sample:end_sample]
                
                # 檔名
                chunk_filename = f"{input_path.stem}_chunk_{i+1:03d}.wav"
                chunk_path = output_dir / chunk_filename
                
                # 使用 soundfile 儲存
                # 轉換回 int16 以節省空間
                chunk_int16 = (chunk * 32767).astype(np.int16)
                sf.write(chunk_path, chunk_int16, sample_rate)
                
                chunk_duration = len(chunk) / sample_rate
                start_ms = int(start_sample * 1000 / sample_rate)
                end_ms = int(end_sample * 1000 / sample_rate)
                
                chunks_info.append({
                    "filename": chunk_filename,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "duration": chunk_duration
                })
                
                logger.info(f"   ✅ 切段 {i+1}: {chunk_duration:.2f}秒 ({start_ms}ms - {end_ms}ms)")
            
            # 計算統計
            total_speech_duration = sum(c["duration"] for c in chunks_info)
            speech_ratio = total_speech_duration / original_duration
            
            logger.info(f"   語音總長: {total_speech_duration:.2f}秒 ({speech_ratio*100:.1f}%)")
            
            return {
                "filename": input_path.name,
                "status": "success",
                "original_duration": original_duration,
                "speech_duration": total_speech_duration,
                "speech_ratio": speech_ratio,
                "chunks": len(chunks_info),
                "chunks_info": chunks_info
            }
        
        except Exception as e:
            logger.error(f"   ❌ 處理失敗: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "filename": input_path.name,
                "status": "error",
                "error": str(e)
            }
    
    def process_directory(
        self,
        input_dir: Path,
        output_dir: Path
    ) -> Dict:
        """處理整個目錄"""
        # 創建輸出目錄
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 找到所有音檔
        audio_files = list(input_dir.glob("*.wav"))
        
        if not audio_files:
            logger.error(f"❌ 在 {input_dir} 中找不到 .wav 檔案")
            return {}
        
        logger.info(f"\n{'='*70}")
        logger.info(f"VAD 預處理開始")
        logger.info(f"{'='*70}")
        logger.info(f"輸入目錄: {input_dir}")
        logger.info(f"輸出目錄: {output_dir}")
        logger.info(f"找到 {len(audio_files)} 個音檔")
        logger.info(f"VAD 方法: {self.vad_method}")
        logger.info(f"VAD 閾值: {self.vad_threshold}")
        logger.info(f"最短語音段: {self.min_speech_duration}秒")
        logger.info(f"最短靜音段: {self.min_silence_duration}秒")
        logger.info(f"最大切段長度: {self.max_chunk_length}秒")
        logger.info(f"{'='*70}\n")
        
        # 處理每個檔案
        results = []
        for audio_file in sorted(audio_files):
            result = self.process_audio_file(audio_file, output_dir)
            results.append(result)
        
        # 統計
        total_files = len(results)
        success_files = sum(1 for r in results if r["status"] == "success")
        total_chunks = sum(r.get("chunks", 0) for r in results)
        total_original_duration = sum(r.get("original_duration", 0) for r in results)
        total_speech_duration = sum(r.get("speech_duration", 0) for r in results)
        
        # 儲存處理報告
        report = {
            "timestamp": datetime.now().isoformat(),
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "vad_config": {
                "method": self.vad_method,
                "threshold": self.vad_threshold,
                "min_speech_duration": self.min_speech_duration,
                "min_silence_duration": self.min_silence_duration,
                "max_chunk_length": self.max_chunk_length
            },
            "statistics": {
                "total_files": total_files,
                "success_files": success_files,
                "total_chunks": total_chunks,
                "original_duration": total_original_duration,
                "speech_duration": total_speech_duration,
                "speech_ratio": total_speech_duration / total_original_duration if total_original_duration > 0 else 0
            },
            "files": results
        }
        
        report_path = output_dir / "vad_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # 輸出總結
        logger.info(f"\n{'='*70}")
        logger.info(f"VAD 預處理完成")
        logger.info(f"{'='*70}")
        logger.info(f"處理檔案: {success_files}/{total_files}")
        logger.info(f"生成切段: {total_chunks}")
        logger.info(f"原始總長: {total_original_duration:.2f}秒")
        logger.info(f"語音總長: {total_speech_duration:.2f}秒")
        if total_original_duration > 0:
            logger.info(f"語音比例: {(total_speech_duration/total_original_duration)*100:.1f}%")
        logger.info(f"處理報告: {report_path}")
        logger.info(f"{'='*70}\n")
        
        return report


def main():
    """主程式"""
    parser = argparse.ArgumentParser(
        description="VAD 預處理 - 語音活動檢測與音訊切分 (修正版)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--input-dir", type=Path, required=True, help="輸入音訊目錄")
    parser.add_argument("--output-dir", type=Path, required=True, help="輸出切分音訊目錄")
    parser.add_argument("--vad-method", type=str, default="energy", choices=["energy", "webrtc"], help="VAD 方法")
    parser.add_argument("--vad-threshold", type=float, default=0.5, help="VAD 閾值 (0.5-0.7)")
    parser.add_argument("--min-speech-duration", type=float, default=0.3, help="最短語音段（秒）")
    parser.add_argument("--min-silence-duration", type=float, default=0.5, help="最短靜音段（秒）")
    parser.add_argument("--max-chunk-length", type=float, default=50.0, help="最大切段長度（秒）")
    parser.add_argument("--sample-rate", type=int, default=16000, help="目標取樣率")
    
    args = parser.parse_args()
    
    # 檢查輸入目錄
    if not args.input_dir.exists():
        logger.error(f"❌ 輸入目錄不存在: {args.input_dir}")
        sys.exit(1)
    
    # 創建處理器
    processor = VADPreprocessor(
        vad_method=args.vad_method,
        vad_threshold=args.vad_threshold,
        min_speech_duration=args.min_speech_duration,
        min_silence_duration=args.min_silence_duration,
        max_chunk_length=args.max_chunk_length,
        sample_rate=args.sample_rate
    )
    
    # 處理
    processor.process_directory(args.input_dir, args.output_dir)


if __name__ == "__main__":
    main()