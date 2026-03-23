#!/usr/bin/env python3
"""
Google Cloud Speech-to-Text Recognizer 診斷工具 (區域端點修正版)
"""

import os
from pathlib import Path
from google.cloud.speech_v2 import SpeechClient
from google.api_core import exceptions
from google.api_core.client_options import ClientOptions

PROJECT_ID = "dazzling-seat-315406"
base_path = Path(__file__).parent.parent
default_key_path = base_path / "utils" / "google-speech-key.json"

if not os.getenv('GOOGLE_APPLICATION_CREDENTIALS') and default_key_path.exists():
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(default_key_path)
    print(f"✅ 已載入金鑰認證: {default_key_path}")

def get_client(location):
    """根據區域建立對應的 API 端點連線"""
    if location == "global":
        return SpeechClient()
    # 如果是 us, eu, asia 等，需要指定 api_endpoint
    options = ClientOptions(api_endpoint=f"{location}-speech.googleapis.com")
    return SpeechClient(client_options=options)

def list_recognizers(project_id: str):
    print("\n" + "=" * 80)
    print(f"正在診斷 Google Cloud 專案: {project_id}")
    print("=" * 80)
    
    locations = ["us", "global", "asia-east1", "eu"] # 修正了區域代碼
    found_recognizers = []
    
    for loc in locations:
        print(f"\n🔍 檢查區域: {loc} ...")
        try:
            client = get_client(loc) # 獲取正確端點的 client
            parent = f"projects/{project_id}/locations/{loc}"
            request = {"parent": parent}
            page_result = client.list_recognizers(request=request)
            
            recognizers = list(page_result)
            if recognizers:
                print(f"✅ 找到 {len(recognizers)} 個辨識器:")
                for rec in recognizers:
                    short_name = rec.name.split('/')[-1]
                    print(f"  📍 名稱: {short_name}")
                    print(f"     模型: {rec.model}")
                    found_recognizers.append(rec)
            else:
                print(f"  ℹ️  此區域目前沒有任何辨識器")
        except Exception as e:
            print(f"  ⚠️  無法存取 {loc} 區域: {str(e)[:100]}...")

    # --- 特別針對您的截圖檢查 ---
    print("\n" + "-" * 80)
    print(f"🎯 針對 'us' 區域的 'recongnizerstt' 進行精確檢查")
    try:
        us_client = get_client("us")
        target_name = f"projects/{project_id}/locations/us/recognizers/recongnizerstt"
        rec = us_client.get_recognizer(name=target_name)
        print(f"✅ 成功連線！辨識器狀態正常。")
        print(f"   模型: {rec.model} | 語言: {rec.language_codes}")
    except Exception as e:
        print(f"❌ 精確檢查失敗: {e}")

def main():
    list_recognizers(PROJECT_ID)

if __name__ == "__main__":
    main()