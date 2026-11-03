#!/usr/bin/env bash
# Cyno Control for macOS: double-click this file in Finder.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Run 'bash setup-mac.sh' first."
  read -r -p "Press Enter to close."
  exit 1
fi
exec .venv/bin/python -m cyno.control
