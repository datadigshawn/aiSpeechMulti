#!/usr/bin/env python3
"""
語音辨識完整執行腳本
一步一步帶您完成從音檔切分到評測的完整流程
"""

import os
import sys
from pathlib import Path

# 添加專案路徑
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def print_step(step_num, title):
    """列印步驟標題"""
    print("\n" + "=" * 70)
    print(f"步驟 {step_num}: {title}")
    print("=" * 70)


def check_environment():
    """檢查環境設定"""
    print_step(0, "環境檢查")
    
    issues = []
    
    # 檢查 .env 檔案
    env_file = project_root / ".env"  # check .env file
    if not env_file.exists():
        issues.append("❌ 找不到 .env 檔案")
        print("   請執行: cp .env.example .env")
        print("   然後編輯 .env 填入您的 API 金鑰")
    else:
        print("✅ .env 檔案存在")
    
    # 檢查必要目錄
    required_dirs = [
        "vocabulary",
        "utils",
        "scripts",
        "experiments"
    ]
    
    for dir_name in required_dirs:
        dir_path = project_root / dir_name
        if not dir_path.exists():
            issues.append(f"❌ 找不到目錄: {dir_name}")
        else:
            print(f"✅ {dir_name}/ 目錄存在")
    
    # 檢查關鍵檔案
    key_files = [
        "vocabulary/master_vocabulary.csv",
        "utils/logger.py",
        "utils/text_cleaner.py",
        "scripts/audio_splitter.py",
        "scripts/batch_inference.py"
    ]
    
    for file_path in key_files:
        full_path = project_root / file_path
        if not full_path.exists():
            issues.append(f"❌ 找不到檔案: {file_path}")
    
    if issues:
        print("\n⚠️  發現以下問題:")
        for issue in issues:
            print(f"   {issue}")
        return False
    else:
        print("\n✅ 環境檢查通過！")
        return True


def step1_generate_vocabulary():
    """步驟1: 生成詞彙表"""
    print_step(1, "生成詞彙表（三重應用）")
    
    vocab_script = project_root / "vocabulary" / "generate_vocabulary_files.py"
    
    if not vocab_script.exists():
        print("❌ 找不到 generate_vocabulary_files.py")
        return False
    
    print("\n執行命令:")
    print(f"  python {vocab_script}")
    print("\n按 Enter 繼續執行...")
    input()
    
    os.system(f"python {vocab_script}")
    
    # 檢查輸出檔案
    expected_files = [
        "vocabulary/google_phrases.json",
        "vocabulary/correction_dict.py",
        "vocabulary/alert_keywords.json"
    ]
    
    print("\n檢查輸出檔案:")
    all_exists = True
    for file_path in expected_files:
        full_path = project_root / file_path
        if full_path.exists():
            print(f"  ✅ {file_path}")
        else:
            print(f"  ❌ {file_path}")
            all_exists = False
    
    return all_exists


def step2_prepare_test_data():
    """步驟2: 準備測試資料"""
    print_step(2, "準備測試資料")
    
    print("\n請確認以下事項:")
    print("  1. 測試音檔已放入 experiments/Test_02_TMRT/source_audio/")
    print("  2. 音檔格式為 .wav, .mp3 或 .m4a")
    
    # 檢查音檔
    test_case = "Test_02_TMRT"
    source_dir = project_root / "experiments" / test_case / "source_audio"
    
    if not source_dir.exists():
        print(f"\n❌ 找不到目錄: {source_dir}")
        print(f"   正在建立...")
        source_dir.mkdir(parents=True, exist_ok=True)
    
    audio_files = list(source_dir.glob("*.wav")) + list(source_dir.glob("*.mp3")) + list(source_dir.glob("*.m4a"))
    
    print(f"\n找到 {len(audio_files)} 個音檔:")
    for i, audio_file in enumerate(audio_files[:5], 1):
        size_mb = audio_file.stat().st_size / (1024 * 1024)
        print(f"  {i}. {audio_file.name} ({size_mb:.2f} MB)")
    
    if len(audio_files) > 5:
        print(f"  ... 還有 {len(audio_files) - 5} 個檔案")
    
    if len(audio_files) == 0:
        print("\n⚠️  沒有找到音檔！")
        print("   請將音檔放入上述目錄後再繼續。")
        return False
    
    print("\n準備好了嗎？按 Enter 繼續...")
    input()
    return True


def step3_split_audio():
    """步驟3: 切分音檔"""
    print_step(3, "使用 VAD 切分音檔")
    
    test_case = "Test_02_TMRT"
    source_dir = project_root / "experiments" / test_case / "source_audio"
    output_dir = project_root / "experiments" / test_case / "dataset_chunks"
    
    # 取得第一個音檔
    audio_files = list(source_dir.glob("*.wav")) + list(source_dir.glob("*.mp3"))
    
    if not audio_files:
        print("❌ 找不到音檔")
        return False
    
    audio_file = audio_files[0]
    
    print(f"\n將要處理的音檔: {audio_file.name}")
    print(f"輸出目錄: {output_dir}")
    
    cmd = f"""python scripts/audio_splitter.py \\
  {audio_file} \\
  --output-dir {output_dir} \\
  --test-case {test_case} \\
  --vad-engine silero \\
  --threshold 0.5"""
    
    print("\n執行命令:")
    print(cmd)
    print("\n按 Enter 開始切分...")
    input()
    
    os.system(cmd.replace("\\", ""))
    
    # 檢查輸出
    if output_dir.exists():
        chunks = list(output_dir.glob("chunk_*.wav"))
        print(f"\n✅ 切分完成！產生 {len(chunks)} 個切片")
        return True
    else:
        print("\n❌ 切分失敗")
        return False


def step4_batch_inference():
    """步驟4: 批次辨識"""
    print_step(4, "批次語音辨識")
    
    test_case = "Test_02_TMRT"
    input_dir = project_root / "experiments" / test_case / "dataset_chunks"
    
    print("\n請選擇要使用的模型:")
    print("  1. Whisper (本地執行，不需 API 金鑰)")
    print("  2. Google STT (需要 Google Cloud 憑證)")
    print("  3. Gemini (需要 Gemini API 金鑰)")
    print("  4. 全部執行")
    
    choice = input("\n請輸入選項 (1-4): ").strip()
    
    models = []
    if choice == "1":
        models = ["whisper"]
    elif choice == "2":
        models = ["google_stt"]
    elif choice == "3":
        models = ["gemini"]
    elif choice == "4":
        models = ["whisper", "google_stt", "gemini"]
    else:
        print("無效的選項")
        return False
    
    vocab_file = project_root / "vocabulary" / "google_phrases.json"
    
    for model in models:
        output_dir = project_root / "experiments" / test_case / "ASR_Evaluation" / f"{model}_output"
        
        cmd = f"""python scripts/batch_inference.py \\
  --model {model} \\
  --input-dir {input_dir} \\
  --output-dir {output_dir} \\
  --vocabulary {vocab_file}"""
        
        print(f"\n執行 {model.upper()} 辨識...")
        print(cmd)
        print()
        
        os.system(cmd.replace("\\", ""))
    
    print("\n✅ 批次辨識完成！")
    return True


def step5_merge_results():
    """步驟5: 合併結果"""
    print_step(5, "合併多模型辨識結果")
    
    test_case = "Test_02_TMRT"
    eval_dir = project_root / "experiments" / test_case / "ASR_Evaluation"
    chunks_timeline = project_root / "experiments" / test_case / "dataset_chunks" / "chunks_timeline.json"
    
    cmd = f"""python scripts/result_merger.py \\
  {eval_dir} \\
  --create-timestamped \\
  --chunks-timeline {chunks_timeline}"""
    
    print("\n執行命令:")
    print(cmd)
    print("\n按 Enter 繼續...")
    input()
    
    os.system(cmd.replace("\\", ""))
    
    # 檢查輸出
    csv_file = eval_dir / "asr_results.csv"
    if csv_file.exists():
        print(f"\n✅ 結果合併完成！")
        print(f"   輸出檔案: {csv_file}")
        return True
    else:
        print("\n⚠️  未產生 CSV 檔案（可能需要先準備 ground_truth）")
        return True


def step6_evaluate():
    """步驟6: 評測"""
    print_step(6, "計算 CER/TER 並生成報表")
    
    test_case = "Test_02_TMRT"
    results_csv = project_root / "experiments" / test_case / "ASR_Evaluation" / "asr_results.csv"
    alert_keywords = project_root / "vocabulary" / "alert_keywords.json"
    
    if not results_csv.exists():
        print(f"❌ 找不到結果檔案: {results_csv}")
        print("   請先執行步驟 5 (合併結果)")
        return False
    
    cmd = f"""python scripts/evaluator.py \\
  {results_csv} \\
  --key-terms {alert_keywords}"""
    
    print("\n執行命令:")
    print(cmd)
    print("\n按 Enter 繼續...")
    input()
    
    os.system(cmd.replace("\\", ""))
    
    print("\n✅ 評測完成！")
    return True


def main():
    """主流程"""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 18 + "aiSpeech 語音辨識執行嚮導" + " " * 22 + "║")
    print("╚" + "=" * 68 + "╝")
    
    # 環境檢查
    if not check_environment():
        print("\n❌ 環境檢查失敗，請先解決上述問題")
        return
    
    # 執行流程
    steps = [
        ("生成詞彙表", step1_generate_vocabulary),
        ("準備測試資料", step2_prepare_test_data),
        ("切分音檔", step3_split_audio),
        ("批次辨識", step4_batch_inference),
        ("合併結果", step5_merge_results),
        ("評測報告", step6_evaluate),
    ]
    
    print("\n完整執行流程:")
    for i, (title, _) in enumerate(steps, 1):
        print(f"  步驟 {i}: {title}")
    
    print("\n開始執行？(y/n): ", end="")
    if input().lower() != 'y':
        print("已取消")
        return
    
    # 執行各步驟
    for i, (title, func) in enumerate(steps, 1):
        success = func()
        
        if not success:
            print(f"\n❌ 步驟 {i} 執行失敗")
            print("是否繼續下一步驟？(y/n): ", end="")
            if input().lower() != 'y':
                print("已中止")
                return
    
    # 完成
    print("\n" + "=" * 70)
    print("✨ 所有步驟執行完成！")
    print("=" * 70)
    print("\n輸出檔案位置:")
    print("  experiments/Test_02_TMRT/ASR_Evaluation/")
    print("    ├── asr_results.csv          (合併結果)")
    print("    ├── evaluation_report.csv    (評測報告)")
    print("    ├── accuracy_comparison.png  (比較圖表)")
    print("    └── timestamped_*.json       (含時間戳結果)")
    print()


if __name__ == "__main__":
    main()
