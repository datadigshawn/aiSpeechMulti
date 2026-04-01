#!/bin/bash
# ============================================================
# aiSpeech Local v2.0（機密版）安裝腳本
# 雙引擎：faster-whisper + SenseVoiceSmall
# 適用於 macOS (Apple Silicon: M1/M2/M3/M4)
# ============================================================

set -e

echo "🔒 aiSpeech Local v2.0 雙引擎安裝程式"
echo "======================================="
echo ""

# ── 1. 檢查系統需求 ──
echo "📋 檢查系統需求..."

if ! command -v python3 &> /dev/null; then
    echo "❌ 需要 Python 3.10+：brew install python@3.11"
    exit 1
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "   ✅ Python $PYVER"

if ! command -v brew &> /dev/null; then
    echo "❌ 需要 Homebrew"
    exit 1
fi
echo "   ✅ Homebrew"

# ── 2. 安裝 ffmpeg ──
echo ""
echo "📦 安裝系統依賴..."
if ! command -v ffmpeg &> /dev/null; then
    echo "   安裝 ffmpeg..."
    brew install ffmpeg
else
    echo "   ✅ ffmpeg 已安裝"
fi

# ── 3. Python 虛擬環境 ──
echo ""
echo "🐍 建立虛擬環境..."

VENV_DIR="$HOME/aiSpeech_local_env"

if [ -d "$VENV_DIR" ]; then
    echo "   虛擬環境已存在：$VENV_DIR"
    read -p "   重新建立？(y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$VENV_DIR"
        python3 -m venv "$VENV_DIR"
    fi
else
    python3 -m venv "$VENV_DIR"
    echo "   ✅ 已建立：$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# ── 4. 安裝 Python 套件 ──
echo ""
echo "📚 安裝 Python 套件（雙引擎）..."
pip install --upgrade pip

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pip install -r "$SCRIPT_DIR/requirements.txt"

echo "   ✅ 套件安裝完成"

# ── 5. 預下載模型 ──
echo ""
echo "🤖 預下載模型..."
echo ""

python3 << 'PYEOF'
import sys

# 引擎 A：faster-whisper
print("   [A] faster-whisper 模型...")
try:
    from faster_whisper import WhisperModel
    for m in ["large-v3", "medium"]:
        print(f"       下載 {m}...")
        WhisperModel(m, device="cpu", compute_type="int8")
        print(f"       ✅ {m}")
except Exception as e:
    print(f"       ⚠️  失敗：{e}")

# 引擎 B：SenseVoiceSmall
print("   [B] SenseVoiceSmall 模型...")
try:
    from funasr import AutoModel
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        trust_remote_code=True,
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 30000},
        device="cpu",
    )
    print("       ✅ SenseVoiceSmall + fsmn-vad")
except Exception as e:
    print(f"       ⚠️  失敗：{e}")
    print("       （首次啟動時會自動下載）")
PYEOF

# ── 6. 工作目錄 ──
echo ""
echo "📁 建立工作目錄..."
mkdir -p "$HOME/aiSpeech_incoming"
mkdir -p "$HOME/aiSpeech_transcripts"
echo "   ✅ 監控目錄：$HOME/aiSpeech_incoming"
echo "   ✅ 結果目錄：$HOME/aiSpeech_transcripts"

# ── 7. 啟動腳本 ──
echo ""
echo "🚀 建立啟動腳本..."

LAUNCH="$SCRIPT_DIR/start.sh"
cat > "$LAUNCH" << 'EOF'
#!/bin/bash
source "$HOME/aiSpeech_local_env/bin/activate"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
streamlit run "$DIR/app.py" \
    --server.address 0.0.0.0 \
    --server.port 8501 \
    --server.maxUploadSize 500 \
    --browser.gatherUsageStats false
EOF
chmod +x "$LAUNCH"
echo "   ✅ $LAUNCH"

# ── 完成 ──
echo ""
echo "============================================================"
echo "✅ aiSpeech Local v2.0 安裝完成！"
echo ""
echo "啟動：cd $SCRIPT_DIR && ./start.sh"
echo "開啟：http://localhost:8501"
echo ""
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || echo '<本機IP>')
echo "內網存取：http://$LOCAL_IP:8501"
echo ""
echo "🔒 所有資料皆在本機處理，不傳送至任何外部伺服器"
echo "============================================================"
