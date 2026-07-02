#!/usr/bin/env bash
# Run the Grain Size Analyzer. Self-heals: installs the venv if missing.
set -euo pipefail

# --- Resolve the project root (directory containing this script) -------------
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

# --- Ensure the virtual environment exists ------------------------------------
if [ ! -x .venv/bin/python ]; then
    echo "==> No virtual environment found; running ./install.sh first"
    ./install.sh
fi

# --- Start the app -------------------------------------------------------------
# PORT is passed through to the app (default 5066 inside app.py).
echo "==> Starting Grain Size Analyzer on http://localhost:${PORT:-5066}"
exec .venv/bin/python app.py
