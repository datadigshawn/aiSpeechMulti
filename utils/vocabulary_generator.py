"""
詞彙表轉換引擎,將master_vocabulary.csv轉化三格式
1. google_phrases.json (用途1. Google STT Phraseset)
2. correction_dict.py  (用途2.Python後處理修正字典)
3. alert_keywords.json (用途3. Elasticsearch告警關鍵字)
"""

import os
import csv
import json 
from pathlib import Path

class VocabularyGenerator:
    def __init__(self, csv_path='vocabulary/master_vocabulary.csv'):
        """初始化詞彙表產生器"""
        self.project_root = Path(__file__).parent.parent
        self.csv_path = self.project_root / csv_path
        self.output_dir = self.project_root / 'vocabulary'
        
        # 確保輸出目錄存在
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 儲存讀取的詞彙資料
        self.vocabulary = []
        
    def load_csv(self):
        """讀取主詞彙表 CSV"""
        if not self.csv_path.exists():
            raise FileNotFoundError(f"找不到詞彙表檔案: {self.csv_path}")
        
        print(f"📖 正在讀取: {self.csv_path}")
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            self.vocabulary = list(reader)
        
        print(f"✅ 成功載入 {len(self.vocabulary)} 個詞彙")
        return self
    
    def generate_google_phrases(self):
        """
        產生 Google STT 的 PhraseSet 格式
        用途1: 辨識前優化，提高專業術語辨識準確率
        """
        output_path = self.output_dir / 'google_phrases.json'
        
        # 建立 phrases 陣列
        phrases = []
        
        for item in self.vocabulary:
            phrase_obj = {
                "value": item['term'],
                "boost": float(item['boost_value'])
            }
            phrases.append(phrase_obj)
        
        # 包裝成 Google STT V2 API 的 PhraseSet 格式
        phrase_set = {
            "phrases": phrases
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(phrase_set, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 已產生: {output_path}")
        print(f"   → 用途1: Google STT 辨識前優化 (共 {len(phrases)} 個詞組)")
        return self
    
    def generate_correction_dict(self):
        """
        產生 Python 字典格式的修正表
        用途2: 辨識後修正同音異字
        """
        output_path = self.output_dir / 'correction_dict.py'
        
        # 建立修正字典
        corrections = {}
        
        for item in self.vocabulary:
            # 只處理有標註常見錯誤的詞彙
            if item['common_error'] and item['common_error'].strip():
                correct_term = item['term']
                errors = item['common_error'].split('|')
                
                for error in errors:
                    error = error.strip()
                    if error:
                        corrections[error] = correct_term
        
        # 寫入 Python 檔案
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('"""\n')
            f.write('詞彙修正字典 - 自動產生\n')
            f.write('用途2: Python 辨識後處理，修正同音異字\n')
            f.write('請勿手動編輯此檔案，請修改 master_vocabulary.csv 後重新產生\n')
            f.write('"""\n\n')
            f.write('# 同音異字修正表\n')
            f.write('CORRECTION_DICT = {\n')   # 定義一個名為Correction_Dict的字典，並且把資料寫入
            
            for wrong, correct in sorted(corrections.items()):   
                f.write(f'    "{wrong}": "{correct}",\n')       
                # corrections字典中存儲每個錯誤字串與對應的正確字串，這段程式遍歷correction字典時，將每個錯誤字串給wrong、對應的正確字串給correct
            
            f.write('}\n\n')
            
            # 加入輔助函數
            f.write('def apply_corrections(text):\n')
            f.write('    """\n')
            f.write('    應用詞彙修正\n')
            f.write('    \n')
            f.write('    Args:\n')
            f.write('        text (str): 辨識原始文字\n')
            f.write('    \n')
            f.write('    Returns:\n')
            f.write('        str: 修正後的文字\n')
            f.write('    """\n')
            f.write('    if not text:\n')
            f.write('        return ""\n')
            f.write('    \n')
            f.write('    # 執行字典替換\n')
            f.write('    for wrong, correct in CORRECTION_DICT.items():\n')
            f.write('        text = text.replace(wrong, correct)\n')
            f.write('    \n')
            f.write('    return text\n')
        
        print(f"✅ 已產生: {output_path}")
        print(f"   → 用途2: Python 辨識後修正 (共 {len(corrections)} 組修正規則)")
        return self
    
    def generate_alert_keywords(self):
        """
        產生 Elasticsearch 告警關鍵字 JSON
        用途3: 關鍵字偵測與分級告警
        """
        output_path = self.output_dir / 'alert_keywords.json'
        
        # 依告警等級分類
        alert_categories = {
            "emergency": [],      # 等級 3
            "important": [],      # 等級 2
            "normal": [],         # 等級 1
            "info": []           # 等級 0 (不告警，但記錄)
        }
        
        for item in self.vocabulary:
            alert_level = int(item['alert_level'])
            keyword_obj = {
                "term": item['term'],
                "category": item['category'],
                "description": item['description']
            }
            
            if alert_level == 3:
                alert_categories["emergency"].append(keyword_obj)
            elif alert_level == 2:
                alert_categories["important"].append(keyword_obj)
            elif alert_level == 1:
                alert_categories["normal"].append(keyword_obj)
            else:
                alert_categories["info"].append(keyword_obj)
        
        # 建立 Elasticsearch Percolate Query 格式
        es_queries = []
        
        # 緊急告警 (等級 3)
        if alert_categories["emergency"]:
            es_queries.append({
                "query_id": "emergency_alert",
                "alert_level": 3,
                "alert_type": "緊急告警",
                "notification": ["email", "sms", "popup", "sound"],
                "keywords": [k["term"] for k in alert_categories["emergency"]],
                "query": {
                    "bool": {
                        "should": [
                            {"match": {"content": k["term"]}} 
                            for k in alert_categories["emergency"]
                        ],
                        "minimum_should_match": 1
                    }
                }
            })
        
        # 重要告警 (等級 2)
        if alert_categories["important"]:
            es_queries.append({
                "query_id": "important_alert",
                "alert_level": 2,
                "alert_type": "重要告警",
                "notification": ["email", "popup"],
                "keywords": [k["term"] for k in alert_categories["important"]],
                "query": {
                    "bool": {
                        "should": [
                            {"match": {"content": k["term"]}} 
                            for k in alert_categories["important"]
                        ],
                        "minimum_should_match": 1
                    }
                }
            })
        
        # 一般通知 (等級 1)
        if alert_categories["normal"]:
            es_queries.append({
                "query_id": "normal_alert",
                "alert_level": 1,
                "alert_type": "一般通知",
                "notification": ["popup"],
                "keywords": [k["term"] for k in alert_categories["normal"]],
                "query": {
                    "bool": {
                        "should": [
                            {"match": {"content": k["term"]}} 
                            for k in alert_categories["normal"]
                        ],
                        "minimum_should_match": 1
                    }
                }
            })
        
        output_data = {
            "description": "關鍵字告警設定 - 自動產生",
            "categories": alert_categories,
            "elasticsearch_queries": es_queries
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:              # 講指定的output_path檔案以UTF-8編碼開啟，使用with陳述句，會在檔案執行運算後關閉
            json.dump(output_data, f, ensure_ascii=False, indent=2)    # 使用json.dump將output_data內容寫入該檔案，可確保非ASCII字元不會被轉議，並且已2個空格的縮排方式排版
        
        print(f"✅ 已產生: {output_path}")
        print(f"   → 用途3: Elasticsearch 告警 (緊急:{len(alert_categories['emergency'])} "
              f"重要:{len(alert_categories['important'])} "
              f"一般:{len(alert_categories['normal'])})")
        return self
    
    def generate_statistics(self):
        """產生詞彙統計報告"""
        stats_path = self.output_dir / 'vocabulary_stats.txt'
        
        # 統計各類別數量
        category_count = {}
        alert_count = {0: 0, 1: 0, 2: 0, 3: 0}
        
        for item in self.vocabulary:   # self.vocabulary 是一個屬性，存儲了從 CSV 檔案讀取的詞彙資料。self.vocabulary 可以在 generate_statistics方法中訪問和使用。
            # 統計類別
            cat = item['category']
            category_count[cat] = category_count.get(cat, 0) + 1
            
            # 統計告警等級
            level = int(item['alert_level'])
            alert_count[level] += 1
        
        with open(stats_path, 'w', encoding='utf-8') as f:
            f.write('='*60 + '\n')
            f.write('詞彙表統計報告\n')
            f.write('='*60 + '\n\n')
            
            f.write(f'總詞彙數: {len(self.vocabulary)}\n\n')
            
            f.write('類別分布:\n')
            for cat, count in sorted(category_count.items(), key=lambda x: x[1], reverse=True):
                f.write(f'  • {cat:20s}: {count:3d} 個\n')
            
            f.write('\n告警等級分布:\n')
            f.write(f'  • 等級 0 (不告警):  {alert_count[0]:3d} 個\n')
            f.write(f'  • 等級 1 (一般):    {alert_count[1]:3d} 個\n')
            f.write(f'  • 等級 2 (重要):    {alert_count[2]:3d} 個\n')
            f.write(f'  • 等級 3 (緊急):    {alert_count[3]:3d} 個\n')
            
            f.write('\n產生檔案:\n')
            f.write(f'  1. google_phrases.json     (用途1: Google STT 辨識前優化)\n')
            f.write(f'  2. correction_dict.py      (用途2: Python 辨識後修正)\n')
            f.write(f'  3. alert_keywords.json     (用途3: Elasticsearch 告警)\n')
            f.write(f'  4. vocabulary_stats.txt    (統計報告)\n')
        
        print(f"✅ 已產生: {stats_path}")
        print(f"\n📊 詞彙統計:")
        print(f"   總計: {len(self.vocabulary)} 個詞彙")
        print(f"   類別數: {len(category_count)} 種")
        print(f"   緊急關鍵字: {alert_count[3]} 個")
        
        return self
    
    def run(self):
        """執行完整的轉換流程"""
        print("\n" + "="*60)
        print("🚀 詞彙表轉換引擎啟動")
        print("="*60 + "\n")
        
        try:
            self.load_csv()
            print()
            
            self.generate_google_phrases()
            self.generate_correction_dict()
            self.generate_alert_keywords()
            self.generate_statistics()
            
            print("\n" + "="*60)
            print("✨ 全部完成！三種格式的詞彙表已成功產生")
            print("="*60 + "\n")
            
            print("📁 產生的檔案位於: vocabulary/")
            print("   ├─ google_phrases.json      (用途1)")
            print("   ├─ correction_dict.py       (用途2)")
            print("   ├─ alert_keywords.json      (用途3)")
            print("   └─ vocabulary_stats.txt     (統計報告)")
            
            print("\n🔄 下一步:")
            print("   1. 檢查產生的檔案是否正確")
            print("   2. 在 batch_inference.py 中引用 correction_dict")
            print("   3. 在 Google STT 設定中載入 google_phrases.json")
            print("   4. 在 Elasticsearch 中設定 alert_keywords.json")
            
        except FileNotFoundError as e:
            print(f"\n❌ 錯誤: {e}")
            print("   請確認 vocabulary/master_vocabulary.csv 檔案存在")
        except Exception as e:
            print(f"\n❌ 發生錯誤: {e}")
            import traceback
            traceback.print_exc()


def main():
    """主程式入口"""
    generator = VocabularyGenerator()
    generator.run()


if __name__ == "__main__":
    main()