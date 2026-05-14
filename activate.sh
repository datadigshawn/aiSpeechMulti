#!/usr/bin/env bash
# aiSpeechMulti 環境啟動腳本
# 用法：source ./activate.sh           # 啟動主力環境 (nightly)
#       source ./activate.sh stable    # 啟動穩定環境

ENV_NAME="aiSpeech_project_${1:-nightly}"

# 確保 conda 函式已載入（從 miniforge3）
if ! type conda >/dev/null 2>&1; then
  source "$HOME/miniforge3/etc/profile.d/conda.sh"
fi

conda activate "$ENV_NAME" && \
  echo "✅ 已啟動 conda 環境：$ENV_NAME" && \
  echo "   Python: $(python --version 2>&1)" && \
  echo "   路徑:   $(which python)"
