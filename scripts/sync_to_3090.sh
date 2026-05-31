#!/usr/bin/env bash
# ============================================================================
# sync_to_3090.sh — M2 ↔ Windows 3090 桌機 fine-tune 工作流自動化
# ============================================================================
#
# 用法：
#   ./scripts/sync_to_3090.sh                  # = up（預設）
#   ./scripts/sync_to_3090.sh up               # git push + rsync audio 上去
#   ./scripts/sync_to_3090.sh down [run_name]  # 拉 finetune_runs/[run_name] 回 M2
#                                              # 不帶 run_name 會列出遠端可用 run 讓你選
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
RUN_NAME=""
for arg in "$@"; do
    case "$arg" in
        -n|--dry-run) DRY_RUN="--dry-run" ;;
        -h|--help)    awk 'NR==1{next} /^[^#]/{exit} {sub(/^# ?/,""); print}' "$0"; exit 0 ;;
        up|down|audio|code|status) CMD="$arg" ;;
        # down 可帶第二個 positional 指定 run 名稱
        *)
            if [ "$CMD" = "down" ] && [ -z "$RUN_NAME" ] && [[ "$arg" != -* ]]; then
                RUN_NAME="$arg"
            else
                echo "❌ 未知參數：$arg" >&2; exit 2
            fi
            ;;
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
        # 支援所有 manifest 接受的音檔格式（與 build_golden_manifest.py 一致）
        # 用 find 收集成 array，一次 scp（避免每檔起 ssh session）
        local -a audio_files
        while IFS= read -r -d '' f; do audio_files+=("$f"); done < <(
            find "$LOCAL_AUDIO" -maxdepth 1 -type f \
                \( -name "*.wav" -o -name "*.mp3" -o -name "*.m4a" \
                   -o -name "*.flac" -o -name "*.ogg" -o -name "*.aac" \) \
                -print0 2>/dev/null
        )
        local audio_count="${#audio_files[@]}"
        echo "🎵 scp audio → 3090（${audio_count} 個音檔；rsync 不在桌機，用 scp 全量傳）"
        if [ -n "$DRY_RUN" ]; then
            echo "  (dry-run: 會傳 ${audio_count} 個音檔到 ${REMOTE_AUDIO})"
            return
        fi
        [ "$audio_count" -gt 0 ] && scp "${audio_files[@]}" "$REMOTE_AUDIO"
    fi
}

list_remote_runs() {
    # 列出遠端 finetune_runs/ 內所有子目錄，方便 user 挑哪個 run 拉
    # 只列名稱避免 PowerShell escape 巢狀引號災難；要看大小自己 ssh 進去看
    echo "📋 遠端 finetune_runs/ 內可用的訓練 run（請帶 run 名稱回呼）："
    ssh "$HOST" "powershell -NoProfile -Command \"Get-ChildItem '${REMOTE_PATH}/experiments/finetune_runs' -Directory -Name\"" 2>&1 \
        | grep -v WARNING | grep -v "post-quantum" | grep -v "^$" \
        | sed 's/^/  /'
    echo ""
    echo "用法：./scripts/sync_to_3090.sh down <run_name>"
    echo "  (要看 run 大小：ssh ${HOST} 'powershell -Command \"Get-ChildItem ${REMOTE_PATH}/experiments/finetune_runs/<name> -Recurse -File | Measure-Object Length -Sum\"')"
}

pull_runs() {
    mkdir -p "$LOCAL_RUNS"

    # 沒指定 run name → 列出可用 runs 提示使用者選
    if [ -z "$RUN_NAME" ]; then
        list_remote_runs
        return
    fi

    local remote_run="${REMOTE_PATH}/experiments/finetune_runs/${RUN_NAME}"
    local local_run="${LOCAL_RUNS}${RUN_NAME}"
    mkdir -p "$local_run"

    if $USE_RSYNC; then
        echo "📥 rsync finetune_runs/${RUN_NAME}/ ← 3090（增量）"
        rsync -avh --progress ${DRY_RUN} "${HOST}:${remote_run}/" "${local_run}/"
    else
        # 為何不用 wildcard：scp "host:path/*" 在 Windows OpenSSH 不會做 remote glob
        # （Unix scp 會把 * 送到 remote shell 展開，Windows OpenSSH 不會）
        # 改用 directory copy：把整個 run 目錄複製到 finetune_runs/ 下
        echo "📥 scp finetune_runs/${RUN_NAME}/ ← 3090（rsync 不在桌機；用 scp -r）"
        if [ -n "$DRY_RUN" ]; then
            echo "  (dry-run: 會拉 ${HOST}:${remote_run} 到 ${LOCAL_RUNS})"
            return
        fi
        scp -r "${HOST}:${remote_run}" "${LOCAL_RUNS}"
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
