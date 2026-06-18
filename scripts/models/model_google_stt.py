#!/usr/bin/env python3
"""
Google Cloud Speech-to-Text V2 模型包裝器
版本: 3.4 (2026年3月11日)

修正重點:
1. ✅ 正確使用區域端點 ({REGION}-speech.googleapis.com)
2. ✅ 正確的 recognizer 路徑格式
3. ✅ 支援 Chirp 3 完整模型路徑（修正 404 錯誤）
4. ✅ 正確實作 PhraseSet 適應功能（chirp_2/chirp）
5. ✅ 擴展的自動區域回退機制（支援 404 錯誤）
6. ✅ 音訊格式自動轉換（解決 ADPCM 和其他格式問題）
7. ✅ 支援講者辨識（chirp_3 + cmn-Hans-CN，空設定）
8. ✅ 優化的錯誤處理和日誌記錄
9. ✅ chirp_3 跳過 PhraseSet（預設辨識器不支援，會導致 404）
10. ✅ 修正 chirp_2 主要區域誤用 us（location=None 不再強制轉為 us）
11. ✅ DIARIZATION_SUPPORT 字典：依模型+語言自動啟用講者辨識
12. ✅ 修正 _format_diarized_transcript 使用 V2 API 欄位 start_offset（非 V1 的 start_time）

版本歷史:
- v3.4 (2026-03-11): 修正 start_time→start_offset（V2 API），加入 is_config_error 安全防護
- v3.3 (2026-03-11): DIARIZATION_SUPPORT 字典，支援 chirp_3+cmn-Hans-CN 講者辨識
- v3.2 (2026-03-11): 修正 location=None 時不強制 us，改由配置管理器選擇 primary_region
- v3.1 (2026-03-11): chirp_3 不套用 inline PhraseSet（修正全 chunk 404 問題）
- v3.0 (2026-01-27): 修正 Chirp 3 完整模型路徑、擴展回退機制
- v2.0 (2026-01-12): 音訊格式自動轉換、區域端點配置
- v1.0 (2025-12): 初始版本
"""

import os
import sys
import wave
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple

# 修正 import 路徑
if __name__ == "__main__":
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

# ============================================================================
# 內建認證設定（在 import Google Client 之前）
# ============================================================================
def setup_credentials():
    """自動設定 Google Cloud 認證"""
    default_key_path = Path(__file__).parent.parent.parent / "utils" / "google-speech-key.json"
    
    if not os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
        if default_key_path.exists():
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(default_key_path)

# 設定認證
setup_credentials()

from google.cloud.speech_v2 import SpeechClient, SpeechAsyncClient
from google.cloud.speech_v2.types import cloud_speech
from google.api_core.client_options import ClientOptions

try:
    from utils.logger import get_logger
    from utils.google_stt_config_manager import GoogleSTTConfigManager
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from utils.logger import get_logger
    from utils.google_stt_config_manager import GoogleSTTConfigManager


# ============================================================================
# 音訊格式轉換工具
# ============================================================================
class AudioConverter:
    """音訊格式轉換器 - 確保音訊符合 Google STT 要求"""
    
    SUPPORTED_SAMPLE_RATES = [8000, 16000, 32000, 48000]
    TARGET_SAMPLE_RATE = 16000  # Google STT 推薦的取樣率
    
    @staticmethod
    def get_wav_info(audio_path: str) -> Dict:
        """
        讀取 WAV 檔案資訊
        
        Returns:
            dict: {
                'sample_rate': int,
                'channels': int,
                'sample_width': int (bytes),
                'frames': int,
                'duration': float (seconds),
                'encoding': str
            }
        """
        try:
            with wave.open(audio_path, 'rb') as wav:
                return {
                    'sample_rate': wav.getframerate(),
                    'channels': wav.getnchannels(),
                    'sample_width': wav.getsampwidth(),
                    'frames': wav.getnframes(),
                    'duration': wav.getnframes() / wav.getframerate(),
                    'encoding': 'LINEAR16' if wav.getsampwidth() == 2 else f'UNKNOWN_{wav.getsampwidth()*8}bit'
                }
        except Exception as e:
            return {'error': str(e)}
    
    @staticmethod
    def convert_to_linear16(
        input_path: str,
        output_path: str = None,
        target_sample_rate: int = 16000
    ) -> Tuple[str, int]:
        """
        轉換音訊為 LINEAR16 PCM 格式
        
        Args:
            input_path: 輸入音檔路徑
            output_path: 輸出路徑（None 則使用臨時檔案）
            target_sample_rate: 目標取樣率
        
        Returns:
            (output_path, sample_rate)
        """
        if output_path is None:
            temp_fd, output_path = tempfile.mkstemp(suffix='.wav')
            os.close(temp_fd)
        
        # 使用 ffmpeg 轉換
        cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-acodec', 'pcm_s16le',  # LINEAR16
            '-ar', str(target_sample_rate),
            '-ac', '1',  # mono
            output_path
        ]
        
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
            return output_path, target_sample_rate
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"音訊轉換失敗: {e.stderr.decode()}")
    
    @staticmethod
    def needs_conversion(audio_path: str) -> bool:
        """
        檢查音訊是否需要轉換
        
        Returns:
            True if 需要轉換
        """
        info = AudioConverter.get_wav_info(audio_path)
        
        if 'error' in info:
            return True  # 無法讀取，可能需要轉換
        
        # 檢查是否為 LINEAR16, mono, 支援的取樣率
        needs_conv = (
            info['encoding'] != 'LINEAR16' or
            info['channels'] != 1 or
            info['sample_rate'] not in AudioConverter.SUPPORTED_SAMPLE_RATES
        )
        
        return needs_conv


# ============================================================================
# Google STT 模型類別
# ============================================================================
class GoogleSTTModel:
    """
    Google Cloud Speech-to-Text V2 API 包裝器
    支援 Chirp 3, Chirp 2, Chirp 等模型
    """
    
    def __init__(
        self,
        project_id: str,
        location: str = "us-central1",
        model: str = "chirp_2",
        language_code: str = "cmn-Hant-TW",
        auto_convert_audio: bool = True,
        use_config_manager: bool = True
    ):
        """
        初始化 Google STT 模型
        
        Args:
            project_id: Google Cloud 專案 ID
            location: 區域（如 us-central1, asia-southeast1, eu）
            model: 模型名稱（chirp_3, chirp_2, chirp 等）
            language_code: 語言代碼（如 cmn-Hant-TW）
            auto_convert_audio: 是否自動轉換音訊格式
            use_config_manager: 是否使用配置管理器
        """
        self.logger = get_logger(self.__class__.__name__)
        self.project_id = project_id
        # 先暫存 location，讓配置管理器在 location=None 時自行選擇最佳區域
        self.location = location  # 可為 None；配置管理器會決定
        self.model = model
        self.language_code = language_code
        self.auto_convert_audio = auto_convert_audio

        # 初始化配置管理器（如果啟用）
        self.config_manager = None
        if use_config_manager:
            try:
                self.config_manager = GoogleSTTConfigManager(project_id)
                self.logger.info("✅ 使用動態配置管理")

                # 使用配置管理器獲取最佳配置
                # preferred_region=None → 配置管理器依模型選擇 primary_region
                # preferred_region=某區域 → 使用使用者指定的區域
                result_model, result_region, result_endpoint = self.config_manager.get_optimal_config(
                    model=model,
                    preferred_region=location  # None = 讓配置管理器決定最佳區域
                )
                self.location = result_region
                self.model = result_model

            except AttributeError as e:
                self.logger.error(f"❌ 配置管理器方法錯誤: {e}")
                self.logger.error("❌ 請檢查 GoogleSTTConfigManager.get_optimal_config() 方法")
                self.logger.warning("⚠️ 使用預設配置")
                self.config_manager = None
            except Exception as e:
                self.logger.warning(f"⚠️ 配置管理器初始化失敗: {e}")
                self.logger.warning(f"⚠️ 錯誤類型: {type(e).__name__}")
                self.logger.warning("⚠️ 使用預設配置")
                self.config_manager = None

        # 若配置管理器未指定區域（未啟用或失敗），使用安全預設值
        if not self.location:
            self.location = "us-central1"
            self.logger.warning("⚠️ 未指定區域且配置管理器無法設定，預設使用 'us-central1'")
        
        # 設定 API 端點
        api_endpoint = f"{self.location}-speech.googleapis.com"
        client_options = ClientOptions(api_endpoint=api_endpoint)
        
        # 初始化客戶端
        self.client = SpeechClient(client_options=client_options)
        
        # 記錄配置
        self.logger.info("✅ Google STT 初始化成功")
        self.logger.info(f"   專案: {self.project_id}")
        self.logger.info(f"   區域: {self.location}")
        self.logger.info(f"   端點: {api_endpoint}")
        self.logger.info(f"   模型: {self.model}")
        self.logger.info(f"   語言: {self.language_code}")
        self.logger.info(f"   自動轉檔: {'✅ 啟用' if self.auto_convert_audio else '❌ 停用'}")
    
    def _prepare_audio(self, audio_file: str) -> Tuple[bytes, int]:
        """
        準備音訊檔案（必要時自動轉換）
        
        Args:
            audio_file: 音檔路徑
        
        Returns:
            (audio_content, sample_rate)
        """
        audio_path = Path(audio_file)
        
        # 檢查檔案是否存在
        if not audio_path.exists():
            raise FileNotFoundError(f"音檔不存在: {audio_file}")
        
        # 檢查音檔長度
        info = AudioConverter.get_wav_info(str(audio_path))
        if 'duration' in info:
            if info['duration'] > 60:
                self.logger.error(
                    f"音檔長度 {info['duration']:.1f} 秒超過 60 秒限制 (模型： {self.model})"
                )
                raise ValueError(f"音檔長度超過 60 秒限制")
        
        # 檢查是否需要轉換
        if self.auto_convert_audio and AudioConverter.needs_conversion(str(audio_path)):
            self.logger.info("🔄 音訊需要轉換: 格式不相容")
            
            # 轉換音訊
            converted_path, sample_rate = AudioConverter.convert_to_linear16(str(audio_path))
            
            # 讀取轉換後的音訊
            with open(converted_path, 'rb') as f:
                audio_content = f.read()
            
            # 清理臨時檔案
            if converted_path != str(audio_path):
                try:
                    os.unlink(converted_path)
                except Exception:
                    pass
            
            return audio_content, sample_rate
        
        else:
            # 不自動轉換，直接讀取
            with open(audio_file, 'rb') as f:
                audio_content = f.read()
            
            # 嘗試取得取樣率
            info = AudioConverter.get_wav_info(str(audio_path))
            sample_rate = info.get('sample_rate', 16000)
            
            return audio_content, sample_rate
    
    # ============================================================================
    # 模型能力常數
    # ============================================================================
    # 講者辨識支援表：{ 模型名稱: {支援的語言代碼, ...} }
    # - chirp_3 支援 14 種語言的 diarization（官方文件確認）
    #   ✅ cmn-Hans-CN（簡體中文）在支援清單內
    #   ❌ cmn-Hant-TW（繁體中文）目前不在支援清單內
    # - chirp_2 使用預設辨識器 (_) 時 diarization 觸發 400，暫不支援
    DIARIZATION_SUPPORT: dict = {
        'chirp_3': {
            'cmn-Hans-CN',                       # 簡體中文（中國）✅
            'en-US', 'en-GB', 'en-IN',           # 英語
            'de-DE',                              # 德語
            'es-ES', 'es-US',                    # 西班牙語
            'fr-FR', 'fr-CA',                    # 法語
            'hi-IN',                              # 印地語
            'it-IT', 'ja-JP', 'ko-KR', 'pt-BR',  # 義/日/韓/葡
        },
        # chirp_2 未來若改用具名辨識器可再加入，格式同上
    }

    # chirp_3 diarization 使用空設定（官方文件規定，不填 min/max speaker count）
    # 其他未來模型若需指定 min/max 則不加入此集合
    EMPTY_DIARIZATION_CONFIG_MODELS: set = {'chirp_3'}

    @staticmethod
    def _format_diarized_transcript(results) -> str:
        """
        將含講者標記的辨識結果格式化為易讀文字。

        輸出格式（每換一位講者輸出一行）：
            【講者A ｜ MM:SS】文字內容...
            【講者B ｜ MM:SS】文字內容...

        Args:
            results: Google STT V2 response.results

        Returns:
            格式化後的字串；若無詞彙資料則回傳空字串

        Note:
            V2 API 欄位名稱為 start_offset（V1 為 start_time），
            但 Python google-cloud-speech 已將 protobuf Duration 包裝為 datetime.timedelta，
            故呼叫方式與 V1 相同：so.total_seconds()，只有欄位名稱不同。
        """
        all_words = []
        for result in results:
            if not result.alternatives:
                continue
            alt = result.alternatives[0]
            for w in alt.words:
                spk = getattr(w, 'speaker_label', '') or '1'
                # ✅ V2 API 欄位名稱改為 start_offset（V1 為 start_time），
                #    Python client 已將 protobuf Duration 包裝為 datetime.timedelta，
                #    因此直接呼叫 .total_seconds() 即可。
                so = getattr(w, 'start_offset', None)
                if so is not None:
                    start_secs = so.total_seconds()
                else:
                    start_secs = 0.0
                all_words.append({
                    'word':    w.word,
                    'start':   start_secs,
                    'speaker': spk,
                })

        if not all_words:
            return ''

        # 按起始時間排序（跨 result 的詞可能不連續）
        all_words.sort(key=lambda x: x['start'])

        # 將連續相同講者的詞合併為一行
        lines = []
        cur_speaker: str | None = None
        cur_words: list = []
        cur_start: float = 0.0

        for w in all_words:
            if w['speaker'] != cur_speaker:
                if cur_words:
                    mm = int(cur_start // 60)
                    ss = int(cur_start % 60)
                    lines.append(
                        f"【講者{cur_speaker} ｜ {mm:02d}:{ss:02d}】{''.join(cur_words)}"
                    )
                cur_speaker = w['speaker']
                cur_words   = [w['word']]
                cur_start   = w['start']
            else:
                cur_words.append(w['word'])

        # 最後一組
        if cur_words:
            mm = int(cur_start // 60)
            ss = int(cur_start % 60)
            lines.append(
                f"【講者{cur_speaker} ｜ {mm:02d}:{ss:02d}】{''.join(cur_words)}"
            )

        return '\n'.join(lines)

    def transcribe_file(
        self,
        audio_file: str,
        phrases: List[Dict] = None,
        enable_word_time_offsets: bool = True,
        enable_automatic_punctuation: bool = True,
        **kwargs  # 接收並忽略不支援的參數（如 diarization）
    ) -> Dict:
        """
        辨識音檔（完整優化版 v3.0）
        
        Args:
            audio_file: 音檔路徑
            phrases: 詞彙表列表 [{"value": "詞彙", "boost": 10}, ...]
            enable_word_time_offsets: 是否啟用字詞時間戳
            enable_automatic_punctuation: 是否啟用自動標點符號
            **kwargs: 其他參數（會被忽略，如 speaker diarization 相關）
        
        Returns:
            辨識結果字典: {
                'transcript': str,
                'transcript_raw': str,
                'confidence': float,
                'results': list (optional),
                'error': str (optional)
            }
        """
        # audio_seconds for cost ledger (Phase A 2026-05-08)
        try:
            from utils.audio_duration import audio_seconds as _audio_sec, AudioDurationError
            _duration = _audio_sec(audio_file)
        except (AudioDurationError, Exception):
            _duration = 0.0

        try:
            # 準備音訊（必要時自動轉換）
            audio_content, sample_rate = self._prepare_audio(audio_file)
            
            # ====================================================================
            # Recognizer 路徑（V2 API 標準格式）
            # ====================================================================
            recognizer_path = (
                f"projects/{self.project_id}/locations/{self.location}/recognizers/_"
            )
            
            self.logger.debug(f"Recognizer 路徑: {recognizer_path}")
            
            # ====================================================================
            # 音訊編碼配置
            # ====================================================================
            explicit_decoding = cloud_speech.ExplicitDecodingConfig(
                encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=sample_rate,
                audio_channel_count=1
            )
            
            # ====================================================================
            # 🔧 修正: 智慧模型路徑選擇
            # ====================================================================
            # 所有 Chirp 系列模型均使用簡短名稱，不使用完整路徑
            # chirp_3 使用完整路徑會導致 "model does not exist" 400 錯誤
            # 參考: https://cloud.google.com/speech-to-text/v2/docs/chirp-model

            # 定義使用簡短名稱的模型列表（所有已知模型均用簡短名稱）
            short_name_models = ['chirp', 'chirp_2', 'chirp_3', 'chirp_telephony', 'latest_short', 'latest_long', 'telephony']

            if self.model in short_name_models:
                # 使用簡短模型名稱
                model_path = self.model
                self.logger.debug(f"使用簡短模型名稱: {model_path}")
            else:
                # 使用完整模型路徑（自定義模型）
                model_path = f"projects/{self.project_id}/locations/{self.location}/models/{self.model}"
                self.logger.debug(f"使用完整模型路徑: {model_path}")
            
            # ====================================================================
            # Recognition 配置
            # ====================================================================
            # 判斷此模型 + 語言組合是否支援講者辨識
            supported_langs = self.DIARIZATION_SUPPORT.get(self.model, set())
            has_diarization = self.language_code in supported_langs

            # 構建 RecognitionFeatures（diarization 需要 word time offsets）
            features_kwargs = dict(
                enable_word_time_offsets=enable_word_time_offsets or has_diarization,
                enable_automatic_punctuation=enable_automatic_punctuation,
            )
            if has_diarization:
                if self.model in self.EMPTY_DIARIZATION_CONFIG_MODELS:
                    # chirp_3：官方文件規定使用空設定（不帶 min/max speaker count）
                    features_kwargs['diarization_config'] = cloud_speech.SpeakerDiarizationConfig()
                    self.logger.debug(
                        f"✅ 啟用講者辨識（{self.model} + {self.language_code}，空設定）"
                    )
                else:
                    # 其他模型：使用 min/max speaker count
                    features_kwargs['diarization_config'] = cloud_speech.SpeakerDiarizationConfig(
                        min_speaker_count=1,
                        max_speaker_count=6,
                    )
                    self.logger.debug(
                        f"✅ 啟用講者辨識（{self.model} + {self.language_code}，最多 6 位）"
                    )

            config = cloud_speech.RecognitionConfig(
                explicit_decoding_config=explicit_decoding,
                language_codes=[self.language_code],
                model=model_path,
                features=cloud_speech.RecognitionFeatures(**features_kwargs),
            )
            
            # ====================================================================
            # 詞彙表配置（PhraseSet Adaptation）
            # ====================================================================
            # chirp_3 使用預設辨識器 (_) 時不支援 inline PhraseSet adaptation：
            # 強制加入 config.adaptation 會導致「404 Requested entity was not found」
            # 在所有區域（us / eu / asia-northeast1 等）一律失敗。
            # 解決方案：chirp_3 略過第一層（PhraseSet），
            #           第二層後處理詞彙修正仍照常執行。
            ADAPTATION_INCOMPATIBLE_MODELS = {'chirp_3'}

            if phrases and len(phrases) > 0 and self.model in ADAPTATION_INCOMPATIBLE_MODELS:
                self.logger.warning(
                    f"⚠️ 模型 '{self.model}' 不支援 inline PhraseSet（預設辨識器限制）"
                )
                self.logger.warning(
                    "   → 跳過第一層詞彙（PhraseSet），保留第二層後處理修正"
                )

            elif phrases and len(phrases) > 0:
                # 保留 value + boost 兩個欄位，以便正確傳遞個別 boost 值
                phrase_objects = []
                for phrase_dict in phrases:
                    if isinstance(phrase_dict, dict) and 'value' in phrase_dict:
                        phrase_objects.append({
                            'value': phrase_dict['value'],
                            'boost': float(phrase_dict.get('boost', 10)),
                        })
                    elif isinstance(phrase_dict, str):
                        phrase_objects.append({'value': phrase_dict, 'boost': 10.0})

                if phrase_objects:
                    # 限制數量（chirp_2 / chirp 最多 500 個）
                    phrase_objects = phrase_objects[:500]

                    # 使用 inline adaptation（正確的 V2 API 方式）
                    # 使用每個詞彙的實際 boost 值，不再硬寫 boost=10
                    config.adaptation = cloud_speech.SpeechAdaptation(
                        phrase_sets=[
                            cloud_speech.SpeechAdaptation.AdaptationPhraseSet(
                                inline_phrase_set=cloud_speech.PhraseSet(
                                    phrases=[
                                        cloud_speech.PhraseSet.Phrase(
                                            value=p['value'],
                                            boost=p['boost'],
                                        )
                                        for p in phrase_objects
                                    ]
                                )
                            )
                        ]
                    )

                    self.logger.debug(f"✅ 載入 {len(phrase_objects)} 個詞彙提示（boost 範圍: "
                                      f"{min(p['boost'] for p in phrase_objects):.0f}"
                                      f"–{max(p['boost'] for p in phrase_objects):.0f}）")
            
            # ====================================================================
            # 建立辨識請求
            # ====================================================================
            request = cloud_speech.RecognizeRequest(
                recognizer=recognizer_path,
                config=config,
                content=audio_content
            )
            
            # ====================================================================
            # 執行辨識 (chirp_3 自動切換 long-running)
            # ====================================================================
            self.logger.debug(f"發送辨識請求: {Path(audio_file).name}")
            response = self.client.recognize(request=request)
            
            # ====================================================================
            # 處理辨識結果
            # ====================================================================
            if not response.results:
                self.logger.warning(f"辨識結果為空: {audio_file}")
                return {
                    'transcript': '',
                    'transcript_raw': '',
                    'confidence': 0.0,
                    'has_diarization': has_diarization,
                    'audio_seconds': _duration,
                }

            if has_diarization:
                # ── 講者辨識模式：輸出「【講者X ｜ MM:SS】文字」格式 ──
                transcript = self._format_diarized_transcript(response.results)
                # 同時保留原始純文字（不含格式）供後處理使用
                transcript_raw = ''.join(
                    alt.transcript
                    for result in response.results
                    if result.alternatives
                    for alt in [result.alternatives[0]]
                )
                self.logger.debug(
                    f"✅ 辨識成功（講者辨識）: {Path(audio_file).name}"
                )
                return {
                    'transcript': transcript,
                    'transcript_raw': transcript_raw,
                    'confidence': 0.0,      # diarization 不計算整體信心度
                    'results': response.results,
                    'has_diarization': True,
                    'audio_seconds': _duration,
                }

            # ── 一般模式：提取文字和信心度 ────────────────────────────
            transcript = ''
            confidence_sum = 0.0
            word_count = 0

            for result in response.results:
                if result.alternatives:
                    alternative = result.alternatives[0]
                    transcript += alternative.transcript
                    confidence_sum += alternative.confidence
                    word_count += 1

            avg_confidence = confidence_sum / word_count if word_count > 0 else 0.0

            self.logger.debug(f"✅ 辨識成功: {Path(audio_file).name} (信心度: {avg_confidence:.2%})")

            return {
                'transcript': transcript,
                'transcript_raw': transcript,
                'confidence': avg_confidence,
                'results': response.results,
                'has_diarization': False,
                'audio_seconds': _duration,
            }
        
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"❌ 辨識失敗 ({Path(audio_file).name}): {error_msg}")
            
            # ====================================================================
            # 🔧 擴展的區域回退機制（解決 404 / 區域不支援錯誤）
            # ====================================================================
            # 「配置本身不支援」的 400 錯誤是全域性問題，換區域也沒用，直接跳過回退。
            is_config_error = (
                "unsupported fields" in error_msg or           # 功能不在預設辨識器支援清單
                "does not support feature" in error_msg or     # 如 diarization_config
                "Unknown field for WordInfo" in error_msg or   # 客戶端解析錯誤（欄位名稱錯誤），換區域無效
                "has no attribute 'nanos'" in error_msg        # timedelta 當 Duration 存取，客戶端程式碼錯誤
            )
            # 「區域不支援此模型」或「找不到資源」才觸發回退
            should_fallback = (
                not is_config_error and
                self.config_manager and (
                    "does not exist in the location" in error_msg or
                    "404" in error_msg or
                    "Requested entity was not found" in error_msg or
                    "not found" in error_msg.lower()
                )
            )
            
            if should_fallback:
                self.logger.warning(f"🔄 觸發區域回退機制")
                return self._try_fallback_regions(audio_file, phrases, enable_word_time_offsets, enable_automatic_punctuation, e)
            
            # 回傳錯誤資訊
            return {
                'transcript': '',
                'transcript_raw': '',
                'confidence': 0.0,
                'error': error_msg,
                'audio_seconds': 0.0,
            }
    
    # =========================================================================
    # 即時串流辨識（Google STT V2 streaming_recognize）
    # =========================================================================

    async def stream_recognize(
        self,
        audio_queue:    "asyncio.Queue[bytes]",
        result_queue:   "asyncio.Queue[dict]",
        stop_event:     "asyncio.Event",
        max_chunk_bytes: int = 24000,   # ≤25KB；16kHz mono 約 0.75 秒
        reconnect_secs:  int = 10,      # Google STT V2 chirp_3 只在串流關閉時回傳結果；
                                        # 縮短為 10 秒讓每個 window 都能拿到辨識文字。
                                        # （Google 單次串流上限 5 分鐘；10 秒遠低於此限制）
    ) -> None:
        """
        持續從 audio_queue 讀取 PCM bytes，透過 Google STT V2
        streaming_recognize() 串流辨識，將結果放入 result_queue。

        設計說明：
            - 使用 SpeechAsyncClient（原生 asyncio，避免 to_thread 包裝）
            - 第一個 request 只含 config，後續 request 只含音訊（V2 規定）
            - 自動每 reconnect_secs 秒重連一次（Google 限制單次串流 5 分鐘）
            - 修復已知 metadata bug：必須手動傳入 x-goog-request-params header
              （未傳入時 interim_results=True 會導致永久 blocking/timeout）

        Args:
            audio_queue:     外部傳入 PCM bytes 的 asyncio.Queue
                             每筆資料為任意長度的 bytes，內部會自動切成 ≤25KB chunk
            result_queue:    辨識結果輸出 asyncio.Queue，每筆格式：
                             {
                                 "type":       "partial" | "final",
                                 "text":       str,       # 辨識文字
                                 "confidence": float,     # 信心值（0.0–1.0）
                             }
            stop_event:      設定後結束串流（asyncio.Event）
            max_chunk_bytes: 每個 streaming request 的最大音訊大小（預設 24KB）
            reconnect_secs:  每次串流視窗長度（預設 10 秒）。
                             chirp_3 streaming 只在串流關閉時回傳結果，
                             縮短視窗可降低辨識延遲。Google 上限 5 分鐘。

        使用方式（在 FastAPI 的 asyncio 環境中）：
            audio_q  = asyncio.Queue()
            result_q = asyncio.Queue()
            stop_ev  = asyncio.Event()

            # 啟動串流辨識任務
            task = asyncio.create_task(
                stt.stream_recognize(audio_q, result_q, stop_ev)
            )

            # 送入音訊
            await audio_q.put(pcm_bytes)

            # 讀取結果
            result = await result_q.get()
            # {"type": "partial", "text": "你好", "confidence": 0.0}
            # {"type": "final",   "text": "你好世界", "confidence": 0.92}

            # 結束
            stop_ev.set()
            await task

        ⚠️  已知問題與解決方案：
            Bug 1（metadata 缺失）：
                V2 Python client 不自動注入 x-goog-request-params header，
                導致 interim_results=True 時串流永久 blocking。
                → 已修復：metadata 參數手動傳入 recognizer 路徑。

            Bug 2（cmn 系列 CANCELLED）：
                cmn-Hans-CN 已知串流 CANCELLED，cmn-Hant-TW 存在相同風險。
                → 建議：串流使用 Chirp 2；Chirp 3 用於批次確認。
        """
        import asyncio as _asyncio

        recognizer = (
            f"projects/{self.project_id}/locations/{self.location}/recognizers/_"
        )
        # ── metadata bug 修復：必須手動傳入此 header ──────────────────────────
        metadata = [("x-goog-request-params", f"recognizer={recognizer}")]

        api_endpoint = f"{self.location}-speech.googleapis.com"
        client_opts  = ClientOptions(api_endpoint=api_endpoint)

        def _build_config_request() -> cloud_speech.StreamingRecognizeRequest:
            """建立只含 config 的第一個 request（V2 規定：第一個 request 不含音訊）。"""
            rec_config = cloud_speech.RecognitionConfig(
                explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
                    encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=16000,
                    audio_channel_count=1,
                ),
                language_codes=[self.language_code],
                model=self.model,
                features=cloud_speech.RecognitionFeatures(
                    enable_automatic_punctuation=True,
                ),
            )
            streaming_cfg = cloud_speech.StreamingRecognitionConfig(
                config=rec_config,
                streaming_features=cloud_speech.StreamingRecognitionFeatures(
                    interim_results=True,   # 啟用邊說邊出字；須搭配 metadata 修復
                ),
            )
            return cloud_speech.StreamingRecognizeRequest(
                recognizer=recognizer,
                streaming_config=streaming_cfg,
            )

        async def _request_generator(pending_chunks: list):
            """
            非同步 request 產生器：
                第 1 個 yield → config request（無音訊）
                後續 yield   → 音訊 request（從 audio_queue 持續取資料）
            """
            # ── 第一個 request：config only ──
            self.logger.debug("[stream_recognize] generator: 送出 config request")
            yield _build_config_request()

            # ── 若有前一輪未送完的暫存 chunks ──
            for chunk in pending_chunks:
                for i in range(0, len(chunk), max_chunk_bytes):
                    yield cloud_speech.StreamingRecognizeRequest(
                        audio=chunk[i : i + max_chunk_bytes]
                    )

            # ── 持續從佇列讀取並送出音訊 ──
            audio_chunk_count = 0
            deadline = _asyncio.get_event_loop().time() + reconnect_secs
            while not stop_event.is_set():
                remaining = deadline - _asyncio.get_event_loop().time()
                if remaining <= 0:
                    self.logger.debug(
                        f"[stream_recognize] {reconnect_secs}s 視窗結束，"
                        f"共送 {audio_chunk_count} chunk，關閉串流等待回傳結果…"
                    )
                    break
                try:
                    pcm = await _asyncio.wait_for(
                        audio_queue.get(), timeout=min(1.0, remaining)
                    )
                    audio_chunk_count += 1
                    if audio_chunk_count <= 3 or audio_chunk_count % 20 == 0:
                        self.logger.debug(
                            f"[stream_recognize] generator: 送出第 {audio_chunk_count} 個音訊 chunk"
                            f"（{len(pcm)} bytes）"
                        )
                    for i in range(0, len(pcm), max_chunk_bytes):
                        yield cloud_speech.StreamingRecognizeRequest(
                            audio=pcm[i : i + max_chunk_bytes]
                        )
                except _asyncio.TimeoutError:
                    continue
            self.logger.debug(
                f"[stream_recognize] generator 結束，共送出 {audio_chunk_count} 個音訊 chunk"
            )

        # ── 主迴圈：自動重連 ────────────────────────────────────────────────
        pending: list[bytes] = []

        async with SpeechAsyncClient(client_options=client_opts) as async_client:
            while not stop_event.is_set():
                try:
                    self.logger.debug(
                        f"[stream_recognize] 發起 streaming_recognize："
                        f" model={self.model} lang={self.language_code}"
                        f" recognizer={recognizer}"
                    )
                    responses = await async_client.streaming_recognize(
                        requests=_request_generator(pending),
                        metadata=metadata,      # ← metadata bug 修復關鍵
                    )
                    pending = []  # 重連成功，清空暫存
                    self.logger.debug(
                        f"[stream_recognize] streaming_recognize() 已回傳，"
                        f"responses 型別={type(responses).__name__}，開始迭代…"
                    )

                    response_count = 0
                    result_count   = 0
                    async for response in responses:
                        response_count += 1
                        self.logger.debug(
                            f"[stream_recognize] 收到第 {response_count} 個 response，"
                            f"results={len(response.results)}"
                        )
                        for result in response.results:
                            result_count += 1
                            alts = result.alternatives
                            text_raw = alts[0].transcript if alts else ""
                            self.logger.debug(
                                f"[stream_recognize] result #{result_count}："
                                f" is_final={result.is_final}"
                                f" alternatives={len(alts)}"
                                f" text='{text_raw[:40]}'"
                            )
                            if not alts:
                                continue
                            text = text_raw.strip()
                            if not text:
                                continue
                            is_final = result.is_final
                            await result_queue.put({
                                "type":       "final" if is_final else "partial",
                                "text":       text,
                                "confidence": float(alts[0].confidence or 0.0),
                            })

                    self.logger.debug(
                        f"[stream_recognize] async for 結束："
                        f" responses={response_count}  results={result_count}"
                    )

                except Exception as exc:
                    err_str = str(exc)
                    self.logger.warning(f"⚠️  Google STT 串流中斷：{err_str}")
                    # 把錯誤訊息送入 result_queue，讓消費端推播前端
                    await result_queue.put({
                        "type":    "error",
                        "text":    f"Google STT 串流錯誤：{err_str}",
                        "confidence": 0.0,
                    })
                    if stop_event.is_set():
                        break
                    # 短暫等待後重連（避免瞬間過多重連）
                    await _asyncio.sleep(2.0)

        self.logger.info("✅ Google STT stream_recognize() 已結束")

    def _try_fallback_regions(self, audio_file, phrases, enable_word_time_offsets, enable_automatic_punctuation, original_error):
        """
        嘗試使用回退區域
        
        Args:
            audio_file: 音檔路徑
            phrases: 詞彙表
            enable_word_time_offsets: 字詞時間戳
            enable_automatic_punctuation: 自動標點
            original_error: 原始錯誤
        
        Returns:
            辨識結果或拋出錯誤
        """
        self.logger.warning(f"⚠️ 當前區域 '{self.location}' 失敗，嘗試回退區域...")
        
        if not self.config_manager:
            raise original_error
        
        # 獲取回退區域列表
        fallback_regions = self.config_manager.get_fallback_regions(self.model)
        
        if not fallback_regions:
            self.logger.error("❌ 沒有可用的回退區域")
            raise original_error
        
        # 嘗試每個回退區域
        for fallback_region in fallback_regions:
            if fallback_region == self.location:
                continue  # 跳過當前區域
            
            self.logger.info(f"🔄 嘗試回退區域: {fallback_region}")
            
            try:
                # 使用回退區域重新初始化
                fallback_model = GoogleSTTModel(
                    project_id=self.project_id,
                    location=fallback_region,
                    model=self.model,
                    language_code=self.language_code,
                    auto_convert_audio=self.auto_convert_audio,
                    use_config_manager=False  # 避免遞迴
                )
                
                # 重新嘗試辨識
                result = fallback_model.transcribe_file(
                    audio_file,
                    phrases=phrases,
                    enable_word_time_offsets=enable_word_time_offsets,
                    enable_automatic_punctuation=enable_automatic_punctuation
                )
                
                if 'error' not in result:
                    self.logger.info(f"✅ 回退成功: 使用區域 {fallback_region}")
                    # 🔧 Sticky fallback：更新 self.location 與 self.client，
                    #    讓後續 chunk 直接用成功的區域，避免每次重試失敗區域
                    self.location = fallback_region
                    new_endpoint = f"{fallback_region}-speech.googleapis.com"
                    self.client = SpeechClient(
                        client_options=ClientOptions(api_endpoint=new_endpoint)
                    )
                    self.logger.info(f"   → 已將主要區域切換至 {fallback_region}，後續 chunk 直接使用")
                    return result

            except Exception as e:
                self.logger.warning(f"⚠️ 回退區域 {fallback_region} 也失敗: {e}")
                continue
        
        # 所有回退都失敗
        self.logger.error("❌ 所有回退區域都失敗")
        raise original_error


# ============================================================================
# 測試程式
# ============================================================================
def test_google_stt():
    """測試 Google STT（修正版 v3.0）"""
    print("\n測試 Google STT（完整優化版 v3.0）")
    print("=" * 80)
    
    # 測試參數
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "dazzling-seat-315406")
    
    # 測試配置
    test_configs = [
        {
            "name": "Chirp 3 @ asia-southeast1",
            "location": "asia-southeast1",
            "model": "chirp_3"
        },
        {
            "name": "Chirp 2 @ asia-southeast1",
            "location": "asia-southeast1",
            "model": "chirp_2"
        },
        {
            "name": "Chirp 2 @ us-central1",
            "location": "us-central1",
            "model": "chirp_2"
        }
    ]
    
    for config in test_configs:
        print(f"\n{'='*80}")
        print(f"測試配置: {config['name']}")
        print(f"{'='*80}")
        
        try:
            model = GoogleSTTModel(
                project_id=project_id,
                location=config['location'],
                model=config['model'],
                language_code="cmn-Hant-TW",
                auto_convert_audio=True,
                use_config_manager=True
            )
            
            print(f"\n當前 Google STT 配置:")
            print(f"  專案ID: {model.project_id}")
            print(f"  區域: {model.location}")
            print(f"  端點: {model.location}-speech.googleapis.com")
            print(f"  模型: {model.model}")
            print(f"  語言: {model.language_code}")
            print(f"  動態配置: {'✅ 啟用' if model.config_manager else '❌ 停用'}")
            print(f"  自動轉檔: {'✅ 啟用' if model.auto_convert_audio else '❌ 停用'}")
            
            # 檢查認證
            cred_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
            if cred_path:
                print(f"  認證設定: ✅ 已設定")
                print(f"  金鑰路徑: {cred_path}")
            else:
                print(f"  認證設定: ❌ 未設定")
            
            print(f"✅ 模型初始化成功")
            
        except Exception as e:
            print(f"❌ 初始化失敗: {e}")
    
    print(f"\n{'='*80}")
    print("測試完成")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    test_google_stt()