"""
檢測 Gemini API 可用模型
快速檢查您的 API key 支援哪些模型
"""

import json
from pathlib import Path

# 嘗試導入 google.generativeai
try:
    import google.generativeai as genai
except ImportError:
    print("❌ 錯誤：找不到 google.generativeai 套件")
    print("請執行：pip install google-generativeai")
    exit(1)

def load_api_key():
    """從配置檔案載入 API key"""
    # 嘗試從 JSON 讀取
    json_path = Path("utils/api_keys.json")
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            api_key = config.get('GEMINI_API_KEY')
            if api_key:
                print(f"✅ 從 {json_path} 載入 API key")
                return api_key
        except Exception as e:
            print(f"⚠️  讀取 JSON 失敗: {e}")
    
    # 嘗試從 Python 檔案讀取
    try:
        from utils.api_keys import get_gemini_api_key
        api_key = get_gemini_api_key()
        if api_key:
            print("✅ 從 utils/api_keys.py 載入 API key")
            return api_key
    except:
        pass
    
    print("❌ 錯誤：找不到 API key")
    print("請設定 utils/api_keys.json 或 utils/api_keys.py")
    return None

def list_models(api_key):
    """列出所有可用模型"""
    genai.configure(api_key=api_key)
    
    print("\n" + "=" * 70)
    print("可用的 Gemini 模型")
    print("=" * 70)
    
    models_found = []
    
    try:
        for model in genai.list_models():
            if 'generateContent' in model.supported_generation_methods:
                models_found.append(model.name)
                print(f"\n✅ {model.name}")
                print(f"   顯示名稱: {model.display_name}")
                print(f"   支援方法: {', '.join(model.supported_generation_methods)}")
                if hasattr(model, 'description'):
                    print(f"   說明: {model.description}")
    
    except Exception as e:
        print(f"\n❌ 列出模型失敗: {e}")
        return []
    
    if not models_found:
        print("\n⚠️  警告：沒有找到支援 generateContent 的模型")
        print("這可能表示您的 API key 權限不足或已過期")
    
    return models_found

def recommend_model(models):
    """推薦適合的模型"""
    if not models:
        return None
    
    print("\n" + "=" * 70)
    print("推薦模型")
    print("=" * 70)
    
    # 檢查各種模型
    recommendations = []
    
    for model_name in models:
        short_name = model_name.replace('models/', '')
        
        # Gemini 2.0
        if 'gemini-2.0' in short_name or 'gemini-exp' in short_name:
            recommendations.append({
                'name': short_name,
                'full_name': model_name,
                'priority': 1,
                'reason': '最新的 Gemini 2.0 版本'
            })
        # Gemini 1.5 Pro
        elif 'gemini-1.5-pro' in short_name:
            recommendations.append({
                'name': short_name,
                'full_name': model_name,
                'priority': 2,
                'reason': 'Gemini 1.5 Pro - 準確度最高'
            })
        # Gemini 1.5 Flash
        elif 'gemini-1.5-flash' in short_name:
            recommendations.append({
                'name': short_name,
                'full_name': model_name,
                'priority': 3,
                'reason': 'Gemini 1.5 Flash - 速度最快'
            })
    
    # 按優先順序排序
    recommendations.sort(key=lambda x: x['priority'])
    
    if recommendations:
        print("\n推薦使用以下模型（按推薦順序）：\n")
        for i, rec in enumerate(recommendations[:3], 1):
            print(f"{i}. {rec['name']}")
            print(f"   完整名稱: {rec['full_name']}")
            print(f"   推薦原因: {rec['reason']}")
            print()
        
        return recommendations[0]['full_name']
    
    return models[0] if models else None

def suggest_usage(model_name):
    """建議使用方式"""
    if not model_name:
        return
    
    print("=" * 70)
    print("使用建議")
    print("=" * 70)
    
    # 取得短名稱
    short_name = model_name.replace('models/', '')
    
    print(f"\n在互動式介面中：")
    print("  如果模型選項中沒有此模型，請選擇最接近的版本")
    
    print(f"\n在命令列中：")
    print(f"  # 嘗試使用預設（2.0 Flash Exp）")
    print(f"  python scripts\\batch_inference.py --test-case Test_02_TMRT --model gemini")
    
    print(f"\n在程式碼中：")
    print(f"  from scripts.models.model_gemini import GeminiModel")
    print(f"  model = GeminiModel(model='{short_name}')")
    
    print(f"\n如果上述方法都失敗，請修改 model_gemini.py：")
    print(f"  在 MODELS 字典中添加：")
    print(f"  '{short_name}': '{model_name}'")

if __name__ == "__main__":
    print("=" * 70)
    print("Gemini API 模型檢測工具")
    print("=" * 70)
    
    # 載入 API key
    api_key = load_api_key()
    if not api_key:
        exit(1)
    
    # 列出模型
    models = list_models(api_key)
    
    # 推薦模型
    recommended = recommend_model(models)
    
    # 建議使用方式
    suggest_usage(recommended)
    
    print("\n" + "=" * 70)
    print("檢測完成")
    print("=" * 70)