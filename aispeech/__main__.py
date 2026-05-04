"""aiSpeechMulti 統一 CLI（python -m aispeech）。

對映關係（thin wrapper，所有未識別的參數會原樣透傳）：

    finetune          → python scripts/finetune_sensevoice.py
    infer             → python scripts/batch_inference.py
    infer-ft-all      → python scripts/_inference_finetuned_all.py
    eval              → python scripts/eval_finetuned_model.py
    eval-batch        → python scripts/batch_stt_eval.py
    ensemble          → python scripts/ensemble_eval.py
    data build-manifest        → python scripts/build_golden_manifest.py
    data build-finetune        → python scripts/build_finetune_dataset.py
    data build-lm              → python scripts/build_ngram_lm.py
    data extract-errors        → python scripts/extract_error_pairs.py
    data extract-regression    → python scripts/extract_regression_cases.py
    data export-feedback       → python scripts/export_correction_feedback.py
    serve api         → python app_api.py
    serve lab         → streamlit run app_lab.py
    serve all         → 同時起 api + lab（前景跑，Ctrl-C 一起停）

設計原則：
- 不動既有 scripts/*.py，所有舊指令仍能直接跑（並行入口，非取代）
- 只用 stdlib argparse + subprocess，零新增依賴
- 未識別的旗標一律透傳，例如：
    python -m aispeech finetune --mode lora --lora-rank 32
  等價於：
    python scripts/finetune_sensevoice.py --mode lora --lora-rank 32
"""

from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ─── 子命令對映 ────────────────────────────────────────────────────────
SCRIPT_MAP = {
    "finetune":     "scripts/finetune_sensevoice.py",
    "infer":        "scripts/batch_inference.py",
    "infer-ft-all": "scripts/_inference_finetuned_all.py",
    "eval":         "scripts/eval_finetuned_model.py",
    "eval-batch":   "scripts/batch_stt_eval.py",
    "ensemble":     "scripts/ensemble_eval.py",
}

DATA_SUBMAP = {
    "build-manifest":     "scripts/build_golden_manifest.py",
    "build-finetune":     "scripts/build_finetune_dataset.py",
    "build-lm":           "scripts/build_ngram_lm.py",
    "extract-errors":     "scripts/extract_error_pairs.py",
    "extract-regression": "scripts/extract_regression_cases.py",
    "export-feedback":    "scripts/export_correction_feedback.py",
    "sync-cer":           "scripts/sync_cer_to_sqlite.py",  # P2: CER CSV → SQLite (供 Grafana)
}


def _run(script_rel: str, passthrough: list[str]) -> int:
    """以 subprocess 執行 python <script_rel> <passthrough...>，回傳 exit code。"""
    script_path = PROJECT_ROOT / script_rel
    if not script_path.exists():
        print(f"❌ 找不到腳本：{script_path}", file=sys.stderr)
        return 2
    cmd = [sys.executable, str(script_path), *passthrough]
    print(f"$ {' '.join(shlex.quote(c) for c in cmd)}", file=sys.stderr)
    return subprocess.call(cmd, cwd=PROJECT_ROOT)


def _serve(target: str) -> int:
    """serve 子命令：起 api / lab / all。"""
    if target == "api":
        return subprocess.call([sys.executable, "app_api.py"], cwd=PROJECT_ROOT)

    if target == "lab":
        return subprocess.call(
            ["streamlit", "run", "app_lab.py"],
            cwd=PROJECT_ROOT,
        )

    if target == "all":
        # 前景同時跑兩支，Ctrl-C 廣播給兩個子程序
        api_proc = subprocess.Popen([sys.executable, "app_api.py"], cwd=PROJECT_ROOT)
        lab_proc = subprocess.Popen(
            ["streamlit", "run", "app_lab.py"], cwd=PROJECT_ROOT
        )

        def _shutdown(signum, frame):
            for p in (api_proc, lab_proc):
                if p.poll() is None:
                    p.send_signal(signal.SIGINT)

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        rc1 = api_proc.wait()
        rc2 = lab_proc.wait()
        return rc1 or rc2

    print(f"❌ 未知 serve 目標：{target}（可用：api / lab / all）", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        prog="python -m aispeech",
        description="aiSpeechMulti 統一 CLI（thin wrapper 包 scripts/*.py）",
        epilog="未識別的旗標會原樣透傳給對應腳本。例：python -m aispeech finetune --lora-rank 32 --epochs 60",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="<cmd>")

    # 一般子命令（透傳）
    for name in SCRIPT_MAP:
        sub.add_parser(name, help=f"→ {SCRIPT_MAP[name]} (透傳)", add_help=False)

    # data 子命令
    p_data = sub.add_parser("data", help="資料管線（build / extract / export）")
    p_data_sub = p_data.add_subparsers(dest="data_cmd", metavar="<data_cmd>")
    for name in DATA_SUBMAP:
        p_data_sub.add_parser(name, help=f"→ {DATA_SUBMAP[name]} (透傳)", add_help=False)

    # serve 子命令
    p_serve = sub.add_parser("serve", help="起服務（api / lab / all）")
    p_serve.add_argument("target", choices=("api", "lab", "all"))

    # 沒帶子命令 → 印 help
    if not argv:
        parser.print_help()
        return 0

    cmd = argv[0]
    rest = argv[1:]

    if cmd in SCRIPT_MAP:
        return _run(SCRIPT_MAP[cmd], rest)

    if cmd == "data":
        if not rest or rest[0] not in DATA_SUBMAP:
            p_data.print_help()
            print(f"\n可用 data_cmd：{', '.join(DATA_SUBMAP.keys())}", file=sys.stderr)
            return 0 if not rest else 2
        return _run(DATA_SUBMAP[rest[0]], rest[1:])

    if cmd == "serve":
        if not rest:
            p_serve.print_help()
            return 2
        return _serve(rest[0])

    if cmd in ("-h", "--help", "help"):
        parser.print_help()
        return 0

    print(f"❌ 未知子命令：{cmd}", file=sys.stderr)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
