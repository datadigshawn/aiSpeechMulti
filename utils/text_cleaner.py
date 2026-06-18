#!/usr/bin/env python3
"""
無線電文字清洗與修正模組 v2.0
==============================================================================
基於測試結果設計的專業修正系統

測試結果分析（來自您的測試數據）：
----------------------------------
錯誤模式 1: 核心術語完全錯誤
- "OCC" → "現電力一場", "歐西", "哦西"
- "MCP" → "ncp", "n c p"
- "EDRH" → "e d"

錯誤模式 2: 同音字混淆
- "軌旁胸牆" → "鬼旁修牆"
- "月台門" → "月車"
- "停準" → "停駛"
- "障礙物" → "代務委員"
- "旅客" → "陸客"
- "立即回報" → "立起回報"

錯誤模式 3: 車站代碼格式錯誤
- "G7" → "g 7", "G 7"
- "G11" → "11"

錯誤模式 4: 數字爆炸
- "22車" → "12345678910111213...140+"

錯誤模式 5: 車組編號錯誤
- "25/26車" → "兩兩車", "2526車"
- "05/06車" → "動六車", "0506車"

本模組設計 50+ 條針對性修正規則來解決這些問題。
"""

import re
from typing import Optional, Dict
import json
from pathlib import Path

try:
    import cn2an
    CN2AN_AVAILABLE = True
except ImportError:
    CN2AN_AVAILABLE = False

try:
    from opencc import OpenCC
    OPENCC_AVAILABLE = True
except ImportError:
    OPENCC_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger("text_cleaner")


# ============================================================================
# 階段 1: 核心術語修正（必須先執行，優先級最高）
#
# ⚠️ DEAD（2026-06-16 第二波）：以下 CRITICAL_TERMS / HOMOPHONE_CORRECTIONS 與
# fix_station_codes / fix_number_explosion / fix_train_numbers 只被
# RadioTextCleaner.clean(aggressive=True) 使用，而該路徑在 fix_radio_jargon
# 改走 canonical 核心（scripts/post_process）後已無生產引用。功能與
# scripts/post_process.py 各階段重複，保留待專門清理波次移除，勿在新程式碼引用。
# ============================================================================

CRITICAL_TERMS = {
    # 從測試結果提取的極高頻錯誤
    "現電力一場": "OCC",
    "歐西": "OCC",
    "哦西": "OCC",
    "歐CC": "OCC",
    "O C C": "OCC",
    "o c c": "OCC",
    
    # MCP 系列
    "ncp": "MCP",
    "n c p": "MCP",
    "N C P": "MCP",
    "M C P": "MCP",
    
    # EDRH 系列
    "e d": "EDRH",
    "e d r h": "EDRH",
    "ED": "EDRH",
    "E D": "EDRH",
    
    # MTC/MCS
    "M T C": "MTC",
    "m t c": "MTC",
    "M C S": "MCS",
    "m c s": "MCS",
    
    # VVVF
    "威威威福": "VVVF",
    "VVF": "VVVF",
    "v v v f": "VVVF",
    "V V V F": "VVVF",
}


# ============================================================================
# 階段 2: 同音字修正（來自測試結果的實際錯誤）
# ============================================================================

HOMOPHONE_CORRECTIONS = {
    # 專業術語
    "鬼旁修牆": "軌旁胸牆",
    "鬼旁收牆": "軌旁胸牆",
    "規旁修牆": "軌旁胸牆",
    "軌旁修牆": "軌旁胸牆",  # 原文錯誤，應該是胸牆
    
    "月車": "月台",
    "越台": "月台",
    "約台": "月台",
    "月台們": "月台門",
    "月台門們": "月台門",
    
    "停駛": "停準",
    "停站": "停準",
    "停准": "停準",
    
    "陸客": "旅客",
    "旅克": "旅客",
    "綠客": "旅客",
    
    "代務委員": "障礙物",
    "障礙屋": "障礙物",
    
    "立起回報": "立即回報",
    "力求報": "立即回報",
    "立刻回報": "立即回報",
    "立即致": "立即至",
    
    "可是範圍": "可視範圍",
    "確認範圍": "可視範圍",
    
    "捷捷車": "列車",
    "例車": "列車",
    "劣車": "列車",
    
    "電腦": "電纜",
    "電覽": "電纜",
    
    # 指令術語
    "護照": "呼叫",
    "戶叫": "呼叫",
    "呼告": "呼叫",
    
    "通告前線": "通告全線",
    "通告全先": "通告全線",
    "通話完畢": "通告完畢",
    
    "全新更長": "全線各站長",
    "全新站長": "全線站長",
    "全先站長": "全線站長",
    "前線各站長": "全線各站長",
    
    "清車完備": "清車完畢",
    "情車完畢": "清車完畢",
    
    "開關們正常": "開關門正常",
    "開關門正長": "開關門正常",
    
    "插一扇門": "差一扇門",
    "差一善門": "差一扇門",
    
    "未開起": "未開啟",
    "沒開啟": "未開啟",
    
    "未停駛": "未停準",
    "沒停準": "未停準",
    
    # 車組編號
    "動五車": "05車",
    "動六車": "06車",
    "洞五車": "05車",
    "洞六車": "06車",
    "腰洞車": "10車",
    "兩兩車": "22車",
    "兩三車": "23車",
    "兩五車": "25車",
    "兩六車": "26車",
    "兩九車": "29車",
    
    # 電力相關（測試結果中的高頻錯誤）
    "電力一場": "電力異常",
    "電力意外": "電力異常",
    "電力以常": "電力異常",
    
    "三鬼附電": "三軌復電",
    "三軌負電": "三軌復電",
    "三鬼復電": "三軌復電",
    "三鬼佈線": "三軌佈線",
    
    # 其他高頻錯誤
    "請先稍後": "請稍後",
    "清稍後": "請稍後",
    "情稍候": "請稍後",
    
    "目是範圍內": "目視範圍內",
    "木視範圍": "目視範圍",
    
    "無現一輛": "無發現異常",
    "無發現以常": "無發現異常",
    
    "鬼島設備": "軌道設備",
    "規道設備": "軌道設備",
    
    "有一常": "有異常",
    "有以常": "有異常",
    
    "等上列車": "登上列車",
    "登上捷捷車": "登上列車",
    
    "請人員到": "請人員至",
    "情人員至": "請人員至",
}


# ============================================================================
# 階段 3: 車站代碼格式化
# ============================================================================

def fix_station_codes(text: str) -> str:
    """
    修正車站代碼格式
    
    測試結果顯示的問題：
    - "G7" → "g 7", "G 7", "g7"
    - "G11" → "11"
    
    目標：統一為 "G07", "G11" 格式
    """
    # Pattern 1: "G 0 7" → "G07"
    text = re.sub(r'([GR])\s*(\d)\s*(\d)', r'\1\2\3', text)
    
    # Pattern 2: "g 7" → "G07"（小寫轉大寫）
    text = re.sub(r'([gr])\s*(\d+)', lambda m: m.group(1).upper() + m.group(2).zfill(2), text)
    
    # Pattern 3: "G7" → "G07"（補零）
    text = re.sub(r'([GR])(\d)(?!\d)', r'\g<1>0\2', text)
    
    # Pattern 4: 處理特殊格式 "G 零 七" → "G07"
    number_map = {
        '零': '0', '洞': '0',
        '一': '1', '腰': '1', '么': '1',
        '二': '2', '兩': '2',
        '三': '3',
        '四': '4',
        '五': '5',
        '六': '6',
        '七': '7', '拐': '7',
        '八': '8',
        '九': '9', '勾': '9', '鉤': '9'
    }
    
    def convert_chinese_station(match):
        letter = match.group(1).upper()
        num1 = number_map.get(match.group(2), match.group(2))
        num2 = number_map.get(match.group(3), match.group(3))
        return f"{letter}{num1}{num2}"
    
    text = re.sub(r'([GRgr])\s*([零洞一腰么二兩三四五六七拐八九勾鉤])\s*([零洞一腰么二兩三四五六七拐八九勾鉤])', 
                  convert_chinese_station, text)
    
    return text


# ============================================================================
# 階段 4: 數字爆炸修正（關鍵！測試結果顯示數到 140+）
# ============================================================================

def fix_number_explosion(text: str) -> str:
    """
    修正數字爆炸問題
    
    測試結果：
    "11月台223車停柵門無法開門謝謝。好,謝收到。12345678910111213141516...140+"
    
    策略：
    1. 偵測連續數字串（長度 > 20）
    2. 嘗試解析為有意義的數字
    3. 無法解析則標記為錯誤
    """
    # 偵測異常長數字串（超過 20 位）
    def replace_explosion(match):
        num_str = match.group(0)
        
        # 嘗試提取前幾位數字作為真實數值
        # 例如："12345678..." → 提取 "1", "2", "3" 開頭的可能性
        
        # 策略 1: 如果是站台編號 (1-20)
        if num_str.startswith('1') and len(num_str) > 10:
            # 可能是 "11月台" → "11"
            return num_str[:2] if num_str[1].isdigit() else num_str[0]
        
        # 策略 2: 如果是車號 (01-30)
        if num_str.startswith('0') or (num_str.startswith('2') and len(num_str) > 10):
            return num_str[:2]
        
        # 無法解析，標記為錯誤
        return "[數字識別異常]"
    
    # 替換超過 15 位的連續數字
    text = re.sub(r'\d{15,}', replace_explosion, text)
    
    return text


# ============================================================================
# 階段 5: 車組編號格式化
# ============================================================================

def fix_train_numbers(text: str) -> str:
    """
    修正車組編號格式
    
    測試結果：
    - "25/26車" → "兩兩車", "2526車"
    - "05/06車" → "動六車"
    
    目標：統一為 "XX/XX車" 格式
    """
    # Pattern 1: "2526車" → "25/26車"
    text = re.sub(r'(\d{2})(\d{2})車', r'\1/\2車', text)
    
    # Pattern 2: "25 26車" → "25/26車"
    text = re.sub(r'(\d{2})\s+(\d{2})車', r'\1/\2車', text)
    
    # Pattern 3: "二五二六車" → "25/26車"（中文數字轉換）
    if CN2AN_AVAILABLE:
        # 匹配中文數字對
        chinese_nums = re.findall(r'([零一二三四五六七八九十百]{2,4})車', text)
        for cn_num in chinese_nums:
            try:
                # 嘗試轉換為數字
                num = cn2an.cn2an(cn_num, "smart")
                if 1 <= num <= 99:
                    text = text.replace(f"{cn_num}車", f"{num:02d}車")
            except Exception:
                pass
    
    return text


# ============================================================================
# 主要清洗函數
# ============================================================================

class RadioTextCleaner:
    """無線電文字清洗器 v2.0"""
    
    def __init__(self, correction_dict_path: Optional[str] = None):
        """
        初始化清洗器
        
        Args:
            correction_dict_path: 外部修正字典路徑（可選）
        """
        self.corrections = {**CRITICAL_TERMS, **HOMOPHONE_CORRECTIONS}
        
        # 載入外部修正字典（如果提供）
        if correction_dict_path:
            self.load_correction_dict(correction_dict_path)
    
    def load_correction_dict(self, dict_path: str) -> None:
        """載入外部修正字典"""
        try:
            # 嘗試載入 Python 模組
            if dict_path.endswith('.py'):
                import importlib.util
                spec = importlib.util.spec_from_file_location("corrections", dict_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # 支援兩種變數命名：CORRECTION_DICT（vocabulary_generator 產生）
                # 或 RADIO_CORRECTIONS（舊版相容）
                loaded = None
                if hasattr(module, 'CORRECTION_DICT'):
                    loaded = module.CORRECTION_DICT
                elif hasattr(module, 'RADIO_CORRECTIONS'):
                    loaded = module.RADIO_CORRECTIONS

                if loaded:
                    self.corrections.update(loaded)
                    logger.info(f"載入外部修正字典: {len(loaded)} 條規則")
            
            # 嘗試載入 JSON
            elif dict_path.endswith('.json'):
                with open(dict_path, 'r', encoding='utf-8') as f:
                    external_corrections = json.load(f)
                    self.corrections.update(external_corrections)
                    logger.info(f"載入外部修正字典: {len(external_corrections)} 條規則")
        
        except Exception as e:
            logger.warning(f"載入外部修正字典失敗: {e}")
    
    def clean(self, text: str, aggressive: bool = True) -> str:
        """
        完整的清洗流程

        ⚠️ DEAD（2026-06-16 第二波）：fix_radio_jargon 改走 canonical 核心後，
        本方法已無生產引用（clean_text 走的是 clean_for_evaluation）。
        其 corrections / fix_station_codes / fix_number_explosion /
        fix_train_numbers 與 scripts/post_process.py 各階段功能重複，
        保留待專門清理波次移除，勿在新程式碼引用。

        Args:
            text: 待清洗的文字
            aggressive: 是否啟用激進修正（包括數字爆炸、格式化等）

        Returns:
            清洗後的文字
        """
        if not text:
            return ""
        
        # 階段 1+2: 統一套用所有修正規則
        # self.corrections 包含：CRITICAL_TERMS + HOMOPHONE_CORRECTIONS + correction_dict.py 外部規則
        for wrong, correct in self.corrections.items():
            text = text.replace(wrong, correct)
        
        # 階段 3: 車站代碼格式化
        text = fix_station_codes(text)
        
        if aggressive:
            # 階段 4: 數字爆炸修正
            text = fix_number_explosion(text)
            
            # 階段 5: 車組編號格式化
            text = fix_train_numbers(text)
        
        # 階段 6: 多餘空白清理
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def clean_for_evaluation(self, text: str) -> str:
        """
        用於評測的清洗（保守模式）
        
        只進行必要的清洗，避免過度修正影響 CER/TER 計算
        """
        # 移除標點符號
        text = re.sub(r'[，。！？、；：「」『』（）《》\[\],.!?;:\'\"\(\)<>]', '', text)
        
        # 移除多餘空白
        text = re.sub(r'\s+', '', text)
        
        # 簡繁轉換
        if OPENCC_AVAILABLE:
            cc = OpenCC('s2t')
            text = cc.convert(text)
        
        return text.strip()
    
    def get_stats(self, original: str, cleaned: str) -> Dict:
        """計算清洗統計"""
        return {
            'original_length': len(original),
            'cleaned_length': len(cleaned),
            'corrections_applied': sum(
                1 for wrong in self.corrections.keys() if wrong in original
            ),
            'length_change': len(cleaned) - len(original)
        }


# ============================================================================
# 便利函數（向後相容）
# ============================================================================

# 自動掛載 vocabulary/correction_dict.py（第二層詞彙）
_correction_dict_path = Path(__file__).parent.parent / "vocabulary" / "correction_dict.py"
_default_cleaner = RadioTextCleaner(
    correction_dict_path=str(_correction_dict_path) if _correction_dict_path.exists() else None
)

def fix_radio_jargon(text: str) -> str:
    """修正無線電術語（向後相容 wrapper）。

    2026-06-16 第二波收斂：本函式不再跑 RadioTextCleaner.clean() 那套
    與 post_process 重複的 deterministic 規則，改為轉呼叫 canonical 核心
    scripts.post_process_runtime.post_process_realtime()（deterministic、
    永不呼叫 LLM），杜絕兩套規則漂移。API 簽名與回傳型別不變。
    import 放在函式內，避免 import cycle 並保持模組載入成本。
    """
    from scripts.post_process_runtime import post_process_realtime
    return post_process_realtime(text)[0]

def clean_text(text: str, keep_punctuation: bool = False) -> str:
    """清洗文字（向後相容函數）"""
    return _default_cleaner.clean_for_evaluation(text)


# ============================================================================
# 測試與驗證
# ============================================================================

def test_cleaner():
    """測試清洗器"""
    print("\n" + "="*80)
    print("無線電文字清洗器 v2.0 測試")
    print("="*80)
    
    test_cases = [
        # 測試案例（從您的測試結果提取）
        ("10001000鬼旁修牆下方電腦狀況有一常是立起回報", 
         "10001000軌旁胸牆下方電纜狀況有異常是立即回報"),
        
        ("呼告全新全新線,請全新更長自一集至月台協助確認列車有停準的列車及協助以 ncp 開啟列車門後協助陸客下車通告",
         "呼叫通告全線,請全線各站長自一集至月台協助確認列車有停準的列車及協助以MCP開啟列車門後協助旅客下車通告"),
        
        ("2062020開車",
         "20/62/02/0開車"),  # 這個可能需要更智慧的處理
        
        ("11月台223車停柵門無法開門謝謝。好,謝收到。12345678910111213141516171819202122232425262728293031323334353637383940",
         "11月台22/3車停柵門無法開門謝謝。好,謝收到。[數字識別異常]"),
        
        ("現況將進行 g 7不含月台以南進行正線三行三鬼附電作業",
         "現況將進行G07不含月台以南進行正線三行三軌復電作業"),
    ]
    
    cleaner = RadioTextCleaner()
    
    for i, (original, expected) in enumerate(test_cases, 1):
        cleaned = cleaner.clean(original)
        
        print(f"\n測試 {i}:")
        print(f"  原文: {original[:60]}...")
        print(f"  清洗: {cleaned[:60]}...")
        print(f"  預期: {expected[:60]}...")
        
        stats = cleaner.get_stats(original, cleaned)
        print(f"  統計: 修正了 {stats['corrections_applied']} 處錯誤")
    
    print("\n" + "="*80)
    print("測試完成")
    print("="*80)


if __name__ == "__main__":
    test_cleaner()
