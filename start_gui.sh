#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || command -v python)
[ -z "$PY" ] && { echo "Python 3 not found. Install it first."; read -rp "Press Enter..."; exit 1; }
"$PY" taxis_gui.py || { echo "If tkinter is missing: Ubuntu 'sudo apt install python3-tk' | macOS 'brew install python-tk'"; read -rp "Press Enter..."; }
