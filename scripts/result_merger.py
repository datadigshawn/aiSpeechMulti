#!/usr/bin/env python3
"""
結果合併模組
將多個 ASR 模型的辨識結果合併為統一的 CSV 檔案
"""

import sys
from pathlib import Path

# 添加專案路徑
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
from typing import Dict, List
from utils.logger import get_logger
from utils.config import get_config


class ResultMerger:
    """ASR 結果合併器"""
    
    def __init__(self):
        """初始化結果合併器"""
        self.logger = get_logger(self.__class__.__name__)
        self.config = get_config()
        
        self.logger.info("ResultMerger 初始化完成")
    
    def merge_results(
        self,
        ground_truth_dir: Path,
        model_output_dirs: Dict[str, Path],
        output_csv: Path
    ) -> pd.DataFrame:
        """
        合併多個模型的辨識結果
        
        Args:
            ground_truth_dir: Ground Truth 目錄
            model_output_dirs: 模型輸出目錄字典 {"模型名稱": Path}
            output_csv: 輸出 CSV 路徑
        
        Returns:
            合併後的 DataFrame
        """
        self.logger.info("開始合併 ASR 結果...")
        
        # 掃描 Ground Truth 檔案
        gt_files = sorted(ground_truth_dir.glob("*.txt"))
        
        if not gt_files:
            self.logger.error(f"在 {ground_truth_dir} 中未找到任何 .txt 檔案")
            return pd.DataFrame()
        
        self.logger.info(f"找到 {len(gt_files)} 個 Ground Truth 檔案")
        
        # 建立資料結構
        results = []
        
        for gt_file in gt_files:
            filename = gt_file.stem  # 不含副檔名的檔名
            
            # 讀取 Ground Truth
            with open(gt_file, 'r', encoding='utf-8') as f:
                ground_truth = f.read().strip()
            
            # 建立該檔案的結果字典
            row = {
                'filename': filename,
                'ground_truth': ground_truth
            }
            
            # 讀取各模型的辨識結果
            for model_name, model_dir in model_output_dirs.items():
                model_file = model_dir / f"{filename}.txt"
                
                if model_file.exists():
                    with open(model_file, 'r', encoding='utf-8') as f:
                        model_output = f.read().strip()
                    row[model_name] = model_output
                else:
                    self.logger.warning(f"模型 {model_name} 缺少檔案: {filename}.txt")
                    row[model_name] = ""
            
            results.append(row)
        
        # 轉換為 DataFrame
        df = pd.DataFrame(results)
        
        # 儲存 CSV
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        
        self.logger.info(f"✅ 結果已合併並儲存至: {output_csv}")
        self.logger.info(f"   總共 {len(df)} 筆資料，{len(model_output_dirs)} 個模型")
        
        return df
    
    def preview_results(self, df: pd.DataFrame, num_rows: int = 5):
        """
        預覽合併結果
        
        Args:
            df: 合併後的 DataFrame
            num_rows: 顯示的行數
        """
        print("\n" + "=" * 80)
        print("ASR 結果預覽 (前 {} 筆)".format(num_rows))
        print("=" * 80)
        
        for idx, row in df.head(num_rows).iterrows():
            print(f"\n檔案: {row['filename']}")
            print(f"Ground Truth: {row['ground_truth']}")
            
            for col in df.columns:
                if col not in ['filename', 'ground_truth']:
                    print(f"{col}: {row[col]}")
            
            print("-" * 80)


def main():
    """主函數 - 命令列介面"""
    import argparse
    
    parser = argparse.ArgumentParser(description="ASR 結果合併工具")
    parser.add_argument("ground_truth", type=Path, help="Ground Truth 目錄")
    parser.add_argument("output_csv", type=Path, help="輸出 CSV 檔案")
    parser.add_argument(
        "--models",
        nargs='+',
        help="模型輸出目錄 (格式: 模型名稱=路徑)"
    )
    
    args = parser.parse_args()
    
    # 解析模型目錄
    model_dirs = {}
    if args.models:
        for model_spec in args.models:
            name, path = model_spec.split('=')
            model_dirs[name] = Path(path)
    
    # 執行合併
    merger = ResultMerger()
    df = merger.merge_results(
        ground_truth_dir=args.ground_truth,
        model_output_dirs=model_dirs,
        output_csv=args.output_csv
    )
    
    # 預覽結果
    if not df.empty:
        merger.preview_results(df)
        print(f"\n✅ 完成！結果已儲存至: {args.output_csv}")


if __name__ == "__main__":
    main()
