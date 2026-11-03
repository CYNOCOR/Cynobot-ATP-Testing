#!/usr/bin/env bash
# Cyno Bot — start everything on macOS:  bash start-mac.sh
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-7860}"

[ -x .venv/bin/python ] || { echo "Run 'bash setup-mac.sh' first."; exit 1; }

# Ollama powers offline mode; make sure it is running.
if ! curl -s http://localhost:11434/api/version >/dev/null; then
  if [ -d /Applications/Ollama.app ]; then open -a Ollama
  elif command -v ollama >/dev/null 2>&1; then (nohup ollama serve >/dev/null 2>&1 &)
  else echo "[!] Ollama not found: offline mode will not answer."; fi
fi

# Open both displays once the server answers.
(
  for _ in $(seq 1 60); do curl -s "http://localhost:$PORT/api/state" >/dev/null && break; sleep 1; done
  for page in chest face; do
    open -a "Google Chrome" "http://localhost:$PORT/$page/" 2>/dev/null || open "http://localhost:$PORT/$page/"
  done
) &

echo "Starting Cyno on http://localhost:$PORT  (Ctrl+C to stop)"
exec .venv/bin/python -m cyno.server
