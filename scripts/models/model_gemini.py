"""
Google Gemini 模型模組
(2026/3/11 更新)

支援功能:
- gemini-2.5-flash / gemini-2.5-pro / gemini-2.5-flash-lite（當前主力）
- gemini-2.0-flash（穩定版，2026/6/1 停用）
- 檔案上傳 (File API)
- 帶上下文辨識
- 自定義提示詞
- 自動從 utils/api_keys.py 或 utils/api_keys.json 讀取 API key

注意：gemini-1.5-pro / gemini-1.5-flash 已完全下線，呼叫會回傳 404 錯誤。
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional
import os

import google.generativeai as genai

# 修正後的 logger 導入（加入 fallback 機制）
try:
    from utils.logger import get_logger
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    def get_logger(name):
        return logging.getLogger(name)

logger = get_logger('gemini')


class GeminiModel:
    """Google Gemini 模型封裝"""
    
    # 支援的模型（2026/3 更新）
    # gemini-1.5-pro / gemini-1.5-flash 已完全下線，呼叫回傳 404
    # gemini-2.0-flash 穩定版 2026/6/1 停用
    MODELS = {
        'gemini-2.5-flash':      'gemini-2.5-flash',       # ⭐ 推薦：最佳價格/性能
        'gemini-2.5-pro':        'gemini-2.5-pro',         # 最高準確度
        'gemini-2.5-flash-lite': 'gemini-2.5-flash-lite',  # 最快、最省費
        'gemini-2.0-flash':      'gemini-2.0-flash',       # 穩定版（2026/6/1 停用）
        'gemini-2.0-flash-exp':  'gemini-2.0-flash-exp',   # 實驗版（即將停用）
    }
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.0-flash-exp",
        temperature: float = 0.0
    ):
        """
        初始化 Gemini 模型
        
        Args:
            api_key: Gemini API 金鑰
            model: 模型名稱
            temperature: 溫度參數 (0.0-1.0，0.0 為最確定性)
        
        API Key 載入優先順序：
        1. 直接傳入的 api_key 參數
        2. 環境變數 GEMINI_API_KEY
        3. utils/api_keys.json 配置檔案 ⭐ JSON 支援
        4. utils/api_keys.py 配置檔案
        
        """
        self.model_name = model
        self.temperature = temperature
        
        # 取得 API 金鑰（多層級 fallback）
        api_key = self._get_api_key(api_key)
        
        # 設定 API
        genai.configure(api_key=api_key)
        
        # 初始化模型
        try:
            model_identifier = self.MODELS.get(model, model)
            self.model = genai.GenerativeModel(
                model_name=model_identifier,
                generation_config={
                    'temperature': temperature,
                    'top_p': 0.95,
                    'top_k': 40,
                    'max_output_tokens': 8192,
                }
            )
            
            logger.info(f"Gemini 模型初始化成功")
            logger.info(f"  模型: {model_identifier}")
            logger.info(f"  溫度: {temperature}")
            
        except Exception as e:
            logger.error(f"初始化 Gemini 模型失敗: {e}")
            raise
    
    def _get_api_key(self, api_key: Optional[str] = None) -> str:
        """
        取得 API 金鑰（多層級 fallback）
        
        優先順序：
        1. 直接傳入的參數
        2. 環境變數 GEMINI_API_KEY
        3. utils/api_keys.json 配置檔案 ⭐ 新增
        4. utils/api_keys.py 配置檔案
        
        Returns:
            API 金鑰字串
        
        Raises:
            ValueError: 所有方式都無法取得 API 金鑰
        """
        # 優先級 1: 直接傳入的參數
        if api_key is not None:
            logger.info("✅ 使用傳入的 API key")
            return api_key
        
        # 優先級 2: 環境變數
        api_key = os.environ.get('GEMINI_API_KEY')
        if api_key is not None:
            logger.info("✅ 使用環境變數 GEMINI_API_KEY")
            return api_key
        
        # 優先級 3: utils/api_keys.json 配置檔案
        try:
            # 嘗試多個可能的路徑
            possible_json_paths = [
                Path(__file__).parent.parent / "utils" / "api_keys.json",
                Path("utils/api_keys.json"),
                Path("../utils/api_keys.json"),
            ]
            
            for json_path in possible_json_paths:
                if json_path.exists():
                    with open(json_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    
                    api_key = config.get('GEMINI_API_KEY')
                    if api_key:
                        logger.info(f"✅ 從 {json_path.name} 載入 API key")
                        return api_key
        
        except FileNotFoundError:
            logger.debug("utils/api_keys.json 不存在，跳過")
        except json.JSONDecodeError as e:
            logger.warning(f"utils/api_keys.json 格式錯誤: {e}")
        except Exception as e:
            logger.warning(f"從 utils/api_keys.json 讀取失敗: {e}")
        
        # 優先級 4: utils/api_keys.py 配置檔案（向後相容）
        try:
            from utils.api_keys import get_gemini_api_key
            api_key = get_gemini_api_key()
            if api_key:
                logger.info("✅ 從 utils/api_keys.py 載入 API key")
                return api_key
        except ImportError:
            logger.debug("utils/api_keys.py 不存在，跳過")
        except Exception as e:
            logger.warning(f"從 utils/api_keys.py 讀取失敗: {e}")
        
        # 所有方式都失敗，拋出錯誤
        raise ValueError(
            "無法取得 Gemini API 金鑰！請使用以下任一方式設定：\n"
            "1. 直接傳入參數：GeminiModel(api_key='your-key')\n"
            "2. 設定環境變數：export GEMINI_API_KEY='your-key'\n"
            "3. 建立 utils/api_keys.json 檔案（推薦）\n"
            "4. 建立 utils/api_keys.py 配置檔案"
        )
    
    def upload_audio_file(self, audio_file: str, display_name: Optional[str] = None) -> object:
        """
        上傳音檔到 Gemini File API
        
        Args:
            audio_file: 音檔路徑
            display_name: 顯示名稱 (可選)
        
        Returns:
            上傳的檔案物件
        """
        audio_path = Path(audio_file)
        if not audio_path.exists():
            raise FileNotFoundError(f"音檔不存在: {audio_file}")
        
        if display_name is None:
            display_name = audio_path.name
        
        try:
            # 上傳檔案
            logger.info(f"正在上傳音檔: {audio_path.name}")
            uploaded_file = genai.upload_file(
                path=str(audio_path),
                display_name=display_name
            )
            
            logger.info(f"檔案上傳成功: {uploaded_file.name}")
            
            # 等待檔案處理完成
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(1)
                uploaded_file = genai.get_file(uploaded_file.name)
            
            if uploaded_file.state.name == "FAILED":
                raise Exception(f"檔案處理失敗: {uploaded_file.state.name}")
            
            logger.info(f"檔案處理完成，可以開始辨識")
            
            return uploaded_file
            
        except Exception as e:
            logger.error(f"上傳音檔失敗: {e}")
            raise
    
    def transcribe_file(
        self,
        audio_file: str,
        prompt: Optional[str] = None,
        context: Optional[str] = None
    ) -> Dict:
        """
        辨識音檔
        
        Args:
            audio_file: 音檔路徑
            prompt: 自定義提示詞 (可選)
            context: 上下文資訊 (可選)
        
        Returns:
            辨識結果字典:
            {
                'transcript': '完整逐字稿',
                'transcript_raw': '未經修正的原始逐字稿',
                'model': 模型名稱
            }
        """
        # 上傳檔案
        uploaded_file = self.upload_audio_file(audio_file)
        
        # 建立提示詞
        if prompt is None:
            prompt = self._create_default_prompt(context)
        
        try:
            # 生成內容
            logger.info(f"正在進行語音辨識...")
            response = self.model.generate_content([
                uploaded_file,
                prompt
            ])
            
            # 提取逐字稿
            transcript = response.text.strip()
            
            # 清理可能的 Markdown 格式
            if transcript.startswith('```') and transcript.endswith('```'):
                # 移除 Markdown code block
                lines = transcript.split('\n')
                transcript = '\n'.join(lines[1:-1]).strip()
            
            logger.info(f"辨識完成: {Path(audio_file).name}")
            logger.info(f"  逐字稿: {transcript[:50]}...")
            
            # 刪除已上傳的檔案 (節省配額)
            try:
                genai.delete_file(uploaded_file.name)
                logger.debug(f"已刪除上傳的檔案: {uploaded_file.name}")
            except:
                pass
            
            return {
                'transcript': transcript,
                'transcript_raw': transcript,
                'model': self.model_name
            }
            
        except Exception as e:
            logger.error(f"辨識失敗 ({audio_file}): {e}")
            
            # 嘗試刪除檔案
            try:
                genai.delete_file(uploaded_file.name)
            except:
                pass
            
            raise
    
    def _create_default_prompt(self, context: Optional[str] = None) -> str:
        """建立預設提示詞"""
        base_prompt = """請將這段音訊轉錄為繁體中文逐字稿。

重要規則：
1. 只輸出逐字稿文字，不要包含任何說明、註解或 Markdown 格式
2. 保持原始語序，不要改寫或摘要
3. 數字使用阿拉伯數字（如：119、101）
4. 專有名詞請保持原樣（如：OCC、R13、VVVF）
5. 不要添加標點符號，除非語氣明確停頓
"""
        
        if context:
            base_prompt += f"\n背景資訊：\n{context}\n"
        
        return base_prompt
    
    def batch_transcribe_files(
        self,
        audio_files: List[str],
        output_dir: str,
        prompt: Optional[str] = None,
        context: Optional[str] = None
    ) -> Dict[str, Dict]:
        """
        批次辨識多個音檔
        
        Args:
            audio_files: 音檔路徑列表
            output_dir: 輸出目錄
            prompt: 自定義提示詞
            context: 上下文資訊
        
        Returns:
            辨識結果字典，key 為 chunk_id
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        results = {}
        
        for i, audio_file in enumerate(audio_files, 1):
            logger.info(f"正在處理 [{i}/{len(audio_files)}]: {Path(audio_file).name}")
            
            try:
                result = self.transcribe_file(
                    audio_file,
                    prompt=prompt,
                    context=context
                )
                
                # 取得 chunk_id (從檔名)
                chunk_id = Path(audio_file).stem
                results[chunk_id] = result
                
                # 儲存文字檔
                txt_file = output_path / f"{chunk_id}.txt"
                with open(txt_file, 'w', encoding='utf-8') as f:
                    f.write(result['transcript'])
                
                # 加入延遲，避免超過 API 速率限制
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"處理失敗 ({audio_file}): {e}")
                chunk_id = Path(audio_file).stem
                results[chunk_id] = {
                    'transcript': '',
                    'transcript_raw': '',
                    'model': self.model_name,
                    'error': str(e)
                }
                
                # 發生錯誤時等待更長時間
                time.sleep(3)
        
        # 儲存完整結果 JSON
        json_file = output_path / "gemini_results_full.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        logger.info(f"批次辨識完成，結果已儲存至: {output_dir}")
        logger.info(f"  成功: {sum(1 for r in results.values() if 'error' not in r)}/{len(results)}")
        
        return results


if __name__ == "__main__":
    # 測試 Gemini 模型
    import sys
    
    # 初始化模型（會自動從 utils/api_keys.py 讀取 API key）
    try:
        model = GeminiModel(
            model="gemini-2.0-flash-exp",
            temperature=0.0
        )
        print("✅ Gemini 模型初始化成功")
    except ValueError as e:
        print(f"❌ 初始化失敗: {e}")
        sys.exit(1)
    
    # 測試辨識
    test_audio = "experiments/Test_01_TMRT/batch_processing/dataset_chunks/chunk_001.wav"
    
    if Path(test_audio).exists():
        # 建立捷運專業術語的上下文
        context = """這是台灣捷運無線電通訊錄音。
常見術語包含：
- OCC (行控中心)
- R13, R14 等車站代碼
- VVVF (變頻器)
- ATP/ATO (列車自動保護/駕駛系統)
- Bypass (旁通)
"""
        
        result = model.transcribe_file(test_audio, context=context)
        
        print(f"\n辨識結果:")
        print(f"逐字稿: {result['transcript']}")
        print(f"模型: {result['model']}")
    else:
        print(f"測試檔案不存在: {test_audio}")