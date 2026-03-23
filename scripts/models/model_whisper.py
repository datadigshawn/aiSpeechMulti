"""
Whisper 語音辨識模組（動態詞彙表版本）
支援從 vocabulary/google_phrases.json 動態產生 initial_prompt

檔案位置: aiSpeech/scripts/model_whisper.py

使用前準備:
1. 安裝套件: pip install openai-whisper torch
2. 確保 vocabulary/google_phrases.json 已產生
3. (選用) 如果有 NVIDIA GPU: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

使用方式:
    from model_whisper import transcribe_with_whisper
    text = transcribe_with_whisper("audio.wav", model_size="large-v3")
"""

import json
import whisper
import torch
from pathlib import Path


# ==================== 全域變數 ====================
# 用來暫存載入好的模型，避免重複載入（單例模式）
_loaded_model = None
_current_model_size = None

# 暫存已產生的 prompt，避免重複讀取檔案
_cached_prompt = None
_prompt_loaded = False


# ==================== 詞彙表處理 ====================

def load_vocabulary_for_prompt():
    """
    從 vocabulary/google_phrases.json 動態產生 Whisper 的 initial_prompt
    
    用途1: 辨識前優化
    - 將詞彙表中權重最高的術語組成 prompt
    - 提示 Whisper 模型注意這些專業用語
    
    Returns:
        str: 格式化的 prompt 文字
    """
    global _cached_prompt, _prompt_loaded
    
    # 如果已經載入過，直接返回快取
    if _prompt_loaded:
        return _cached_prompt
    
    # 取得詞彙表路徑
    project_root = Path(__file__).parent.parent
    phrases_path = project_root / 'vocabulary' / 'google_phrases.json'
    
    # 如果檔案不存在，使用預設 prompt
    if not phrases_path.exists():
        print("⚠️  警告: 找不到 google_phrases.json，使用預設 prompt")
        print(f"   請先執行: python utils/vocabulary_generator.py")
        _cached_prompt = "這是一段台灣捷運無線電通訊。"
        _prompt_loaded = True
        return _cached_prompt
    
    try:
        # 讀取詞彙表
        with open(phrases_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        phrases = data.get('phrases', [])
        
        if not phrases:
            print("⚠️  警告: 詞彙表為空，使用預設 prompt")
            _cached_prompt = "這是一段台灣捷運無線電通訊。"
            _prompt_loaded = True
            return _cached_prompt
        
        # 依照 boost 值排序，取前 30 個最重要的術語
        top_terms = sorted(
            phrases, 
            key=lambda x: x.get('boost', 0), 
            reverse=True
        )[:30]
        
        # 提取術語文字
        terms_list = [term['value'] for term in top_terms]
        
        # 組合成自然語言的 prompt
        terms_str = "、".join(terms_list)
        
        prompt = (
            f"這是一段台灣捷運無線電通訊。"
            f"對話中包含以下專業術語：{terms_str}。"
            f"請準確辨識這些術語，保持原文不要翻譯或轉換。"
        )
        
        _cached_prompt = prompt
        print(f"✅ 已載入詞彙表: {len(terms_list)} 個關鍵術語")
        
    except Exception as e:
        print(f"⚠️  讀取詞彙表失敗: {e}")
        print("   使用預設 prompt")
        _cached_prompt = "這是一段台灣捷運無線電通訊。"
    
    _prompt_loaded = True
    return _cached_prompt


# ==================== 模型管理 ====================

def load_model_once(model_size="large-v3"):
    """
    確保模型只被載入一次的單例模式（Singleton Pattern）
    並保留原本的 M2 GPU 加速判斷邏輯
    
    Args:
        model_size (str): 模型大小
            - "turbo": 最快，準確度略低（適合測試）
            - "medium": 中等速度與準確度
            - "large-v3": 最準確（推薦用於正式辨識）
    
    Returns:
        whisper.Whisper: 載入的 Whisper 模型
    """
    global _loaded_model, _current_model_size
    
    # 如果模型已經載入且大小一樣，直接回傳
    if _loaded_model is not None and _current_model_size == model_size:
        return _loaded_model
    
    print(f"🔄 正在載入 Whisper 模型 ({model_size})...")
    
    # 偵測可用的加速裝置
    # 優先順序: CUDA (NVIDIA GPU) > MPS (Apple Silicon) > CPU
    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    
    try:
        _loaded_model = whisper.load_model(model_size, device=device)
        print(f"✅ Whisper 模型 ({model_size}) 載入完成")
        print(f"   使用裝置: {device.upper()}")
    except Exception as e:
        print(f"⚠️  {device.upper()} 啟用失敗，切換回 CPU 模式: {e}")
        _loaded_model = whisper.load_model(model_size, device="cpu")
        print(f"✅ Whisper 模型 ({model_size}) 載入完成")
        print(f"   使用裝置: CPU")
    
    _current_model_size = model_size
    return _loaded_model


# ==================== 辨識功能 ====================

def transcribe_with_whisper(
    audio_path, 
    model_size="large-v3",
    use_vocabulary=True,
    language="zh"
):
    """
    使用 Whisper 辨識單一音檔
    
    Args:
        audio_path (str): 音檔路徑
        model_size (str): 模型大小 (turbo/medium/large-v3)
        use_vocabulary (bool): 是否使用詞彙表產生 prompt（用途1）
        language (str): 語言代碼
            - "zh": 中文（自動偵測簡繁）
            - "zh-TW": 繁體中文
            - None: 自動偵測語言
    
    Returns:
        str: 辨識文字
    """
    # 1. 取得模型實體
    model = load_model_once(model_size)
    
    # 2. 產生 prompt（如果啟用詞彙表）
    if use_vocabulary:
        prompt_text = load_vocabulary_for_prompt()
    else:
        prompt_text = "這是一段台灣捷運無線電通訊。"
    
    # 3. 執行辨識
    # initial_prompt 是 Whisper 的關鍵參數，可以引導模型辨識方向
    result = model.transcribe(
        audio_path,
        language=language,
        initial_prompt=prompt_text,
        verbose=False  # 關閉進度顯示（批次處理時較乾淨）
    )
    
    return result['text'].strip()


def batch_transcribe(
    audio_folder, 
    output_folder, 
    model_size="large-v3",
    use_vocabulary=True
):
    """
    批次辨識資料夾中的所有音檔
    
    Args:
        audio_folder (str): 音檔資料夾路徑
        output_folder (str): 輸出文字檔資料夾
        model_size (str): 使用的模型
        use_vocabulary (bool): 是否使用詞彙表
    """
    from pathlib import Path
    
    audio_folder = Path(audio_folder)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    
    # 支援的音檔格式
    audio_files = []
    for ext in ['.wav', '.mp3', '.m4a', '.flac', '.ogg']:
        audio_files.extend(audio_folder.glob(f'*{ext}'))
    
    audio_files = sorted(audio_files)
    
    if not audio_files:
        print(f"❌ 在 {audio_folder} 中找不到音檔")
        return
    
    print("\n" + "="*60)
    print(f"📂 開始批次處理: {len(audio_files)} 個檔案")
    print(f"   模型: Whisper {model_size}")
    print(f"   詞彙表: {'啟用' if use_vocabulary else '停用'}")
    print(f"   輸出: {output_folder}")
    print("="*60 + "\n")
    
    for i, audio_path in enumerate(audio_files, 1):
        print(f"▶️  [{i}/{len(audio_files)}] {audio_path.name}")
        
        output_path = output_folder / f"{audio_path.stem}.txt"
        
        # 如果已經存在，跳過
        if output_path.exists():
            print(f"   ⏭️  已存在，跳過")
            continue
        
        try:
            text = transcribe_with_whisper(
                str(audio_path),
                model_size=model_size,
                use_vocabulary=use_vocabulary
            )
            
            # 存檔
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            
            print(f"   ✅ 完成")
            
        except Exception as e:
            print(f"   ❌ 錯誤: {e}")


# ==================== 測試程式 ====================

if __name__ == "__main__":
    """
    測試用主程式
    使用方式: python scripts/model_whisper.py
    """
    import sys
    
    print("="*60)
    print("Whisper 語音辨識測試（動態詞彙表版本）")
    print("="*60)
    
    # 測試詞彙表載入
    print("\n📋 測試詞彙表載入...")
    prompt = load_vocabulary_for_prompt()
    print(f"\n產生的 Prompt (前 100 字):")
    print("-" * 60)
    print(prompt[:100] + "...")
    print("-" * 60)
    
    # 測試單一檔案辨識
    test_file = "experiments/Test_01_TMRT/dataset_chunks/chunk_001.wav"
    
    if Path(test_file).exists():
        print(f"\n🎤 測試檔案: {test_file}")
        print("   使用模型: turbo (測試用)")
        
        try:
            result = transcribe_with_whisper(
                test_file,
                model_size="turbo",  # 測試時用較快的模型
                use_vocabulary=True
            )
            
            print("\n辨識結果:")
            print("-" * 60)
            print(result)
            print("-" * 60)
            
        except Exception as e:
            print(f"\n❌ 測試失敗: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"\n⚠️  找不到測試檔案: {test_file}")
        print("   請確認檔案路徑或修改 test_file 變數")
        
        # 提示批次處理用法
        print("\n💡 批次處理用法:")
        print("   from model_whisper import batch_transcribe")
        print("   batch_transcribe(")
        print("       'experiments/Test_01_TMRT/dataset_chunks',")
        print("       'experiments/Test_01_TMRT/ASR_Evaluation/whisper_output'")
        print("   )")