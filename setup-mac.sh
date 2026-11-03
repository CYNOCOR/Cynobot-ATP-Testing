#!/usr/bin/env bash
# Cyno Bot — one-time setup for macOS. Safe to re-run.
#   Double-click is not supported on .sh; run in Terminal:  bash setup-mac.sh
set -euo pipefail
cd "$(dirname "$0")"

OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2:3b}"
step() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }
warn() { printf "\033[1;33m[!] %s\033[0m\n" "$1"; }

step "1/6  uv (Python manager)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

step "2/6  Python 3.12 environment (.venv)"
[ -d .venv ] || uv venv --python 3.12 .venv

step "3/6  Python packages (first run downloads ~2 GB, be patient)"
uv pip install --python .venv -r requirements.txt

step "4/6  Ollama (offline brain)"
if ! command -v ollama >/dev/null 2>&1 && [ ! -d /Applications/Ollama.app ]; then
  if command -v brew >/dev/null 2>&1; then
    brew install ollama
  else
    warn "Ollama is not installed. Download it from https://ollama.com/download, open it once, then re-run this script."
    exit 1
  fi
fi
if ! curl -s http://localhost:11434/api/version >/dev/null; then
  if [ -d /Applications/Ollama.app ]; then open -a Ollama; else (nohup ollama serve >/dev/null 2>&1 &); fi
  for _ in $(seq 1 30); do curl -s http://localhost:11434/api/version >/dev/null && break; sleep 1; done
fi
OLLAMA_BIN="$(command -v ollama || echo /Applications/Ollama.app/Contents/Resources/ollama)"
"$OLLAMA_BIN" pull "$OLLAMA_MODEL"

step "5/6  Gemini API key (.env)"
.venv/bin/python -m cyno.setup_env

step "6/6  Download, warm up and benchmark offline models"
.venv/bin/python -m cyno.prepare_offline

.venv/bin/python -m cyno.control.install_icons

printf "\n\033[1;32mSetup complete.\033[0m Open the control app: double-click 'Cyno Control.command'  (or run: bash start-mac.sh)\n"
