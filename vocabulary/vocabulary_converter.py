#!/usr/bin/env python3
"""
詞彙表轉換工具 v2.0 - 針對無線電語音優化
==============================================================================
功能：
1. 讀取 master_vocabulary_enhanced.csv
2. 生成三種格式輸出：
   a) Google STT PhraseSet JSON（pre-recognition）
   b) Python 修正字典（post-recognition）
   c) Elasticsearch 關鍵字 JSON（alerting）
3.保留舊版的統計摘要報告(.txt)

新增優化：
- 階層式 boost 權重（Alert Level 3 = boost 20, Level 2 = boost 15...）
- 同音字錯誤列表自動展開
- 特殊格式處理（車組編號 "25/26車"）
"""

import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple
import re


class VocabularyConverter:
    """詞彙表轉換器 v2.1 - 整合統計報告功能"""
    
    def __init__(self, csv_path: str):
        """初始化轉換器"""
        self.csv_path = Path(csv_path)
        self.terms = []
        self.corrections = {}  # 同音字修正字典
        self.alert_keywords = []  # 警報關鍵字
        # 新增：用於統計的變數
        self.stats = {
            "categories": {},
            "levels": {0: 0, 1: 0, 2: 0, 3: 0}
        }
        
    def load_csv(self) -> None:
        """載入 CSV 並進行初步統計"""
        if not self.csv_path.exists():
            raise FileNotFoundError(f"找不到詞彙表檔案: {self.csv_path}")
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 跳過註解行
                if row['term'].startswith('#'):
                    continue
                
                self.terms.append(row)
                
                # 統計類別與等級
                cat = row['category']
                lvl = int(row.get('alert_level', 0))
                self.stats["categories"][cat] = self.stats["categories"].get(cat, 0) + 1
                self.stats["levels"][lvl] = self.stats["levels"].get(lvl, 0) + 1

                # 建立同音字修正字典
                if row.get('common_error'):
                    for error in row['common_error'].split('|'):
                        error = error.strip()
                        if error:
                            self.corrections[error] = row['term']
                
                # 收集警報關鍵字（Alert Level 2 以上）
                if int(row.get('alert_level', 0)) >= 2:
                    self.alert_keywords.append({
                        'keyword': row['term'],
                        'level': int(row['alert_level']),
                        'category': row['category'],
                        'description': row.get('description', '')
                    })
        
        print(f"✅ 載入 {len(self.terms)} 個術語")
        print(f"   - 同音字修正: {len(self.corrections)} 組")
        print(f"   - 警報關鍵字: {len(self.alert_keywords)} 個")
    
    def generate_google_phraseset(self, output_path: str) -> Dict:
        """
        生成 Google STT PhraseSet JSON
        
        優化策略：
        1. 使用 alert_level 和 boost_value 決定權重
        2. 關鍵術語（OCC, EDRH等）boost=20
        3. 車站代碼 boost=20
        4. 一般術語 boost=10-15
        """
        phrases = []
        
        for term in self.terms:
            # 計算 boost 權重
            boost_value = int(term.get('boost_value', 10))
            alert_level = int(term.get('alert_level', 0))
            
            # Alert Level 越高，boost 越高
            final_boost = boost_value
            if alert_level == 3:
                final_boost = max(boost_value, 20)  # 緊急術語至少 20
            elif alert_level == 2:
                final_boost = max(boost_value, 15)  # 重要術語至少 15
            
            phrase_dict = {
                "value": term['term'],
                "boost": final_boost
            }
            phrases.append(phrase_dict)
            
            # 特殊處理：車站代碼添加變體
            if term['category'] == 'station_code':
                # 添加帶空格的版本（例如："G 0 7", "G 零 七"）
                station_code = term['term']
                if re.match(r'[GR]\d+', station_code):
                    # G07 -> "G 0 7", "G 零 七"
                    spaced_version = ' '.join(station_code)
                    phrases.append({
                        "value": spaced_version,
                        "boost": final_boost
                    })
        
        # 按 boost 值排序（高權重在前）
        phrases.sort(key=lambda x: x['boost'], reverse=True)
        
        # 限制數量（Google STT Chirp 3 支援最多 1000 個）
        phrases = phrases[:1000]
        
        result = {
            "phrases": phrases,
            "metadata": {
                "total_count": len(phrases),
                "max_boost": max(p['boost'] for p in phrases),
                "min_boost": min(p['boost'] for p in phrases),
                "source": str(self.csv_path.name),
                "version": "2.0_radio_optimized"
            }
        }
        
        # 儲存 JSON
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ Google PhraseSet JSON 已生成: {output_file}")
        print(f"   - 總數: {len(phrases)} 個短語")
        print(f"   - Boost 範圍: {result['metadata']['min_boost']}~{result['metadata']['max_boost']}")
        
        return result
    
    def generate_python_correction_dict(self, output_path: str) -> None:
        """
        生成 Python 修正字典（用於後處理）
        
        格式：
        CORRECTIONS = {
            "錯誤詞": "正確詞",
            "鬼旁修牆": "軌旁胸牆",
            ...
        }
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 生成 Python 程式碼
        code = '#!/usr/bin/env python3\n'
        code += '"""\n'
        code += '自動生成的同音字修正字典\n'
        code += f'來源: {self.csv_path.name}\n'
        code += f'生成時間: {Path(__file__).stat().st_mtime}\n'
        code += '"""\n\n'
        code += 'RADIO_CORRECTIONS = {\n'
        
        for error, correct in sorted(self.corrections.items()):
            code += f'    "{error}": "{correct}",\n'
        
        code += '}\n\n'
        code += f'# 總計: {len(self.corrections)} 個修正規則\n'
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(code)
        
        print(f"\n✅ Python 修正字典已生成: {output_file}")
        print(f"   - 總數: {len(self.corrections)} 個規則")
    
    def generate_alert_keywords_json(self, output_path: str) -> None:
        """生成警報關鍵字 JSON（用於 Elasticsearch 或 real-time alerting）"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        result = {
            "alert_keywords": self.alert_keywords,
            "metadata": {
                "total_count": len(self.alert_keywords),
                "level_3_count": sum(1 for k in self.alert_keywords if k['level'] == 3),
                "level_2_count": sum(1 for k in self.alert_keywords if k['level'] == 2),
            }
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 警報關鍵字 JSON 已生成: {output_file}")
        print(f"   - Level 3 (緊急): {result['metadata']['level_3_count']} 個")
        print(f"   - Level 2 (重要): {result['metadata']['level_2_count']} 個")

    def generate_statistics_report(self, output_dir: Path) -> None:
        """移植舊版的統計報告生成邏輯"""
        stats_path = output_dir / 'vocabulary_stats.txt'
        
        with open(stats_path, 'w', encoding='utf-8') as f:
            f.write('='*60 + '\n')
            f.write(f'詞彙表統計報告 - 來源: {self.csv_path.name}\n')
            f.write('='*60 + '\n\n')
            f.write(f'總詞彙數: {len(self.terms)}\n\n')
            
            f.write('類別分布:\n')
            for cat, count in sorted(self.stats["categories"].items(), key=lambda x: x[1], reverse=True):
                f.write(f'  • {cat:20s}: {count:3d} 個\n')
            
            f.write('\n告警等級分布:\n')
            for lvl in range(4):
                label = {0: "不告警", 1: "一般", 2: "重要", 3: "緊急"}[lvl]
                f.write(f'  • 等級 {lvl} ({label}): {self.stats["levels"][lvl]:3d} 個\n')
        
        print(f"✅ 統計報告已生成: {stats_path}")
    
    def convert_all(self, output_dir: str = "vocabulary") -> None:
        """一次性生成所有格式"""
        output_path = Path(output_dir)
        
        print("\n" + "="*80)
        print("詞彙表轉換工具 v2.0 - 無線電語音優化版")
        print("="*80)
        
        # 載入 CSV
        self.load_csv()
        
        # 生成三種格式
        self.generate_google_phraseset(output_path / "google_phrases.json")
        self.generate_python_correction_dict(output_path / "radio_corrections.py")
        self.generate_alert_keywords_json(output_path / "alert_keywords.json")
        self.generate_statistics_report(output_path) # 執行移植的統計功能
        
        print("\n" + "="*80)
        print("✅ 轉換完成！")
        print("="*80)
        print(f"\n使用方式:")
        print(f"1. Google STT: 將 google_phrases.json 用於 batch_inference.py")
        print(f"2. 後處理: import radio_corrections.RADIO_CORRECTIONS")
        print(f"3. 警報系統: 將 alert_keywords.json 用於 real-time monitoring")
        print(f"4. 統計報告表: 產出")


def main():
    """主程式"""
    import argparse
    
    parser = argparse.ArgumentParser(description="詞彙表轉換工具")
    parser.add_argument(
        "--input",
        default="master_vocabulary_enhanced.csv",
        help="輸入 CSV 檔案路徑"
    )
    parser.add_argument(
        "--output-dir",
        default="vocabulary",
        help="輸出目錄"
    )
    
    args = parser.parse_args()
    
    # 執行轉換
    converter = VocabularyConverter(args.input)
    converter.convert_all(args.output_dir)


if __name__ == "__main__":
    main()
