"""
詞彙表生成器 (Vocabulary Generator)
功能：
1. 讀取 master_vocabulary.csv
2. 生成 google_phrases.json（用途1：Google STT PhraseSet）
3. 生成 correction_dict.py（用途2：Python 後處理修正）
4. 生成 alert_keywords.json（用途3：Elasticsearch 關鍵字告警）
"""

import csv
import json
from pathlib import Path


def load_master_vocabulary(csv_file: str):
    """載入主詞彙表"""
    vocabulary = []
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            vocabulary.append(row)
    
    return vocabulary


def generate_google_phrases(vocabulary, output_file: str):
    """
    生成 Google STT PhraseSet 格式
    用途1：辨識前優化
    """
    phrases = []
    
    for item in vocabulary:
        term = item['term'].strip()
        boost_value = int(item['boost_value']) if item['boost_value'] else 10
        
        if term:  # 排除空白行
            phrases.append({
                "value": term,
                "boost": boost_value
            })
    
    output_data = {
        "phrases": phrases,
        "description": "aiSpeech 捷運無線電專業術語 PhraseSet",
        "total_terms": len(phrases)
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Google Phrases 已生成: {output_file}")
    print(f"   包含 {len(phrases)} 個詞彙")


def generate_correction_dict(vocabulary, output_file: str):
    """
    生成 Python 修正字典
    用途2：辨識後修正（同音異字）
    """
    corrections = {}
    
    for item in vocabulary:
        term = item['term'].strip()
        common_errors = item.get('common_error', '').strip()
        
        if term and common_errors:
            # 分割多個錯誤寫法（用 | 分隔）
            error_list = [e.strip() for e in common_errors.split('|') if e.strip()]
            
            for error in error_list:
                corrections[error] = term
    
    # 生成 Python 程式碼
    code = '''"""
自動生成的無線電術語修正字典
由 generate_vocabulary_files.py 從 master_vocabulary.csv 生成
請勿手動編輯此檔案！
"""

# 無線電術語修正字典（同音異字）
RADIO_REPLACEMENT_RULES = {
'''
    
    for error, correct in sorted(corrections.items()):
        code += f'    "{error}": "{correct}",\n'
    
    code += '}\n'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(code)
    
    print(f"✅ Correction Dict 已生成: {output_file}")
    print(f"   包含 {len(corrections)} 組修正規則")


def generate_alert_keywords(vocabulary, output_file: str):
    """
    生成 Elasticsearch 告警關鍵字
    用途3：關鍵字告警
    """
    keywords = []
    
    # 告警級別對應
    alert_level_map = {
        '0': 'INFO',
        '1': 'WARNING',
        '2': 'IMPORTANT',
        '3': 'CRITICAL'
    }
    
    for item in vocabulary:
        term = item['term'].strip()
        alert_level = item.get('alert_level', '0').strip()
        category = item.get('category', '').strip()
        description = item.get('description', '').strip()
        
        if term and int(alert_level) > 0:  # 只包含需要告警的詞彙
            keywords.append({
                "term": term,
                "level": alert_level_map.get(alert_level, 'INFO'),
                "category": category,
                "description": description,
                "priority": int(alert_level)
            })
    
    # 按優先度排序（高優先度在前）
    keywords.sort(key=lambda x: x['priority'], reverse=True)
    
    output_data = {
        "keywords": keywords,
        "description": "aiSpeech 關鍵字告警詞彙表",
        "total_keywords": len(keywords),
        "alert_levels": {
            "CRITICAL": "嚴重告警（立即處理）",
            "IMPORTANT": "重要告警（優先處理）",
            "WARNING": "一般告警（需注意）",
            "INFO": "資訊通知"
        }
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Alert Keywords 已生成: {output_file}")
    print(f"   包含 {len(keywords)} 個告警關鍵字")
    
    # 顯示各級別統計
    level_stats = {}
    for kw in keywords:
        level = kw['level']
        level_stats[level] = level_stats.get(level, 0) + 1
    
    print("   級別統計:")
    for level in ['CRITICAL', 'IMPORTANT', 'WARNING', 'INFO']:
        count = level_stats.get(level, 0)
        if count > 0:
            print(f"     {level}: {count}")


def main():
    """主函數"""
    print("=" * 60)
    print("詞彙表生成器")
    print("=" * 60)
    
    # 設定路徑
    script_dir = Path(__file__).parent
    csv_file = script_dir / "master_vocabulary.csv"
    
    # 檢查輸入檔案
    if not csv_file.exists():
        print(f"❌ 找不到 master_vocabulary.csv: {csv_file}")
        return
    
    print(f"\n讀取主詞彙表: {csv_file}")
    
    # 載入詞彙表
    vocabulary = load_master_vocabulary(str(csv_file))
    print(f"✅ 載入 {len(vocabulary)} 個詞彙\n")
    
    # 生成三種格式
    print("生成輸出檔案...")
    print()
    
    # 1. Google Phrases
    generate_google_phrases(
        vocabulary,
        str(script_dir / "google_phrases.json")
    )
    print()
    
    # 2. Correction Dict
    generate_correction_dict(
        vocabulary,
        str(script_dir / "correction_dict.py")
    )
    print()
    
    # 3. Alert Keywords
    generate_alert_keywords(
        vocabulary,
        str(script_dir / "alert_keywords.json")
    )
    
    print()
    print("=" * 60)
    print("✨ 所有檔案生成完成！")
    print("=" * 60)
    print()
    print("輸出檔案位置:")
    print(f"  1. {script_dir / 'google_phrases.json'}")
    print(f"  2. {script_dir / 'correction_dict.py'}")
    print(f"  3. {script_dir / 'alert_keywords.json'}")
    print()


if __name__ == "__main__":
    main()
