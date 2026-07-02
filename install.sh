#!/usr/bin/env bash
# One-shot installer for the Grain Size Analyzer.
# Safe to re-run: existing .venv is reused, deps are (re)installed idempotently.
set -euo pipefail

# --- Resolve the project root (directory containing this script) -------------
# `readlink -f` is GNU; macOS may not have it, so fall back gracefully.
resolve_dir() {
    local src="$1"
    if command -v readlink >/dev/null 2>&1 && readlink -f "$src" >/dev/null 2>&1; then
        dirname "$(readlink -f "$src")"
    else
        # macOS fallback: resolve via cd/pwd (handles relative invocation).
        cd "$(dirname "$src")" >/dev/null 2>&1 && pwd
    fi
}
PROJECT_ROOT="$(resolve_dir "${BASH_SOURCE[0]:-$0}")"
cd "$PROJECT_ROOT"

# --- Check for python3 --------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 was not found on your PATH." >&2
    echo "Please install Python 3.9 or newer:" >&2
    echo "  https://www.python.org/downloads/" >&2
    echo "  (Debian/Ubuntu: sudo apt install python3 python3-venv)" >&2
    exit 1
fi

# --- Require Python >= 3.9 ----------------------------------------------------
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    PYVER="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
    echo "Error: Python >= 3.9 is required, but found Python $PYVER." >&2
    echo "Please upgrade: https://www.python.org/downloads/" >&2
    exit 1
fi

# --- Create the virtual environment (skip if it exists) -----------------------
if [ -d .venv ]; then
    echo "==> Reusing existing virtual environment at .venv"
else
    echo "==> Creating virtual environment at .venv"
    if ! python3 -m venv .venv; then
        echo "Error: failed to create a virtual environment." >&2
        echo "On Debian/Ubuntu you may need: sudo apt install python3-venv" >&2
        exit 1
    fi
fi

# --- Install dependencies ------------------------------------------------------
echo "==> Upgrading pip"
.venv/bin/python -m pip install --upgrade pip --quiet

echo "==> Installing dependencies from requirements.txt"
.venv/bin/python -m pip install -r requirements.txt --quiet

# --- Done ----------------------------------------------------------------------
echo
echo "Install complete."
echo
echo "Next steps:"
echo "  ./run.sh          # start the server (or: make run)"
echo
echo "Then open:  http://localhost:5066"
echo "(Set PORT to use a different port, e.g.: PORT=8080 ./run.sh)"
