#!/usr/bin/env bash
# ============================================================================
# sync_to_3090.sh — M2 ↔ Windows 3090 桌機 fine-tune 工作流自動化
# ============================================================================
#
# 用法：
#   ./scripts/sync_to_3090.sh                  # = up（預設）
#   ./scripts/sync_to_3090.sh up               # git push + rsync audio 上去
#   ./scripts/sync_to_3090.sh down             # rsync 拉 finetune_runs/ 回 M2
#   ./scripts/sync_to_3090.sh audio            # 只 rsync audio 上去
#   ./scripts/sync_to_3090.sh code             # 只 git push（並在桌機 git pull）
#   ./scripts/sync_to_3090.sh status           # 看本機 vs 桌機 audio 數量差
#
# 旗標：
#   -n, --dry-run     不執行，只印 rsync 預覽
#   -h, --help        看這份說明
#
# 設定（在 ~/.aispeech_3090.env 或 export 設定）：
#   AISPEECH_3090_HOST   SSH host alias（必填，例：3090）
#   AISPEECH_3090_PATH   桌機端專案路徑（預設：/Y/Projects/aiSpeechMulti）
#
# 詳見：docs/finetune_setup_3090.md §1.5
#       Obsidian: aiSpeechMulti/docs/scp 同步指令備忘.md
# ============================================================================
set -euo pipefail

# ── 設定 ─────────────────────────────────────────────────────────────────
ENV_FILE="${HOME}/.aispeech_3090.env"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

HOST="${AISPEECH_3090_HOST:-}"
REMOTE_PATH="${AISPEECH_3090_PATH:-Y:/Projects/aiSpeechMulti}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_AUDIO="${REPO_ROOT}/experiments/golden_dataset/audio/"
LOCAL_RUNS="${REPO_ROOT}/experiments/finetune_runs/"
REMOTE_AUDIO="${HOST}:${REMOTE_PATH}/experiments/golden_dataset/audio/"
REMOTE_RUNS="${HOST}:${REMOTE_PATH}/experiments/finetune_runs/"

# ── 旗標解析 ─────────────────────────────────────────────────────────────
DRY_RUN=""
CMD="up"
for arg in "$@"; do
    case "$arg" in
        -n|--dry-run) DRY_RUN="--dry-run" ;;
        -h|--help)    awk 'NR==1{next} /^[^#]/{exit} {sub(/^# ?/,""); print}' "$0"; exit 0 ;;
        up|down|audio|code|status) CMD="$arg" ;;
        *) echo "❌ 未知參數：$arg" >&2; exit 2 ;;
    esac
done

# ── 必要條件檢查 ─────────────────────────────────────────────────────────
if [ -z "$HOST" ] && [ "$CMD" != "status" ]; then
    echo "❌ 沒設定 AISPEECH_3090_HOST。範例："
    echo "   echo 'AISPEECH_3090_HOST=3090' >> ${ENV_FILE}"
    echo "   echo 'AISPEECH_3090_PATH=/Y/Projects/aiSpeechMulti' >> ${ENV_FILE}"
    exit 2
fi
# 偵測 rsync（兩端都要有；Windows 預設沒裝）
USE_RSYNC=false
if command -v rsync >/dev/null 2>&1 && [ "$CMD" != "status" ] && [ -n "$HOST" ]; then
    if ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "rsync --version" >/dev/null 2>&1; then
        USE_RSYNC=true
    fi
fi

# ── 子命令 ───────────────────────────────────────────────────────────────
push_code() {
    cd "$REPO_ROOT"
    local branch
    branch="$(git rev-parse --abbrev-ref HEAD)"
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "⚠️  有未 commit 變動，先 commit 再跑（避免 3090 端 git pull 拿到舊版）"
        git status --short
        exit 1
    fi
    echo "📤 git push origin ${branch}"
    [ -n "$DRY_RUN" ] && { echo "  (dry-run skip)"; return; }
    git push origin "$branch"
    echo "🔄 桌機端執行 git pull"
    # 用 PowerShell 友善寫法（cd 與 git pull 用 ; 串接；PowerShell 不認 &&）
    ssh "$HOST" "powershell -NoProfile -Command \"cd ${REMOTE_PATH}; git pull origin ${branch}\"" || \
        echo "⚠️  桌機 git pull 失敗（請手動到桌機 git pull）"
}

push_audio() {
    if $USE_RSYNC; then
        echo "🎵 rsync audio → 3090（增量）"
        rsync -avh --progress ${DRY_RUN} "$LOCAL_AUDIO" "$REMOTE_AUDIO"
    else
        local wav_count
        wav_count=$(find "$LOCAL_AUDIO" -name "*.wav" 2>/dev/null | wc -l | tr -d ' ')
        echo "🎵 scp audio → 3090（${wav_count} 個 .wav；rsync 不在桌機，用 scp 全量傳）"
        if [ -n "$DRY_RUN" ]; then
            echo "  (dry-run: 會傳 ${wav_count} 個 wav 到 ${REMOTE_AUDIO})"
            return
        fi
        # 用 scp -r 上傳；Windows OpenSSH 路徑用 /C:/ 或直接 Windows 樣式
        scp -r "$LOCAL_AUDIO"*.wav "$REMOTE_AUDIO"
    fi
}

pull_runs() {
    mkdir -p "$LOCAL_RUNS"
    if $USE_RSYNC; then
        echo "📥 rsync finetune_runs/ ← 3090（增量）"
        rsync -avh --progress ${DRY_RUN} "$REMOTE_RUNS" "$LOCAL_RUNS"
    else
        echo "📥 scp finetune_runs/ ← 3090（rsync 不在桌機，用 scp 全量）"
        if [ -n "$DRY_RUN" ]; then
            echo "  (dry-run: 會從 ${REMOTE_RUNS} 拉檔到 ${LOCAL_RUNS})"
            return
        fi
        scp -r "${REMOTE_RUNS}*" "$LOCAL_RUNS"
    fi
}

show_status() {
    local local_count
    local_count=$(find "$LOCAL_AUDIO" -name "*.wav" 2>/dev/null | wc -l | tr -d ' ')
    echo "📊 本機 audio 檔數：${local_count}"
    if [ -n "$HOST" ]; then
        echo "📊 桌機 audio 檔數："
        ssh "$HOST" "powershell -Command '(Get-ChildItem ${REMOTE_PATH}/experiments/golden_dataset/audio/*.wav).Count'" || \
            echo "  (桌機連不上或路徑不存在)"
    fi
}

# ── 派發 ─────────────────────────────────────────────────────────────────
case "$CMD" in
    up)      push_code; push_audio ;;
    down)    pull_runs ;;
    audio)   push_audio ;;
    code)    push_code ;;
    status)  show_status ;;
esac

echo "✅ ${CMD} 完成"
