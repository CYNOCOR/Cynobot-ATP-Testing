#!/usr/bin/env bash
# Cyno Bot: after pulling new code, install any new Python packages. Quick, safe to run any time.
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
if [ ! -x .venv/bin/python ]; then echo "Run 'bash setup-mac.sh' first."; exit 1; fi
uv pip install --python .venv -r requirements.txt && echo "Done. Now open Cyno Control."
