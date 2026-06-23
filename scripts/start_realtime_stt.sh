#!/bin/bash
# =============================================================================
# start_realtime_stt.sh — 啟動 aiSpeechMulti FastAPI 伺服器（供桌面捷徑使用）
# =============================================================================
#
# 用途：由桌面 .app 捷徑呼叫。
#   1. 若 FastAPI 伺服器尚未在 :8000 就緒，自動啟動（背景常駐）。
#   2. 等待伺服器就緒後退出（讓 AppleScript 繼續開 Chrome 視窗）。
#
# 注意：此腳本使用 conda 環境（aiSpeech_project_nightly），
#       而非 venv，請勿改為 source venv/bin/activate。
# =============================================================================

# ── 自動定位（搬機免改路徑）──────────────────────────────────────────────────
# PROJECT_DIR = 本腳本(scripts/)的上層目錄；conda env 名可用 AISPEECH_CONDA_ENV 覆蓋。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONDA_ENV="${AISPEECH_CONDA_ENV:-aiSpeech_project_nightly}"

# 自動尋找 conda.sh（miniforge / miniconda / anaconda / mambaforge 常見位置）
CONDA_SH=""
for _c in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/mambaforge" \
          "/opt/homebrew/Caskroom/miniforge/base" "/opt/miniconda3" "/opt/anaconda3"; do
    if [ -f "$_c/etc/profile.d/conda.sh" ]; then CONDA_SH="$_c/etc/profile.d/conda.sh"; break; fi
done

LOG_FILE="/tmp/aiSpeechMulti_app_api.log"
HEALTH_URL="http://localhost:8000/api/health"

cd "$PROJECT_DIR"

if [ -z "$CONDA_SH" ]; then
    echo "$(date '+%H:%M:%S') [launcher] ❌ 找不到 conda（miniforge/miniconda…）" >> "$LOG_FILE"
    echo "❌ 找不到 conda，請確認已安裝且 env=$CONDA_ENV 存在" >&2
    exit 1
fi

# ── 若伺服器尚未就緒，啟動它 ─────────────────────────────────────────────────
if ! curl -s -m 1 "$HEALTH_URL" >/dev/null 2>&1; then
    echo "$(date '+%H:%M:%S') [launcher] 伺服器未就緒，啟動中..." >> "$LOG_FILE"

    # 啟動 conda（非互動式 shell 需要手動 source）
    # shellcheck source=/dev/null
    source "$CONDA_SH"
    conda activate "$CONDA_ENV"

    # 背景啟動 FastAPI，stdout/stderr 導向 log，與終端機解除關聯
    nohup python app_api.py >> "$LOG_FILE" 2>&1 &
    disown

    echo "$(date '+%H:%M:%S') [launcher] FastAPI PID=$! 已在背景啟動" >> "$LOG_FILE"
else
    echo "$(date '+%H:%M:%S') [launcher] 伺服器已就緒，略過啟動" >> "$LOG_FILE"
fi

# ── 等待伺服器就緒（最長 60 秒）────────────────────────────────────────────
for i in $(seq 1 60); do
    if curl -s -m 1 "$HEALTH_URL" >/dev/null 2>&1; then
        echo "$(date '+%H:%M:%S') [launcher] ✅ 就緒（第 ${i} 秒）" >> "$LOG_FILE"
        exit 0
    fi
    sleep 1
done

echo "$(date '+%H:%M:%S') [launcher] ❌ 伺服器啟動逾時（60 秒）" >> "$LOG_FILE"
echo "❌ aiSpeechMulti 伺服器啟動逾時，請查看 $LOG_FILE" >&2
exit 1
