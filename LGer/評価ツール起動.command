#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

cleanup() {
    kill $SERVER_PID 2>/dev/null
    osascript -e 'tell application "Terminal" to close front window'
}
trap cleanup EXIT

# 依存パッケージのチェック
if ! python3 -c "import flask, anthropic" 2>/dev/null; then
    echo "必要なパッケージをインストールしています..."
    pip3 install flask anthropic
fi

python3 app.py &
SERVER_PID=$!
sleep 2
open http://127.0.0.1:5100
wait $SERVER_PID
