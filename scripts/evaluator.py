#!/usr/bin/env python3
"""
評測模組
計算 CER (字元錯誤率) 和 TER (關鍵術語錯誤率)
"""

import sys
from pathlib import Path

# 添加專案路徑
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import jiwer
from typing import Dict, List, Tuple
import matplotlib.pyplot as plt

from utils.logger import get_logger
from utils.config import get_config
from utils.text_cleaner import clean_text, normalize_for_evaluation


class Evaluator:
    """ASR 評測器"""
    
    def __init__(self):
        """初始化評測器"""
        self.logger = get_logger(self.__class__.__name__)
        self.config = get_config()
        
        # 設定中文字型 (matplotlib)
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'Microsoft JhengHei', 'SimHei']
        plt.rcParams['axes.unicode_minus'] = False
        
        self.logger.info("Evaluator 初始化完成")
    
    def calculate_cer(
        self,
        reference: str,
        hypothesis: str,
        normalize: bool = True
    ) -> float:
        """
        計算字元錯誤率 (CER)
        
        Args:
            reference: 參考答案
            hypothesis: 辨識結果
            normalize: 是否進行文字標準化
        
        Returns:
            CER 值 (0-1 之間)
        """
        if normalize:
            reference, hypothesis = normalize_for_evaluation(reference, hypothesis)
        
        try:
            cer = jiwer.cer(reference, hypothesis)
            return cer
        except Exception as e:
            self.logger.error(f"CER 計算錯誤: {e}")
            return 1.0  # 回傳最差的錯誤率
    
    def calculate_ter(
        self,
        reference: str,
        hypothesis: str,
        key_terms: List[str]
    ) -> Tuple[float, Dict]:
        """
        計算關鍵術語錯誤率 (TER)
        
        Args:
            reference: 參考答案
            hypothesis: 辨識結果
            key_terms: 關鍵術語列表
        
        Returns:
            (TER 值, 詳細資訊字典)
        """
        # 清洗文字
        ref_clean = clean_text(reference)
        hyp_clean = clean_text(hypothesis)
        
        # 統計關鍵術語
        total_terms = 0
        correct_terms = 0
        errors = []
        
        for term in key_terms:
            if term in ref_clean:
                total_terms += 1
                if term in hyp_clean:
                    correct_terms += 1
                else:
                    errors.append(f"漏失: {term}")
        
        # 計算 TER
        ter = 0.0 if total_terms == 0 else (total_terms - correct_terms) / total_terms
        
        details = {
            'total_terms': total_terms,
            'correct_terms': correct_terms,
            'errors': errors
        }
        
        return ter, details
    
    def evaluate_dataframe(
        self,
        df: pd.DataFrame,
        model_columns: List[str],
        key_terms: List[str] = None
    ) -> pd.DataFrame:
        """
        對整個 DataFrame 進行評測
        
        Args:
            df: 包含 ground_truth 和模型輸出的 DataFrame
            model_columns: 模型輸出欄位名稱列表
            key_terms: 關鍵術語列表 (用於 TER 計算)
        
        Returns:
            包含評測結果的 DataFrame
        """
        self.logger.info(f"開始評測 {len(df)} 筆資料...")
        
        results = []
        
        for _, row in df.iterrows():
            ground_truth = row['ground_truth']
            result_row = {'filename': row['filename']}
            
            for model_name in model_columns:
                hypothesis = row[model_name]
                
                # 計算 CER
                cer = self.calculate_cer(ground_truth, hypothesis)
                result_row[f'{model_name}_CER'] = cer
                
                # 計算 TER (如果有關鍵術語)
                if key_terms:
                    ter, _ = self.calculate_ter(ground_truth, hypothesis, key_terms)
                    result_row[f'{model_name}_TER'] = ter
            
            results.append(result_row)
        
        results_df = pd.DataFrame(results)
        
        self.logger.info("✅ 評測完成")
        return results_df
    
    def calculate_statistics(
        self,
        results_df: pd.DataFrame,
        model_columns: List[str]
    ) -> Dict:
        """
        計算統計資訊
        
        Args:
            results_df: 評測結果 DataFrame
            model_columns: 模型名稱列表
        
        Returns:
            統計資訊字典
        """
        stats = {}
        
        for model_name in model_columns:
            cer_col = f'{model_name}_CER'
            
            if cer_col in results_df.columns:
                stats[model_name] = {
                    'mean_CER': results_df[cer_col].mean(),
                    'median_CER': results_df[cer_col].median(),
                    'std_CER': results_df[cer_col].std(),
                    'min_CER': results_df[cer_col].min(),
                    'max_CER': results_df[cer_col].max()
                }
                
                # TER (如果有)
                ter_col = f'{model_name}_TER'
                if ter_col in results_df.columns:
                    stats[model_name]['mean_TER'] = results_df[ter_col].mean()
        
        return stats
    
    def plot_comparison(
        self,
        stats: Dict,
        output_path: Path = None
    ):
        """
        繪製模型比較圖表
        
        Args:
            stats: 統計資訊字典
            output_path: 輸出圖片路徑
        """
        models = list(stats.keys())
        cer_values = [stats[m]['mean_CER'] for m in models]
        
        plt.figure(figsize=(10, 6))
        plt.bar(models, cer_values, color='steelblue', alpha=0.7)
        plt.xlabel('模型', fontsize=12)
        plt.ylabel('平均 CER', fontsize=12)
        plt.title('ASR 模型 CER 比較', fontsize=14, fontweight='bold')
        plt.ylim(0, max(cer_values) * 1.2)
        
        # 在柱狀圖上標註數值
        for i, v in enumerate(cer_values):
            plt.text(i, v + 0.01, f'{v:.2%}', ha='center', va='bottom')
        
        plt.tight_layout()
        
        if output_path:
            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            self.logger.info(f"圖表已儲存至: {output_path}")
        else:
            plt.show()
        
        plt.close()


def main():
    """主函數 - 命令列介面"""
    import argparse
    
    parser = argparse.ArgumentParser(description="ASR 評測工具")
    parser.add_argument("input_csv", type=Path, help="合併後的 CSV 檔案")
    parser.add_argument("output_csv", type=Path, help="評測結果 CSV")
    parser.add_argument(
        "--models",
        nargs='+',
        required=True,
        help="模型名稱列表"
    )
    parser.add_argument("--plot", type=Path, help="輸出圖表路徑")
    
    args = parser.parse_args()
    
    # 讀取資料
    df = pd.read_csv(args.input_csv)
    
    # 執行評測
    evaluator = Evaluator()
    results_df = evaluator.evaluate_dataframe(df, args.models)
    
    # 儲存結果
    results_df.to_csv(args.output_csv, index=False, encoding='utf-8-sig')
    
    # 計算統計
    stats = evaluator.calculate_statistics(results_df, args.models)
    
    print("\n" + "=" * 60)
    print("評測結果統計")
    print("=" * 60)
    
    for model, model_stats in stats.items():
        print(f"\n{model}:")
        print(f"  平均 CER: {model_stats['mean_CER']:.2%}")
        print(f"  中位數 CER: {model_stats['median_CER']:.2%}")
        print(f"  標準差: {model_stats['std_CER']:.2%}")
    
    # 繪製圖表
    if args.plot:
        evaluator.plot_comparison(stats, args.plot)
    
    print(f"\n✅ 評測完成！結果已儲存至: {args.output_csv}")


if __name__ == "__main__":
    main()
